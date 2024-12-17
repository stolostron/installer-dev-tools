#!/usr/bin/env python3
# Copyright (c) 2024 Red Hat, Inc.
# Copyright Contributors to the Open Cluster Management project
# Assumes: Python 3.6+

import logging
import os
import re
import yaml

import utils

from packaging import version

def add_pull_secret_override(deployment):
    """
    Adds an image pull secret environment variable to a Kubernetes deployment YAML file.

    This function scans the provided deployment file for the `env:` or `env: {}` section and adds an environment
    variable `AGENT_IMAGE_PULL_SECRET` with a value derived from `.Values.global.pullSecret`, enclosed in 
    Helm flow control (`if`/`end`) blocks. The file is updated in place.

    Args:
        deployment (str): The path to the Kubernetes deployment YAML file where the image pull secret
                          environment variable will be added.
    """
    with open(deployment, 'r') as f:
        lines = f.readlines()

    for i, line in enumerate(lines):
        if line.strip() == "env:" or line.strip() == "env: {}":
            logging.info("Adding image pull secret environment variable to managed-serviceaccount deployment")
            lines[i] = """        env:
{{- if .Values.global.pullSecret }}
        - name: AGENT_IMAGE_PULL_SECRET
          value: {{ .Values.global.pullSecret }}
{{- end }}
"""
        a_file = open(deployment, "w")
        a_file.writelines(lines)
        a_file.close()

def find_templates_of_type(helm_chart, kind):
    """
    Find all templates of a specified Kubernetes resource type (kind) in a Helm chart.

    This function searches the 'templates' directory of a given Helm chart for YAML files 
    that define resources of the specified 'kind'. It returns a list of file paths that 
    match the given resource type.

    Args:
        helm_chart (str): The path to the Helm chart directory.
        kind (str): The Kubernetes resource kind to search for (e.g., 'ClusterRole', 'Service').

    Returns:
        list: A list of file paths to templates that match the specified resource kind.
    """
    resources = []
    templates_dir = os.path.join(helm_chart, "templates")
    
    # Check if the templates directory exists
    if not os.path.exists(templates_dir):
        raise FileNotFoundError(f"Templates directory not found: {templates_dir}")

    # Iterate over YAML files in the templates directory
    for filename in os.listdir(templates_dir):
        if filename.endswith((".yaml", ".yml")):
            file_path = os.path.join(templates_dir, filename)
            
            try:
                with open(file_path, 'r') as f:
                    file_yaml = yaml.safe_load(f)

                if file_yaml and file_yaml.get('kind') == kind:
                    resources.append(file_path)
            except yaml.YAMLError as e:
                logging.error(f"Failed to parse YAML file: {file_path}: {e}")

            except KeyError as e:
                logging.error(f"'kind' field missing in file: {file_path}")

    return resources

def fix_env_var_image_references(helm_chart, image_key_mapping):
    """
    Fixes image references in container environment variables within deployment templates and updates the 
    `values.yaml` file for Helm charts.

    This function performs the following tasks:
    - Scans the Helm chart's `Deployment` templates for environment variables containing image references.
    - For each environment variable with an image reference (ending with '_IMAGE'), it replaces the value with
      a Helm flow control template that references `.Values.global.imageOverrides`.
    - Adds the image key mappings from the deployment environment variables to the `values.yaml` file under 
      `global.imageOverrides`, ensuring that the image references are explicitly defined.
    - If an image reference in the deployment template does not exist in `imageMappings` (the provided mapping
      of image references), the function will log a critical error and exit.

    Args:
        helm_chart (str): Path to the Helm chart directory that contains the `values.yaml` file and deployment templates.
        image_key_mapping (dict): A mapping of image keys to image references to be inserted into the `values.yaml` file.
    """
    logging.info("Fixing image references in container 'env' section in deployments and values.yaml ...")
    
    # Path to the values.yaml file
    values_yaml = os.path.join(helm_chart, "values.yaml")

    # Check if the values.yaml file exists
    if not os.path.exists(values_yaml):
        logging.error(f"{values_yaml} does not exist. Skipping environment variable image reference updates.")
        return

    with open(values_yaml, 'r') as f:
        values = yaml.safe_load(f)
    deployments = find_templates_of_type(helm_chart, 'Deployment')

    imageKeys = []
    for deployment in deployments:
        with open(deployment, 'r') as f:
            deploy = yaml.safe_load(f)
        
        containers = deploy['spec']['template']['spec']['containers']
        for container in containers:
            if 'env' not in container: 
                continue
            
            for env in container['env']:
                image_key = env['name']
                if image_key.endswith('_IMAGE') == False:
                    continue
                image_key = utils.parse_image_ref(env['value'])['repository']
                try:
                    image_key = image_key_mapping[image_key]
                except KeyError:
                    logging.critical("No image key mapping provided for imageKey: %s" % image_key)
                    exit(1)
                imageKeys.append(image_key)
                env['value'] = "{{ .Values.global.imageOverrides." + image_key + " }}"
        with open(deployment, 'w') as f:
            yaml.dump(deploy, f, width=float("inf"))

    for imageKey in imageKeys:
        values['global']['imageOverrides'][imageKey] = ""

    with open(values_yaml, 'w') as f:
        yaml.dump(values, f, width=float("inf"))
    logging.info("Image container env references in deployments and values.yaml updated successfully.\n")

def fix_image_references(helm_chart, image_key_mapping):
    """
    Fixes image and pull policy references in container deployments and updates the `values.yaml` file in a Helm chart.

    This function performs the following tasks:
    - Scans the Helm chart's `Deployment` templates for image references in the `image` field.
    - Replaces image references with Helm flow control templates (`{{ .Values.global.imageOverrides.<image_key> }}`).
    - Sets the `imagePullPolicy` to Helm flow control (`{{ .Values.global.pullPolicy }}`) for each container.
    - Updates the `values.yaml` file by adding the corresponding image keys under `global.imageOverrides`.
    - If an image key referenced in the deployment does not exist in `imageMappings` (the provided mapping of image keys),
      the function will log a critical error and exit.

    Args:
        helm_chart (str): Path to the Helm chart directory containing the `values.yaml` file and deployment templates.
        image_key_mapping (dict): A dictionary mapping image keys to image references used in the Helm chart.
    """
    logging.info("Fixing image and pull policy references in deployments and values.yaml ...")

    # Path to the values.yaml file
    values_yaml = os.path.join(helm_chart, "values.yaml")

    # Check if the values.yaml file exists
    if not os.path.exists(values_yaml):
        logging.error(f"{values_yaml} does not exist. Skipping image and pull policy updates.")
        return

    with open(values_yaml, 'r') as f:
        values = yaml.safe_load(f)
    
    deployments = find_templates_of_type(helm_chart, 'Deployment')
    imageKeys = []

    for deployment in deployments:
        with open(deployment, 'r') as f:
            deploy = yaml.safe_load(f)
        
        containers = deploy['spec']['template']['spec']['containers']
        for container in containers:
            image_key = utils.parse_image_ref(container['image'])["repository"]

            try:
                image_key = image_key_mapping[image_key]
            except KeyError:
                logging.critical("No image key mapping provided for imageKey: %s" % image_key)
                exit(1)

            imageKeys.append(image_key)

            container['image'] = "{{ .Values.global.imageOverrides." + image_key + " }}"
            container['imagePullPolicy'] = "{{ .Values.global.pullPolicy }}"

            args = container['args']
            refreshed_args = []
            for arg in args:
                if "--agent-image-name" not in arg:
                    refreshed_args.append(arg)
                else:
                    refreshed_args.append("--agent-image-name="+"{{ .Values.global.imageOverrides." + image_key + " }}")
            container['args'] = refreshed_args

        with open(deployment, 'w') as f:
            yaml.dump(deploy, f, width=float("inf"))

    values['global']['imageOverrides'].pop('imageOverride', None)
    for imageKey in imageKeys:
        values['global']['imageOverrides'][imageKey] = ""

    with open(values_yaml, 'w') as f:
        yaml.dump(values, f, width=float("inf"))
    logging.info("Image references and pull policy in deployments and values.yaml updated successfully.\n")
    
def fix_image_references_for_addon_template(helm_chart, image_key_mapping):
    """
    Fixes image references in addon templates and updates the `values.yaml` file in a Helm chart.

    This function performs the following tasks:
    - Scans the Helm chart's `AddOnTemplate` for image references in the `image` field of container workloads.
    - Replaces image references with Helm flow control templates (`{{ .Values.global.imageOverrides.<image_key> }}`).
    - Updates the `values.yaml` file by adding the corresponding image keys under `global.imageOverrides`.
    - If an image key referenced in the addon template does not exist in `imageMappings` (the provided mapping of image keys),
      the function will log a critical error and exit.

    Args:
        helm_chart (str): Path to the Helm chart directory containing the `values.yaml` file and addon template.
        image_key_mapping (dict): A dictionary mapping image keys to image references used in the addon templates.
    """

    logging.info("Fixing image references in addon templates and values.yaml ...")

    # Path to the values.yaml file
    values_yaml = os.path.join(helm_chart, "values.yaml")
    
    # Check if the values.yaml file exists
    if not os.path.exists(values_yaml):
        logging.error(f"{values_yaml} does not exist. Skipping image and pull policy updates.")
        return

    with open(values_yaml, 'r') as f:
        values = yaml.safe_load(f)

    addonTemplates = find_templates_of_type(helm_chart, 'AddOnTemplate')
    imageKeys = []

    for addonTemplate in addonTemplates:
        with open(addonTemplate, 'r') as f:
            templateContent = yaml.safe_load(f)

        agentSpec = templateContent['spec']['agentSpec']
        if 'workload' not in agentSpec:
            return

        workload = agentSpec['workload']
        if 'manifests' not in workload:
                return

        manifests = workload['manifests']
        imageKeys = []

        for manifest in manifests:
            if manifest['kind'] == 'Deployment':
                containers = manifest['spec']['template']['spec']['containers']

                for container in containers:
                    image_key = utils.parse_image_ref(container['image'])["repository"]

                    try:
                        image_key = image_key_mapping[image_key]
                    except KeyError:
                        logging.critical("No image key mapping provided for imageKey: %s" % image_key)
                        exit(1)

                    imageKeys.append(image_key)
                    container['image'] = "{{ .Values.global.imageOverrides." + image_key + " }}"

        with open(addonTemplate, 'w') as f:
            yaml.dump(templateContent, f, width=float("inf"))
        logging.info("AddOnTemplate updated with image override successfully. \n")

    if len(imageKeys) == 0:
        return

    values['global']['imageOverrides'].pop('imageOverride', None)
    for imageKey in imageKeys:
        values['global']['imageOverrides'][imageKey] = ""

    with open(values_yaml, 'w') as f:
        yaml.dump(values, f, width=float("inf"))
    logging.info("Image references and pull policy in addon templates and values.yaml updated successfully.\n")

# injectAnnotationsForAddonTemplate injects following annotations for deployments in the AddonTemplate:
# - target.workload.openshift.io/management: '{"effect": "PreferredDuringScheduling"}'
def inject_annotations_for_addon_template(helm_chart):
    logging.info("Injecting Annotations for deployments in the AddonTemplate ...")
    
    addonTemplates = find_templates_of_type(helm_chart, 'AddOnTemplate')
    for addonTemplate in addonTemplates:
        injected = False
        with open(addonTemplate, 'r') as f:
            templateContent = yaml.safe_load(f)
            agentSpec = templateContent['spec']['agentSpec']
            if 'workload' not in agentSpec:
                return

            workload = agentSpec['workload']
            if 'manifests' not in workload:
                return

            manifests = workload['manifests']
            for manifest in manifests:
                if manifest['kind'] == 'Deployment':
                    metadata = manifest['spec']['template']['metadata']
                    if 'annotations' not in metadata:
                        metadata['annotations'] = {}

                    if 'target.workload.openshift.io/management' not in metadata['annotations']:
                        metadata['annotations']['target.workload.openshift.io/management'] = '{"effect": "PreferredDuringScheduling"}'
                        injected = True
        if injected:
            with open(addonTemplate, 'w') as f:
                yaml.dump(templateContent, f, width=float("inf"))
            logging.info("Annotations injected successfully.\n")

def inject_helm_flow_control(deployment, branch, sizes={}):
    logging.info("Adding Helm flow control for NodeSelector, Proxy Overrides, and SeccompProfile ...")

    with open(deployment, "r") as f:
        lines = f.readlines()
        f.seek(0) # Go back to the beginning of the file
        deploy = yaml.safe_load(f)

    for i, line in enumerate(lines):
        if line.strip() == "nodeSelector: \'\'":
            lines[i] = """{{- with .Values.hubconfig.nodeSelector }}
      nodeSelector:
{{ toYaml . | indent 8 }}
{{- end }}
"""     
        if line.strip() == "imagePullSecrets: \'\'":
            lines[i] = """{{- if .Values.global.pullSecret }}
      imagePullSecrets:
      - name: {{ .Values.global.pullSecret }}
{{- end }}
"""

        if line.strip() == "tolerations: \'\'":
            lines[i] = """{{- with .Values.hubconfig.tolerations }}
      tolerations:
      {{- range . }}
      - {{ if .Key }} key: {{ .Key }} {{- end }}
        {{ if .Operator }} operator: {{ .Operator }} {{- end }}
        {{ if .Value }} value: {{ .Value }} {{- end }}
        {{ if .Effect }} effect: {{ .Effect }} {{- end }}
        {{ if .TolerationSeconds }} tolerationSeconds: {{ .TolerationSeconds }} {{- end }}
        {{- end }}
{{- end }}
"""

        if line.strip() == "env:" or line.strip() == "env: {}":
            lines[i] = """        env:
{{- if .Values.hubconfig.proxyConfigs }}
        - name: HTTP_PROXY
          value: {{ .Values.hubconfig.proxyConfigs.HTTP_PROXY }}
        - name: HTTPS_PROXY
          value: {{ .Values.hubconfig.proxyConfigs.HTTPS_PROXY }}
        - name: NO_PROXY
          value: {{ .Values.hubconfig.proxyConfigs.NO_PROXY }}
{{- end }}
"""

        if is_version_compatible(branch, '9.9', '9.9', '9.9'):
            if 'replicas:' in line.strip():
                lines[i] = """  replicas: {{ .Values.hubconfig.replicaCount }}
"""

        if sizes:
            for sizeDeployment in sizes["deployments"]:
                if sizeDeployment["name"] == deploy["metadata"]["name"]:
                    for container in sizeDeployment["containers"]:
                        if line.strip() == "resources: REPLACE-" + container["name"]:
                            lines[i] = """        resources:
{{-  if eq .values.hubconfig.hubSize "Small" }}
          limits:
            cpu: """ + container["Small"]["limits"]["cpu"] + """
            memory: """ + container["Small"]["limits"]["memory"] + """
          requests:
            cpu: """ + container["Small"]["requests"]["cpu"] + """
            memory: """ + container["Small"]["requests"]["memory"] + """
{{- end }}
{{ if eq .values.hubconfig.hubSize "Medium" }}
          limits:
            cpu: """ + container["Medium"]["limits"]["cpu"] + """
            memory: """ + container["Medium"]["limits"]["memory"] + """
          requests:
            cpu: """ + container["Medium"]["requests"]["cpu"] + """
            memory: """ + container["Medium"]["requests"]["memory"] + """
{{- end }}
{{-  if eq .values.hubconfig.hubSize "Large" }}
          limits:
            cpu: """ + container["Large"]["limits"]["cpu"] + """
            memory: """ + container["Large"]["limits"]["memory"] + """
          requests:
            cpu: """ + container["Large"]["requests"]["cpu"] + """
            memory: """ + container["Large"]["requests"]["memory"] + """
{{- end }}
{{ if eq .values.hubconfig.hubSize "ExtraLarge" }}
          limits:
            cpu: """ + container["ExtraLarge"]["limits"]["cpu"] + """
            memory: """ + container["ExtraLarge"]["limits"]["memory"] + """
          requests:
            cpu: """ + container["ExtraLarge"]["requests"]["cpu"] + """
            memory: """ + container["ExtraLarge"]["requests"]["memory"] + """
{{- end }}
"""

        if line.strip() == "seccompProfile:":
            next_line = lines[i+1]  # Ignore possible reach beyond end-of-list, not really possible
            prev_line = lines[i-1]
            if next_line.strip() == "type: RuntimeDefault" and "semverCompare" not in prev_line:
                insert_flow_control_if_around(lines, i, i+1, "semverCompare \">=4.11.0\" .Values.hubconfig.ocpVersion")
                if is_version_compatible(branch, '9.9', '2.7', '2.12'):
                    insert_flow_control_if_around(lines, i, i+1, ".Values.global.deployOnOCP")

        a_file = open(deployment, "w")
        a_file.writelines(lines)
        a_file.close()
    logging.info("Added Helm flow control for NodeSelector, Proxy, and SeccompProfile Overrides.\n")

def inject_requirements(helm_chart, chart_name, config, image_key_mapping, skip_rbac_overrides, exclusions, inclusions, branch, sizes={}):
    """
    Injects onboarding requirements into a Helm chart by performing necessary updates and fixes.

    This function modifies the Helm chart by fixing image references, injecting annotations, 
    updating RBAC configurations (unless skipped), and updating deployments. It supports
    handling exclusions and inclusions, as well as adjusting deployments based on the provided sizes.

    Args:
        helm_chart (str): The path to the Helm chart directory.
        chart_name (str): The name of the chart to update.
        config (dict): A dictionary containing configuration options for the chart.
        image_key_mapping (dict): A dictionary mapping image keys to their respective image references.
        skip_rbac_overrides (bool): Flag indicating whether to skip RBAC overrides.
        exclusions (list): A list of resources to exclude from updates.
        inclusions (list): A list of resources to include in updates.
        branch (str): The branch name, used to adjust behavior for version compatibility.
        sizes (dict, optional): A dictionary specifying deployment sizes (default is an empty dictionary).
    """
    logging.info("Updating Helm chart '%s' with onboarding requirements ...", helm_chart)

    fix_image_references(helm_chart, image_key_mapping)
    fix_env_var_image_references(helm_chart, image_key_mapping)
    fix_image_references_for_addon_template(helm_chart, image_key_mapping)
    inject_annotations_for_addon_template(helm_chart)

    if not skip_rbac_overrides:
        update_rbac(helm_chart, chart_name)

    update_deployments(helm_chart, config, exclusions, inclusions, branch, sizes)
    logging.info("Updated Chart '%s' successfully", helm_chart)

def insert_flow_control_if_around(lines_list, first_line_index, last_line_index, if_condition):
    """
    Inserts a Helm flow control `if` block around the first and last lines in a list of lines.

    This function modifies the given lines list by adding a Helm `if` condition block 
    around the lines at the specified indices. It inserts the `if` condition at the start 
    and the `end` block at the end, without changing the indices of the other lines in the list, 
    preserving iteration consistency.

    Args:
        lines_list (list of str): The list of lines representing the template, where each line is a string.
        first_line_index (int): The index of the first line to wrap with the Helm `if` block.
        last_line_index (int): The index of the last line to wrap with the Helm `end` block.
        if_condition (str): The condition for the Helm `if` block (e.g., a variable or expression).
    """
    lines_list[first_line_index] = "{{- if %s }}\n%s" % (if_condition, lines_list[first_line_index])
    lines_list[last_line_index] = "%s{{- end }}\n" % lines_list[last_line_index]

def is_version_compatible(branch, min_release_version, min_backplane_version, min_ocm_version):
    """
    Checks whether the version of a given branch is compatible with the specified minimum version requirements.

    The function extracts the version part from the branch name (e.g., '2.12-integration' -> '2.12'), 
    and compares it against the specified minimum version for different branch types:
    - 'release' branches are compared against the minimum release version.
    - 'release-ocm' branches are compared against the minimum OCM version.
    - 'backplane' or 'mce' branches are compared against the minimum backplane version.
    - The 'main' or 'master' branch is always considered compatible.

    Args:
        branch (str): The branch name (e.g., '2.12-integration').
        min_release_version (str): The minimum version for release branches (e.g., '2.12').
        min_backplane_version (str): The minimum version for backplane or mce branches (e.g., '1.0').
        min_ocm_version (str): The minimum version for release-ocm branches (e.g., '2.10').

    Returns:
        bool: True if the branch version is compatible with the specified minimum version, False otherwise.
    """
    # Extract the version part from the branch name (e.g., '2.12-integration' -> '2.12')
    pattern = r'(\d+\.\d+)'  # Matches versions like '2.12'
    
    if branch == "main" or branch == "master":
        return True
    
    match = re.search(pattern, branch)
    if match:
        v = match.group(1)  # Extract the version
        branch_version = version.Version(v)  # Create a Version object
        
        if "release-ocm" in branch:
            min_branch_version = version.Version(min_ocm_version)  # Use the minimum release version
        
        elif "release" in branch:
            min_branch_version = version.Version(min_release_version)  # Use the minimum release version

        elif "backplane" in branch or "mce" in branch:
            min_branch_version = version.Version(min_backplane_version)  # Use the minimum backplane version

        else:
            logging.error(f"Unrecognized branch type for branch: {branch}")
            return False

        # Check if the branch version is compatible with the specified minimum branch
        return branch_version >= min_branch_version

    else:
        return False
    
# updateDeployments adds standard configuration to the deployments (antiaffinity, security policies, and tolerations)
def update_deployments(helm_chart, config, exclusions, inclusions, branch, sizes={}):
    logging.info("Updating deployments with antiaffinity, security policies, and tolerations ...")

    deploySpecYaml = os.path.join(os.path.dirname(os.path.realpath(__file__)), "chart-templates/templates/deploymentspec.yaml")
    with open(deploySpecYaml, 'r') as f:
        deploySpec = yaml.safe_load(f)
    
    deployments = find_templates_of_type(helm_chart, 'Deployment')
    for deployment in deployments:
        with open(deployment, 'r') as f:
            deploy = yaml.safe_load(f)

        deploy['metadata'].pop('namespace')
        affinityList = deploySpec['affinity']['podAntiAffinity']['preferredDuringSchedulingIgnoredDuringExecution']
        for antiaffinity in affinityList:
            antiaffinity['podAffinityTerm']['labelSelector']['matchExpressions'][0]['values'][0] = deploy['metadata']['name']

        pod_template = deploy['spec']['template']

        if sizes:
            for sizeDeployment in sizes["deployments"]:
                if sizeDeployment["name"] == deploy["metadata"]["name"]:
                    for i in deploy['spec']['template']['spec']['containers']:            
                        if not any(d['name'] == i['name'] for d in sizeDeployment["containers"]):
                            logging.error("Missing container in sizes.yaml")
                            exit(1)
                        for sizContainer in sizeDeployment["containers"]:
                            if sizContainer["name"] == i["name"]:
                                i['resources'] = 'REPLACE-' + i['name']

        pod_template_spec = pod_template['spec']
        pod_template_spec['affinity'] = deploySpec['affinity']
        pod_template_spec['tolerations'] = ''
        pod_template_spec['hostNetwork'] = False
        pod_template_spec['hostPID'] = False
        pod_template_spec['hostIPC'] = False

        if 'automountServiceAccountToken' in config:
            automountSAToken = config.get('automountServiceAccountToken')
            if isinstance(automountSAToken, bool):
                pod_template_spec['automountServiceAccountToken'] = config.get('automountServiceAccountToken')
            else:
                logging.warning("automountServiceAccountToken should be a boolean. Ignoring invalid value.")

        if 'securityContext' not in pod_template_spec:
            pod_template_spec['securityContext'] = {}
        pod_security_context = pod_template_spec['securityContext']
        pod_security_context['runAsNonRoot'] = True

        pod_template['metadata']['labels']['ocm-antiaffinity-selector'] = deploy['metadata']['name']
        pod_template_spec['nodeSelector'] = ''
        pod_template_spec['imagePullSecrets'] = ''
        
        if 'seccompProfile' not in pod_security_context:
            pod_security_context['seccompProfile'] = {'type': 'RuntimeDefault'}
            # This will be made conditional on OCP version >= 4.11 by injectHelmFlowControl()
        else:
            if pod_security_context['seccompProfile']['type'] != 'RuntimeDefault':
                logging.warning("Leaving non-standard pod-level seccompprofile setting.")

        containers = pod_template_spec['containers']
        for container in containers:
            if 'env' not in container: 
                container['env'] = {}

            if 'securityContext' not in container: 
                container['securityContext'] = {}

            container_security_context = container['securityContext']
            container_security_context['allowPrivilegeEscalation'] = False
            container_security_context['capabilities'] = {}
            container_security_context['capabilities']['drop'] = ['ALL']
            container_security_context['privileged'] = False
            container_security_context['runAsNonRoot'] = True

            if 'readOnlyRootFilesystem' not in exclusions:
                container_security_context['readOnlyRootFilesystem'] = True

            if 'seccompProfile' in container_security_context:
                if container_security_context['seccompProfile']['type'] == 'RuntimeDefault':
                    # Remove, to allow pod-level setting to have effect.
                    del container['securityContext']['seccompProfile']
                else:
                    container_name = container['name']
                    logging.warning("Leaving non-standard seccompprofile setting for container %s" % container_name)
        
        with open(deployment, 'w') as f:
            yaml.dump(deploy, f, width=float("inf"))
        logging.info("Deployments updated with antiaffinity, security policies, and tolerations successfully. \n")

        inject_helm_flow_control(deployment, branch, sizes)
        if 'pullSecretOverride' in inclusions:
            add_pull_secret_override(deployment)

def update_rbac(helm_chart, chart_name):
    """
    Add standard configuration to the RBAC resources in a Helm chart.

    This function updates Role-Based Access Control (RBAC) resources, including
    ClusterRoles, Roles, ClusterRoleBindings, and RoleBindings, within the specified
    Helm chart. It applies standard configurations to ensure consistent RBAC settings
    across charts.

    Args:
        helm_chart (dict): The Helm chart structure represented as a dictionary,
                          typically loaded from a chart template or configuration.
        chart_name (str): The name of the Helm chart being processed, used for identifying
                         and updating RBAC resources.

    Returns:
        dict: The updated Helm chart dictionary with modified RBAC configurations.
    """
    logging.info("Updating RBAC resources (ClusterRoles, Roles, ClusterRoleBindings, RoleBindings) for chart: %s",
                 chart_name)
    
    rbac_kinds = ["ClusterRole", "Role", "ClusterRoleBinding", "RoleBinding"]
    templates_to_update = []
    
    for kind in rbac_kinds:
        templates = find_templates_of_type(helm_chart, kind)

        if templates:
            templates_to_update.extend(find_templates_of_type(helm_chart, kind))
            logging.info(f"Found {len(templates)} templates of kind '{kind}'")
        else:
            logging.warning("No templates found for kind '%s'", kind)

    if not templates_to_update:
        logging.info("No RBAC templates to update for chart: %s", chart_name)
        return

    for rbac_file in templates_to_update:
        try:
            logging.info("Processing RBAC template file: %s", rbac_file)

            with open(rbac_file, 'r') as f:
                rbac = yaml.safe_load(f)

            rbac['metadata']['name'] = "{{ .Values.org }}:{{ .Chart.Name }}:" + chart_name
            if rbac.get('kind') in ['RoleBinding', 'ClusterRoleBinding']:
                rbac['roleRef']['name'] = "{{ .Values.org }}:{{ .Chart.Name }}:" + chart_name

            with open(rbac_file, 'w') as f:
                yaml.dump(rbac, f, width=float("inf"))
    
            logging.info("Successfully updated RBAC template: %s", rbac_file)

        except (yaml.YAMLError, KeyError, TypeError) as e:
            logging.error(f"Failed to update RBAC template: {rbac_file}: {e}")

    logging.info("Completed RBAC resources update for chart: %s.", chart_name)
