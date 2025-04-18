#!/usr/bin/env python3
# Copyright (c) 2021 Red Hat, Inc.
# Copyright Contributors to the Open Cluster Management project
# Assumes: Python 3.6+

import argparse
import os
import shutil
import yaml
import logging
import coloredlogs
import subprocess
import re
from git import Repo, exc
from packaging import version

from validate_csv import *

# Configure logging with coloredlogs
coloredlogs.install(level='DEBUG')  # Set the logging level as needed

# Config Constants
SCRIPT_DIR = os.path.join(os.path.dirname(os.path.realpath(__file__)))
ROOT_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))

def log_header(message, *args):
    """
    Logs a header message with visual separators and formats the message using multiple arguments.
    Args:
        message (str): The message to be displayed as the header.
        *args: Additional arguments to be passed into the message string.
    """
    # Format the message with the provided arguments
    formatted_message = message.format(*args)

    # Create a separator line that matches the length of the formatted message
    separator = "=" * len(formatted_message)

    # Log an empty line before the separator and the header
    logging.info("")

    # Log the separator, the formatted message, and the separator again
    logging.info(separator)
    logging.info(formatted_message)
    logging.info(separator)

# Parse an image reference, return dict containing image reference information
def parse_image_ref(image_ref):
   # Image ref:  [registry-and-ns/]repository-name[:tag][@digest]
   parsed_ref = dict()

   remaining_ref = image_ref
   at_pos = remaining_ref.rfind("@")
   if at_pos > 0:
      parsed_ref["digest"] = remaining_ref[at_pos+1:]
      remaining_ref = remaining_ref[0:at_pos]
   else:
      parsed_ref["digest"] = None
   colon_pos = remaining_ref.rfind(":")
   if colon_pos > 0:
      parsed_ref["tag"] = remaining_ref[colon_pos+1:]
      remaining_ref = remaining_ref[0:colon_pos]
   else:
      parsed_ref["tag"] = None
   slash_pos = remaining_ref.rfind("/")
   if slash_pos > 0:
      parsed_ref["repository"] = remaining_ref[slash_pos+1:]
      rgy_and_ns = remaining_ref[0:slash_pos]
   else:
      parsed_ref["repository"] = remaining_ref
      rgy_and_ns = "localhost"
   parsed_ref["registry_and_namespace"] = rgy_and_ns

   rgy, ns = split_at(rgy_and_ns, "/", favor_right=False)
   if not ns:
      ns = ""

   parsed_ref["registry"] = rgy
   parsed_ref["namespace"] = ns

   slash_pos = image_ref.rfind("/")
   if slash_pos > 0:
      repo_and_suffix = image_ref[slash_pos+1:]
   else:
      repo_and_suffix = image_ref
   parsed_ref["repository_and_suffix"]  = repo_and_suffix

   return parsed_ref


def updateAddOnDeploymentConfig(yamlContent):
    yamlContent['metadata']['namespace'] = '{{ .Values.global.namespace }}'

def updateClusterManagementAddOn(yamlContent):
    if 'spec' not in yamlContent:
        return
    if 'supportedConfigs' not in yamlContent['spec']:
        return
    supportedConfigs = yamlContent['spec']['supportedConfigs']
    for config in supportedConfigs:
        if 'defaultConfig' not in config:
            continue
        defaultConfig = config['defaultConfig']
        if 'namespace' not in defaultConfig:
            continue
        defaultConfig['namespace'] = '{{ .Values.global.namespace }}'

# installAddonForAllClusters updates the clusterManagementAddOn to add a installStrategy
# to install the addon for all clusters
def installAddonForAllClusters(yamlContent):
    if 'spec' not in yamlContent:
        return
    if 'installStrategy' in yamlContent['spec']:
        # If installStrategy already exists, do nothing
        return

    # Create the installStrategy substructure
    install_strategy = {
        'placements': [{
            'name': 'global', # Use the global placement to select all clusters
            'namespace': 'open-cluster-management-global-set',
            'rolloutStrategy': {
                'type': 'All'
            }
        }],
        'type': 'Placements'
    }

    # Assign the installStrategy to the yamlContent
    yamlContent['spec']['installStrategy'] = install_strategy


def updateServiceAccount(yamlContent):
    yamlContent['metadata'].pop('namespace')

def updateClusterRoleBinding(yamlContent):
    subjectsList = yamlContent['subjects']
    for sub in subjectsList:
        sub['namespace'] = '{{ .Values.global.namespace }}'

def escapeTemplateVariables(helmChart, variables):
    addonTemplates = find_templates_of_type(helmChart, 'AddOnTemplate')
    for addonTemplate in addonTemplates:
        for variable in variables:
            logging.info("Start to escape vriable %s", variable)
            at = open(addonTemplate, "r")
            lines = at.readlines()
            v = "{{"+variable+"}}"
            for i, line in enumerate(lines):
                if v in line.strip():
                    logging.info("Found variable %s in line: %s", v, line.strip())
                    lines[i] = line.replace(v, "{{ `"+ v + "` }}")

            a_file = open(addonTemplate, "w")
            a_file.writelines(lines)
            a_file.close()
    logging.info("Escaped template variables.\n")

# Copy chart-templates to a new helmchart directory
def updateResources(outputDir, repo, chart):
    logging.info("Starting resource update process ...")

    # Create main folder
    always_or_toggle = chart['always-or-toggle']
    chartDir = os.path.join(outputDir, "charts", always_or_toggle, chart['name'])
    templateDir = os.path.join(chartDir, "templates")

    # Check if template directory exists
    if not os.path.exists(templateDir):
        logging.error(f"Template directory {templateDir} does not exist. Exiting update process.")
        return # Exit early if the template directory doesn't exist

    for tempFile in os.listdir(templateDir):
        filePath = os.path.join(templateDir, tempFile)

        try:
            with open(filePath, 'r') as f:
                yamlContent = yaml.safe_load(f)
        except Exception as e:
            logging.error(f"Error reading YAML content from {filePath}: {e}")
            return

        # Log the kind of resource being processed   
        kind = yamlContent.get("kind")
        logging.info(f"Found resource of kind: {kind} in {filePath}")

        # Perform the appropriate update action based on the kind
        if kind == "AddOnDeploymentConfig":
            logging.info(f"Updating AddOnDeploymentConfig in {filePath}")
            updateAddOnDeploymentConfig(yamlContent)

        elif kind == "ClusterManagementAddOn":
            logging.info(f"Updating ClusterManagementAddOn in {filePath}")
            updateClusterManagementAddOn(yamlContent)
            if chart.get('auto-install-for-all-clusters', False):
                installAddonForAllClusters(yamlContent)

        elif kind == "ServiceAccount":
            logging.info(f"Updating ServiceAccount in {filePath}")
            updateServiceAccount(yamlContent)

        elif kind == "ClusterRoleBinding":
            skip_rbac_override = chart.get('skipRBACOverrides', False)
            if not skip_rbac_override:
                logging.info(f"Updating ClusterRoleBinding in {filePath}")
                updateClusterRoleBinding(yamlContent)
            else:
                logging.warning(f"Skipping ClusterRoleBinding update (RBAC override is disabled) in {filePath}")

        else:
            continue

        try:
            with open(filePath, 'w') as f:
                yaml.dump(yamlContent, f, width=float("inf"))
            logging.info(f"Successfully updated {filePath}")
        except Exception as e:
            logging.error(f"Error writing YAML content to {filePath}: {e}")
            return

    try:
        # Escape template variables
        escapeTemplateVariables(chartDir, chart["escape-template-variables"])
        logging.info(f"Template variables escaped successfully for {chartDir}.")
    except Exception as e:
        logging.error(f"Error escaping template variables in {chartDir}: {e}")
        return

    logging.info("All resources updated successfully.")

def deep_update(overwrite, original):
    """
    Recursively updates the original dictionary with values from the overwrite dictionary.
    If the value is a dictionary, it will recurse into the nested dictionaries.
    """
    for key, value in overwrite.items():
        if isinstance(value, dict) and key in original and isinstance(original[key], dict):
            # If both the original and overwrite values are dictionaries, recurse into the dictionary
            deep_update(value, original[key])
        elif key in original:
            # Otherwise, directly replace the value
            original[key] = value


def updateValues(overwrite, original):
    # Load overwrite_values.yaml into a dictionary called overwriteValues
    with open(overwrite, 'r') as overwrite_file:
        overwriteValues = yaml.safe_load(overwrite_file)

    # Load values.yaml into a dictionary called originalValues
    with open(original, 'r') as values_file:
        originalValues = yaml.safe_load(values_file)

    deep_update(overwriteValues, originalValues)

    # Write the updated dictionary back to values.yaml
    with open(original, 'w') as values_file:
        yaml.dump(originalValues, values_file, default_flow_style=False)


# Copy chart-templates to a new helmchart directory
def copyHelmChart(destinationChartPath, repo, chart, chartVersion, branch):
    chartName = chart.get('name', '')
    logging.info(f"Starting to process chart '{chartName}' chart directory")

    # Create main folder
    chartPath = os.path.join(os.path.dirname(os.path.realpath(__file__)), "tmp", repo, chart["chart-path"])
    logging.debug(f"Chart path resolved to: '{chartPath}'")
    logging.debug(f"Destination chart path: '{destinationChartPath}'")

    if os.path.exists(destinationChartPath):
        logging.warning(f"Destination chart path already exists. Removing: {destinationChartPath}")
        shutil.rmtree(destinationChartPath)
    
    # Copy Chart.yaml, values.yaml, and templates dir
    destinationTemplateDir = os.path.join(destinationChartPath, "templates")
    logging.info(f"Creating destination template directory: {destinationTemplateDir}")
    os.makedirs(destinationTemplateDir)

    chartYamlPath = os.path.join(chartPath, "Chart.yaml")
    if not os.path.exists(chartYamlPath):
        logging.error(f"Missing Chart.yaml in chart: '{chartName}' at path: {chartYamlPath}")
        return

    # Update chart version if specified before rendering templates
    if chartVersion != "":
        with open(chartYamlPath, 'r') as f:
            chartYaml = yaml.safe_load(f)
        chartYaml['version'] = chartVersion
        with open(chartYamlPath, 'w') as f:
            yaml.dump(chartYaml, f, width=float("inf"))

    overwriteValues = os.path.join(os.path.dirname(os.path.realpath(__file__)), "chart-values", chart['name'], "overwriteValues.yaml")
    specificValues = os.path.join(os.path.dirname(os.path.realpath(__file__)), "chart-values", chart['name'], "values.yaml")
    if os.path.exists(overwriteValues) or os.path.exists(specificValues):
        logging.info(f"Using specific values.yaml for chart '{chartName}' from: {specificValues}")
        if is_version_compatible(branch, '2.14', '2.9', '2.13'):
            updateValues(overwriteValues, os.path.join(chartPath, "values.yaml"))
        else:
            shutil.copyfile(specificValues, os.path.join(chartPath, "values.yaml"))


    else:
        logging.warning(f"No specific values.yaml found for chart '{chartName}'")

    logging.info(f"Running 'helm template' for chart: '{chartName}'")
    helmTemplateOutput = subprocess.getoutput(['helm template '+ chartPath + ' --namespace=PLACEHOLDER_NAMESPACE'])

    yamlList = helmTemplateOutput.split('---')
    for outputContent in yamlList:
        yamlContent = yaml.safe_load(outputContent)
        if yamlContent is None:
            logging.warning("Skipped empty or invalid YAML content during template processing")
            continue

        name = yamlContent.get('metadata', {}).get('name', '').lower()
        kind = yamlContent.get('kind', '').lower()
        if not name or not kind:
            logging.warning("YAML content is missing required metadata or kind fields")
            continue

        yamlFileName = f"{name}-{kind}" if name else kind
        newFileName = yamlFileName + '.yaml'
        newFilePath= os.path.join(destinationTemplateDir, newFileName)
        logging.info(f"Generated file: '{newFileName}'")

        try:
            with open(newFilePath, "w") as f:
                f.writelines(outputContent)

        except Exception as e:
            logging.error(f"Failed to write file '{newFilePath}': {e}")

    shutil.copyfile(chartYamlPath, os.path.join(destinationChartPath, "Chart.yaml"))
    shutil.copyfile(os.path.join(chartPath, "values.yaml"), os.path.join(destinationChartPath, "values.yaml"))

    # Copying template values.yaml instead of values.yaml from chart
    shutil.copyfile(os.path.join(os.path.dirname(os.path.realpath(__file__)), "chart-templates", "values.yaml"), os.path.join(destinationChartPath, "values.yaml"))

    logging.info(f"Finished processing chart: '{chartName}'\n")

# Given a resource Kind, return all filepaths of that resource type in a chart directory
def find_templates_of_type(helmChart, kind):
    resources = []
    for filename in os.listdir(os.path.join(helmChart, "templates")):
        if filename.endswith(".yaml") or filename.endswith(".yml"):
            filePath = os.path.join(helmChart, "templates", filename)
            with open(filePath, 'r') as f:
                fileYml = yaml.safe_load(f)
            if fileYml['kind'] == kind:
                resources.append(filePath)
            continue
        else:
            continue
    return resources

# For each deployment, identify the image references if any exist in the environment variable fields, insert helm flow control code to reference it, and add image-key to the values.yaml file.
# If the image-key referenced in the deployment does not exist in `imageMappings` in the Config.yaml, this will fail. Images must be explicitly defined
def fixEnvVarImageReferences(helmChart, imageKeyMapping):
    logging.info("Fixing image references in container 'env' section in deployments and values.yaml ...")
    
    # Path to the values.yaml file
    valuesYaml = os.path.join(helmChart, "values.yaml")

    # Check if the values.yaml file exists
    if not os.path.exists(valuesYaml):
        logging.error(f"{valuesYaml} does not exist. Skipping environment variable image reference updates.")
        return

    with open(valuesYaml, 'r') as f:
        values = yaml.safe_load(f)
    deployments = find_templates_of_type(helmChart, 'Deployment')

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
                image_key = parse_image_ref(env['value'])['repository']
                try:
                    image_key = imageKeyMapping[image_key]
                except KeyError:
                    logging.critical("No image key mapping provided for imageKey: %s" % image_key)
                    exit(1)
                imageKeys.append(image_key)
                env['value'] = "{{ .Values.global.imageOverrides." + image_key + " }}"
        with open(deployment, 'w') as f:
            yaml.dump(deploy, f, width=float("inf"))

    for imageKey in imageKeys:
        values['global']['imageOverrides'][imageKey] = ""
    with open(valuesYaml, 'w') as f:
        yaml.dump(values, f, width=float("inf"))
    logging.info("Image container env references in deployments and values.yaml updated successfully.\n")

# For each deployment, identify the image references if any exist in the image field, insert helm flow control code to reference it, and add image-key to the values.yaml file.
# If the image-key referenced in the deployment does not exist in `imageMappings` in the Config.yaml, this will fail. Images must be explicitly defined
def fixImageReferences(helmChart, imageKeyMapping):
    logging.info("Fixing image and pull policy references in deployments and values.yaml ...")

    # Path to the values.yaml file
    valuesYaml = os.path.join(helmChart, "values.yaml")

    # Check if the values.yaml file exists
    if not os.path.exists(valuesYaml):
        logging.error(f"{valuesYaml} does not exist. Skipping image and pull policy updates.")
        return  # Exit the function if the file doesn't exist

    with open(valuesYaml, 'r') as f:
        values = yaml.safe_load(f)
    
    resource_kinds = ["Deployment", "Job", "StatefulSet"]
    imageKeys = []
    for kind in resource_kinds:
        resource_templates = find_templates_of_type(helmChart, kind)

        for template_path in resource_templates:
            with open(template_path, 'r') as f:
                resource_data = yaml.safe_load(f)
            
            containers = resource_data['spec']['template']['spec']['containers']
            for container in containers:
                image_key = parse_image_ref(container['image'])["repository"]
                try:
                    image_key = imageKeyMapping[image_key]
                except KeyError:
                    logging.critical("No image key mapping provided for imageKey: %s" % image_key)
                    exit(1)
                imageKeys.append(image_key)
                container['image'] = "{{ .Values.global.imageOverrides." + image_key + " }}"
                container['imagePullPolicy'] = "{{ .Values.global.pullPolicy }}"

                if kind == "Deployment":
                    args = container.get('args', [])
                    refreshed_args = []
                    for arg in args:
                        if "--agent-image-name" not in arg:
                            refreshed_args.append(arg)
                        else:
                            refreshed_args.append("--agent-image-name="+"{{ .Values.global.imageOverrides." + image_key + " }}")
                    container['args'] = refreshed_args

            with open(template_path, 'w') as f:
                yaml.dump(resource_data, f, width=float("inf"))

    if 'imageOverride' in values['global']['imageOverrides']:
        del values['global']['imageOverrides']['imageOverride']

    for imageKey in imageKeys:
        values['global']['imageOverrides'][imageKey] = "" # set to temp to debug

    with open(valuesYaml, 'w') as f:
        yaml.dump(values, f, width=float("inf"))
    logging.info("Image references and pull policy in deployments and values.yaml updated successfully.\n")

# insers Heml flow control if/end block around a first and last line without changing
# the indexes of the lines list (so as to not mess up iteration across the lines).
def insertFlowControlIfAround(lines_list, first_line_index, last_line_index, if_condition):
   lines_list[first_line_index] = "{{- if %s }}\n%s" % (if_condition, lines_list[first_line_index])
   lines_list[last_line_index] = "%s{{- end }}\n" % lines_list[last_line_index]

def is_version_compatible(branch, min_release_version, min_backplane_version, min_ocm_version, enforce_master_check=True):
    # Extract the version part from the branch name (e.g., '2.12-integration' -> '2.12')
    pattern = r'(\d+\.\d+)'  # Matches versions like '2.12'
    
    if branch == "main" or branch == "master":
        if enforce_master_check:
            return True
        else:
            return False
    
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

# injectHelmFlowControl injects advanced helm flow control which would typically make a .yaml file more difficult to parse. This should be called last.
def injectHelmFlowControl(deployment, branch):
    logging.info("Adding Helm flow control for NodeSelector, Proxy Overrides, and SeccompProfile ...")
    deploy = open(deployment, "r")
    lines = deploy.readlines()
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

        if is_version_compatible(branch, '9.9', '9.9', '9.9', False):
            if 'replicas:' in line.strip():
                lines[i] = """  replicas: {{ .Values.hubconfig.replicaCount }}
"""

        if line.strip() == "seccompProfile:":
            next_line = lines[i+1]  # Ignore possible reach beyond end-of-list, not really possible
            prev_line = lines[i-1]
            if next_line.strip() == "type: RuntimeDefault" and "semverCompare" not in prev_line:
                insertFlowControlIfAround(lines, i, i+1, "semverCompare \">=4.11.0\" .Values.hubconfig.ocpVersion")
                if is_version_compatible(branch, '9.9', '2.7', '2.12'):
                    insertFlowControlIfAround(lines, i, i+1, ".Values.global.deployOnOCP")

        a_file = open(deployment, "w")
        a_file.writelines(lines)
        a_file.close()
    logging.info("Added Helm flow control for NodeSelector, Proxy, and SeccompProfile Overrides.\n")

def addPullSecretOverride(deployment):
    deploy = open(deployment, "r")
    lines = deploy.readlines()
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

# updateDeployments adds standard configuration to the deployments (antiaffinity, security policies, and tolerations)
def updateDeployments(chartName, helmChart, exclusions, inclusions, branch):
    logging.info("Updating deployments with antiaffinity, security policies, and tolerations ...")
    deploySpecYaml = os.path.join(os.path.dirname(os.path.realpath(__file__)), "chart-templates/templates/deploymentspec.yaml")
    with open(deploySpecYaml, 'r') as f:
        deploySpec = yaml.safe_load(f)
    
    deployments = find_templates_of_type(helmChart, 'Deployment')
    for deployment in deployments:
        with open(deployment, 'r') as f:
            deploy = yaml.safe_load(f)
        deploy['metadata'].pop('namespace')
        affinityList = deploySpec['affinity']['podAntiAffinity']['preferredDuringSchedulingIgnoredDuringExecution']
        for antiaffinity in affinityList:
            antiaffinity['podAffinityTerm']['labelSelector']['matchExpressions'][0]['values'][0] = deploy['metadata']['name']
        deploy['spec']['template']['spec']['affinity'] = deploySpec['affinity']
        deploy['spec']['template']['spec']['tolerations'] = ''
        deploy['spec']['template']['spec']['hostNetwork'] = False
        deploy['spec']['template']['spec']['hostPID'] = False
        deploy['spec']['template']['spec']['hostIPC'] = False

        deploy['spec']['template']['metadata']['labels']['ocm-antiaffinity-selector'] = deploy['metadata']['name']
        deploy['spec']['template']['spec']['nodeSelector'] = ""
        deploy['spec']['template']['spec']['imagePullSecrets'] = ''
        
        with open(deployment, 'w') as f:
            yaml.dump(deploy, f, width=float("inf"))
        logging.info("Deployments updated with antiaffinity, security policies, and tolerations successfully. \n")

        injectHelmFlowControl(deployment, branch)
        if 'pullSecretOverride' in inclusions:
            addPullSecretOverride(deployment)

def ensure_addon_deployment_config_namespace(resource_data, resource_name, default_namespace):
    resource_namespace = resource_data.get('namespace')

    if resource_namespace is None:
        # Use the default Helm namespace if not specified
        resource_namespace = default_namespace

    else:
        # Update Helm templating to override existing namespace
        resource_namespace = f"{{{{ default \"{resource_namespace}\" .Values.global.namespace }}}}"

    resource_data['metadata']['namespace'] = resource_namespace
    logging.info(f"AddonDeploymentConfig namespace for '{resource_name}' set to: '{resource_namespace}'.\n")

def ensure_clusterrole_binding_subject_namespace(resource_data, resource_name, default_namespace):
    if 'subjects' not in resource_data:
        return
    
    for subject in resource_data.get('subjects', []):
        subject_namespace = subject.get('namespace')
        
        if subject_namespace is None:
            # Use the default Helm namespace if not specified
            subject_namespace = default_namespace            
        else:
            # Update Helm templating to override existing namespace
            subject_namespace = f"{{{{ default \"{subject_namespace}\" .Values.global.namespace }}}}"
    
        subject['namespace'] = subject_namespace
    logging.info(f"Subject namespace for '{resource_name}' set to: '{subject_namespace}'\n")

def ensure_stateful_set_storage_class(resource_data, resource_name):
    """
    Ensures that a StatefulSet has a storageClassName set.

    If the storageClassName is not specified in the StatefulSet spec, it assigns the default 
    Helm value (`{{ .Values.global.storageClassName }}`). If a storageClassName is 
    already set, it wraps it in a Helm `default` function to allow overriding.

    Args:
        resource_data (dict): The StatefulSet resource data dictionary.ß
        resource_name (str): The name of the StatefulSet resource.

    Returns:
        None: Modifies resource_data in place.
    """
    statefulset_vc_templates = resource_data['spec'].get('volumeClaimTemplates', [])
    
    for claim in statefulset_vc_templates:
        # Use the default Helm namespace if not specified
        claim_storage_class_name = claim.get('spec', {}).get('storageClassName')

        if claim_storage_class_name is None:
          claim_storage_class_name = """{{ .Values.global.storageClassName }}"""

        # Update Helm templating to override existing namespace
        else:
            claim_storage_class_name = f"{{{{ default \"{claim_storage_class_name}\" .Values.global.storageClassName }}}}"
        
        claim['spec']['storageClassName'] = claim_storage_class_name
        logging.info(f"StatefulSet volumeClaimTemplate storageClassName for '{resource_name}' set to: '{claim_storage_class_name}'\n")

    resource_data['spec']['volumeClaimTemplates'] = statefulset_vc_templates    

def ensure_pvc_storage_class(resource_data, resource_name):
    """
    Ensures that a PersistentVolumeClaim (PVC) has a storageClassName set.

    If the storageClassName is not specified in the PVC spec, it assigns the default 
    Helm value (`{{ .Values.global.storageClassName }}`). If a storageClassName is 
    already set, it wraps it in a Helm `default` function to allow overriding.

    Args:
        resource_data (dict): The PVC resource data dictionary.
        resource_name (str): The name of the PVC resource.

    Returns:
        None: Modifies resource_data in place.
    """
    storage_class_name = resource_data['spec'].get('storageClassName', None)
    
    # Use the default Helm namespace if not specified
    if storage_class_name is None:
        storage_class_name = """{{ .Values.global.storageClassName }}"""

    # Update Helm templating to override existing namespace
    else:
        storage_class_name = f"{{{{ default \"{storage_class_name}\" .Values.global.storageClassName }}}}"

    resource_data['spec']['storageClassName'] = storage_class_name
    logging.info(f"PersistentVolumeClaim storageClassName for '{resource_name}' set to: '{storage_class_name}'.\n")
    
def ensure_webhook_namespace(resource_data, resource_name, default_namespace):
    """
    Ensures that the namespace for webhooks in a MutatingWebhookConfiguration or 
    ValidatingWebhookConfiguration is set correctly. Uses Helm templating to 
    apply a default namespace if none is provided.

    Args:
        resource_data (dict): The webhook configuration resource data.
        resource_name (str): The name of the webhook resource.
        default_namespace (str): The default namespace to use if not set.

    Returns:
        None: Modifies resource_data in place.
    """
    if 'webhooks' not in resource_data:
        return
    
    for webhook in resource_data.get('webhooks', []):
        client_config = webhook.get('clientConfig', {})

        service = client_config.get('service')
        if not service:
            continue

        service_name = service.get('name')
        service_namespace = service.get('namespace')
        service_path = service.get('path')

        if service_namespace is None:
            # Use the default Helm namespace if not specified
            service_namespace = default_namespace

        else:
            # Update Helm templating to override existing namespace
            service_namespace = f"{{{{ default \"{service_namespace}\" .Values.global.namespace }}}}"

        service['namespace'] = service_namespace
        
        # Log details for each distinct service
        logging.info(f"Webhook service for '{resource_name}' set to:")
        logging.info(f"  Name: {service_name}")
        logging.info(f"  Namespace: {service_namespace}")
        logging.info(f"  Path: {service_path}\n")

def replace_default(data, old, new):
    if isinstance(data, dict):
        for key, value in data.items():
            data[key] = replace_default(value, old, new)
    elif isinstance(data, list):
        for i in range(len(data)):
            data[i] = replace_default(data[i], old, new)
    elif isinstance(data, str):
        return data.replace(old, new)
    return data

# updateHelmResources adds standard configuration to the generic kubernetes resources
def update_helm_resources(chartName, helmChart, skip_rbac_overrides, exclusions, inclusions, branch):
    logging.info(f"Updating resources chart: {chartName}")

    resource_kinds = [
        "ClusterRole", "ClusterRoleBinding", "ConfigMap", "Deployment", "MutatingWebhookConfiguration",
        "NetworkPolicy", "PersistentVolumeClaim", "RoleBinding", "Role", "Route", "Secret", "Service", "StatefulSet",
        "ValidatingWebhookConfiguration", "Job", "ConsolePlugin"
    ]

    namespace_scoped_kinds = [
        "ConfigMap", "Deployment", "NetworkPolicy", "PersistentVolumeClaim", "RoleBinding", "Role", "Route",
        "Secret", "Service", "StatefulSet", "Job"
    ]

    for kind in resource_kinds:
        resource_templates = find_templates_of_type(helmChart, kind)
        if not resource_templates:
            logging.info("------------------------------------------")
            logging.warning(f"No {kind} templates found in the Helm chart [Skipping]")
            logging.info("------------------------------------------\n")
        else:
            logging.info("------------------------------------------")
            logging.info(f"Found {len(resource_templates)} {kind} templates")
            logging.info("------------------------------------------")

        # Set the default namespace for the chart.
        default_namespace = """{{ .Values.global.namespace }}"""

        for template_path in resource_templates:
            try:
                with open(template_path, 'r') as f:
                    resource_data = yaml.safe_load(f)
                    resource_name = resource_data['metadata'].get('name')
                    logging.info(f"Processing resource: {resource_name} from template: {template_path}")

                if chartName == 'flight-control':
                    if kind == 'ConsolePlugin':
                        resource_data = replace_default(resource_data, 'PLACEHOLDER_NAMESPACE', '{{ .Values.global.namespace }}')

                # Ensure namespace is set for namespace-scoped resources
                if kind in namespace_scoped_kinds:
                    resource_namespace = resource_data['metadata'].get('namespace')

                    if resource_namespace is None or resource_namespace == "PLACEHOLDER_NAMESPACE":
                        # Use the default Helm namespace if not specified
                        resource_namespace = default_namespace
                    else:
                        # Allow Helm templating to override existing namespace
                        resource_namespace = f"{{{{ default \"{resource_namespace}\" .Values.global.namespace }}}}"

                    resource_data['metadata']['namespace'] = resource_namespace
                    logging.info(f"Namespace for '{resource_name}' set to: {resource_namespace}")

                # Ensure Mutating/Validating WebhookConfigurations has a service namespace set,
                # defaulting to Helm values if not specified.
                if kind == "MutatingWebhookConfiguration" or kind == "ValidatingWebhookConfiguration":
                    ensure_webhook_namespace(resource_data, resource_name, default_namespace)

                # Ensure the StatefulSet has a storageClassName set,
                # defaulting to Helm values if not specified.
                if kind == 'StatefulSet':
                    ensure_stateful_set_storage_class(resource_data, resource_name)

                # Ensure the PersistentVolumeClaim has a storageClassName set,
                # defaulting to Helm values if not specified.
                if kind == 'PersistentVolumeClaim':
                    ensure_pvc_storage_class(resource_data, resource_name)

                if chartName == 'flight-control':
                    if kind == 'Route':
                        if resource_name == 'flightctl-api-route':
                            resource_data['spec']['host'] = """api.{{ .Values.global.baseDomain  }}"""
                        if resource_name == 'flightctl-api-route-agent':
                            resource_data['spec']['host'] = """agent-api.{{ .Values.global.baseDomain  }}"""

                    if kind == 'ConfigMap':
                        resource_data['metadata']['namespace'] = '{{ .Values.global.namespace  }}'
                        config_data = resource_data.get('data')
                        for key, value in config_data.items():
                            if key.endswith(".yaml") or key.endswith(".yml"):
                                key_data = yaml.safe_load(value)
                                logging.warning(f"key_data={key_data.get('database').get('hostname')}")
                                hostname = key_data.get('database').get('hostname')
                                key_data = replace_default(key_data, 'PLACEHOLDER_NAMESPACE', '{{ .Values.global.namespace }}')
                                key_data = replace_default(key_data, 'placeholder_apiurl', '{{ .Values.global.apiUrl }}')
                                key_data = replace_default(key_data, 'placeholder_basedomain', '{{ .Values.global.baseDomain }}')
                                updated_yaml = yaml.dump(key_data, default_flow_style=False, allow_unicode=True, width=float("inf"))
                                config_data[key] = updated_yaml
                                resource_data['data'] = config_data
                        resource_data['data'] = replace_default(resource_data['data'], 'PLACEHOLDER_NAMESPACE', '{{ .Values.global.namespace }}')
                
                    if kind == "ClusterRoleBinding":
                        resource_data['metadata']['name'] = 'flightctl-api-{{ .Values.global.namespace }}'
                        resource_data['roleRef']['name'] = 'flightctl-api-{{ .Values.global.namespace }}'
                    if kind == "ClusterRole":
                        resource_data['metadata']['name'] = 'flightctl-api-{{ .Values.global.namespace }}'

                    if kind == "NetworkPolicy":
                        resource_data['metadata']['namespace'] = '{{ .Values.global.namespace }}'
                        resource_data = replace_default(resource_data, 'PLACEHOLDER_NAMESPACE', '{{ .Values.global.namespace }}')
                    if kind == "Job":
                        resource_data = replace_default(resource_data, 'PLACEHOLDER_NAMESPACE', '{{ .Values.global.namespace }}')

                if chartName != "managed-serviceaccount":
                    if kind == "ClusterRoleBinding" or kind == "RoleBinding":
                        if 'subjects' in resource_data:
                            for subject in resource_data['subjects']:
                                subject_namespace = subject.get('namespace', None)
                                if subject_namespace is None:
                                    # If no namespace is found, use the default Helm namespace
                                    subject['namespace'] = target_namespace

                                else:
                                    # Update target_namespace to reflect the subject_namespace
                                    target_namespace = f"{{{{ default \"{subject_namespace}\" .Values.global.namespace }}}}"
                                    subject['namespace'] = target_namespace
                            logging.info(f"Subject namespace for {resource_name} set to: {target_namespace} (Helm default used).\n")

                with open(template_path, 'w') as f:
                    yaml.dump(resource_data, f, width=float("inf"), default_flow_style=False, allow_unicode=True)
                    logging.info(f"Succesfully updated resource: {resource_name}\n")

            except Exception as e:
                logging.error(f"Error processing template '{template_path}': {e}")

    logging.info("Resource updating process completed.")

# injectAnnotationsForAddonTemplate injects following annotations for deployments in the AddonTemplate:
# - target.workload.openshift.io/management: '{"effect": "PreferredDuringScheduling"}'
def injectAnnotationsForAddonTemplate(helmChart):
    logging.info("Injecting Annotations for deployments in the AddonTemplate ...")

    addonTemplates = find_templates_of_type(helmChart, 'AddOnTemplate')
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
                logging.info("Annotations injected successfully. \n")


# fixImageReferencesForAddonTemplate identify the image references for every deployment in addontemplates, if any exist
# in the image field, insert helm flow control code to reference it, and add image-key to the values.yaml file.
# If the image-key referenced in the addon template deployment does not exist in `imageMappings` in the Config.yaml,
# this will fail. Images must be explicitly defined
def fixImageReferencesForAddonTemplate(helmChart, imageKeyMapping):
    logging.info("Fixing image references in addon templates and values.yaml ...")

    addonTemplates = find_templates_of_type(helmChart, 'AddOnTemplate')
    imageKeys = []
    temp = "" ## temporarily read image ref
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
                        image_key = parse_image_ref(container['image'])["repository"]
                        try:
                            image_key = imageKeyMapping[image_key]
                        except KeyError:
                            logging.critical("No image key mapping provided for imageKey: %s" % image_key)
                            exit(1)
                        imageKeys.append(image_key)
                        container['image'] = "{{ .Values.global.imageOverrides." + image_key + " }}"
                        # container['imagePullPolicy'] = "{{ .Values.global.pullPolicy }}"
        with open(addonTemplate, 'w') as f:
            yaml.dump(templateContent, f, width=float("inf"))
            logging.info("AddOnTemplate updated with image override successfully. \n")

    if len(imageKeys) == 0:
        return
    valuesYaml = os.path.join(helmChart, "values.yaml")
    with open(valuesYaml, 'r') as f:
        values = yaml.safe_load(f)
    if 'imageOverride' in values['global']['imageOverrides']:
        del values['global']['imageOverrides']['imageOverride']
    for imageKey in imageKeys:
        values['global']['imageOverrides'][imageKey] = "" # set to temp to debug
    with open(valuesYaml, 'w') as f:
        yaml.dump(values, f, width=float("inf"))
    logging.info("Image references and pull policy in addon templates and values.yaml updated successfully.\n")


# updateRBAC adds standard configuration to the RBAC resources (clusterroles, roles, clusterrolebindings, and rolebindings)
def updateRBAC(helmChart, chartName):
    logging.info("Updating clusterroles, roles, clusterrolebindings, and rolebindings ...")
    clusterroles = find_templates_of_type(helmChart, 'ClusterRole')
    roles = find_templates_of_type(helmChart, 'Role')
    clusterrolebindings = find_templates_of_type(helmChart, 'ClusterRoleBinding')
    rolebindings = find_templates_of_type(helmChart, 'RoleBinding')

    for rbacFile in clusterroles + roles + clusterrolebindings + rolebindings:
        with open(rbacFile, 'r') as f:
            rbac = yaml.safe_load(f)
        rbac['metadata']['name'] = "{{ .Values.org }}:{{ .Chart.Name }}:" + chartName
        if rbac['kind'] in ['RoleBinding', 'ClusterRoleBinding']:
            rbac['roleRef']['name'] = "{{ .Values.org }}:{{ .Chart.Name }}:" + chartName
        with open(rbacFile, 'w') as f:
            yaml.dump(rbac, f, width=float("inf"))
    logging.info("Clusterroles, roles, clusterrolebindings, and rolebindings updated. \n")

def inject_security_context_constraints(resource, constraints_override):
    pod_template_spec = resource.setdefault("spec", {}).setdefault("template", {}).setdefault("spec", {})
    pod_security_context = pod_template_spec.setdefault("securityContext", {})

    # --- Pod-level security context ---
    pod_security_context['runAsNonRoot'] = constraints_override.get('runAsNonRoot', True)
    pod_security_context['runAsUser'] = constraints_override.get('runAsUser')
    pod_security_context['runAsGroup'] = constraints_override.get('runAsGroup')
    pod_security_context['fsGroup'] = constraints_override.get('fsGroup')
    pod_security_context['fsGroupChangePolicy'] = constraints_override.get('fsGroupChangePolicy')
    pod_security_context['SELinux'] = constraints_override.get('SELinux')
    pod_security_context['supplementalGroups'] = constraints_override.get('supplementalGroups')
    pod_security_context['supplementalGroupsPolicy'] = constraints_override.get('supplementalGroupsPolicy')

    pod_security_context.setdefault('seccompProfile', constraints_override.get('seccompProfile', {'type': 'RuntimeDefault'}))
    if pod_security_context.get('seccompProfile').get('type') != 'RuntimeDefault':
        logging.warning("Leaving non-standard pod-level seccompprofile setting.")

    # Remove keys with value None. We will only add those overrides, if there are custom values for us to pick up.
    for key in list(pod_security_context):
        if pod_security_context[key] is None:
            pod_security_context.pop(key)

    logging.info(f"Pod security context: {pod_security_context}")

    # --- Container-level security context ---
    container_constraints_override = constraints_override.get('containers', [])
    container_template_spec = pod_template_spec.get('containers', [])

    for container in container_template_spec:
        container_name = container.get('name')
        container_security_context = container.setdefault('securityContext', {})

        # Set container env to empty map, if it doesn't exist.
        container.setdefault('env', {})

        # Find matching constraint by container name
        matching_constraint = next((c for c in container_constraints_override if c.get('name') == container_name), {})

        container_security_context['allowPrivilegeEscalation'] = matching_constraint.get('allowPrivilegeEscalation', False)
        container_security_context['capabilities'] = matching_constraint.get('capabilities', {'drop': ['ALL']})
        container_security_context['privileged'] = matching_constraint.get('privileged', False)
        container_security_context['runAsNonRoot'] = matching_constraint.get('runAsNonRoot', True)
        container_security_context['readOnlyRootFilesystem'] = matching_constraint.get('readOnlyRootFilesystem', True)
        
        if 'seccompProfile'  in container_security_context:
            if container_security_context.get('seccompProfile').get('type') == 'RuntimeDefault':
                # Remove, to allow pod-level setting to have effect.
                del container_security_context['seccompProfile']
            else:
                logging.warning("Leaving non-standard pod-level seccompprofile setting.")

        logging.info(f"Container '{container_name}' security context: {container_security_context}\n")
        

def update_security_contexts(template_chart_path, constraints_override):
    """_summary_

    Args:
        template_chart_path (_type_): _description_
        constraints (list, optional): _description_. Defaults to [].
    """
    log_header("Injecting security context constraints...")

    for kind in ["Deployment", "Job", "StatefulSet"]:
        resource_templates = find_templates_of_type(template_chart_path, kind)
        if not resource_templates:
            continue
    
        for template in resource_templates:
            try:
                with open(template, 'r', encoding="utf-8") as f:
                    resource = yaml.safe_load(f)

                name = resource.get("metadata", {}).get("name")
                constraints = next(
                    (c for c in constraints_override if c.get("kind") == kind and c.get("name") == name), {}
                )

                if constraints:
                    logging.info("Injecting *custom* security context into '%s/%s'", kind, name)
                else:
                    logging.info("Injecting *default* security context into '%s/%s'", kind, name)

                inject_security_context_constraints(resource, constraints)
                with open(template, 'w', encoding="utf-8") as f:
                    yaml.dump(resource, f, width=float("inf"))

            except Exception as e:
                logging.error(f"Error injecting security context for {template}: {e}")

    logging.info("Updated security context for '%s'\n", template_chart_path)

def injectRequirements(helm_chart_path, chart, branch):
    logging.info("Updating Helm chart '%s' with onboarding requirements ...", helm_chart_path)

    chart_name = chart.get("name")
    image_mappings = chart.get("imageMappings", {})
    exclusions = chart.get("exclusions", [])
    inclusions = chart.get("inclusions", [])
    security_context_constraints = chart.get("security-context-constraints", [])
    skip_rbac_overrides = chart.get("skipRBACOverrides", False)

    fixImageReferences(helm_chart_path, image_mappings)
    fixEnvVarImageReferences(helm_chart_path, image_mappings)
    fixImageReferencesForAddonTemplate(helm_chart_path, image_mappings)
    injectAnnotationsForAddonTemplate(helm_chart_path)

    if not skip_rbac_overrides:
        updateRBAC(helm_chart_path, chart_name)

    if is_version_compatible(branch, '2.10', '2.5', '2.10'):
        update_security_contexts(helm_chart_path, security_context_constraints)
    
    if is_version_compatible(branch, '2.13', '2.8', '2.13'):
        update_helm_resources(chart_name, helm_chart_path, skip_rbac_overrides, exclusions, inclusions, branch)

    updateDeployments(chart_name, helm_chart_path, exclusions, inclusions, branch)

    logging.info("Updated Chart '%s' successfully", helm_chart_path)

def split_at(the_str, the_delim, favor_right=True):

   split_pos = the_str.find(the_delim)
   if split_pos > 0:
      left_part  = the_str[0:split_pos]
      right_part = the_str[split_pos+1:]
   else:
      if favor_right:
         left_part  = None
         right_part = the_str
      else:
         left_part  = the_str
         right_part = None

   return (left_part, right_part)

def addCRDs(repo, chart, outputDir):
    if not 'chart-path' in chart:
        logging.critical(f"Chart path missing in the provided chart configuration: {chart}")
        exit(1) 

    chartPath = os.path.join(os.path.dirname(os.path.realpath(__file__)), "tmp", repo, chart["chart-path"])
    logging.debug(f"Chart path resolved to: '{chartPath}'")

    if not os.path.exists(chartPath):
        logging.critical(f"Chart path not found at: {chartPath}")
        exit(1)
        
    crdPath = os.path.join(chartPath, "crds")
    if not os.path.exists(crdPath):
        logging.info(f"No CRDs for repo: {repo}")
        return
    
    destinationCRDPath = os.path.join(outputDir, "crds", chart['name'])
    logging.debug(f"Destination chart path: '{destinationCRDPath}'")

    if os.path.exists(destinationCRDPath): # If path exists, remove and re-clone
        logging.warning(f"Destination CRDs path already exists. Removing: {destinationCRDPath}")
        shutil.rmtree(destinationCRDPath)

    os.makedirs(destinationCRDPath)
    logging.info(f"Created destination path for CRDs: {destinationCRDPath}")

    for filename in os.listdir(crdPath):
        if not filename.endswith(".yaml"): 
            logging.debug(f"File '{filename}' is not a YAML file. Skipping processing.")
            continue

        filepath = os.path.join(crdPath, filename)
        with open(filepath, 'r') as f:
            resourceFile = yaml.safe_load(f)

        if resourceFile["kind"] == "CustomResourceDefinition":
            targetPath = os.path.join(destinationCRDPath, filename)
            shutil.copyfile(filepath, targetPath)
            logging.info(f"Generated CRD file '{filename}'")
        else:
            logging.debug(f"Skipping file '{filename}' as it does not contain a CRD.")

    logging.info(f"Finished processing CRDs for chart '{chart['name']}'\n")

def chartConfigAcceptable(chart):
    helmChart = chart["name"]
    if helmChart == "":
        logging.critical("Unable to generate helm chart without a name.")
        return False
    return True

def getChartVersion(updateChartVersion, repo):
    chartVersion = ""
    if not updateChartVersion:
        logging.warning("Update chart version flag is not set. Returning default chart version.")
        return chartVersion

    repo_name = repo.get("repo_name", "")
    logging.info(f"Calculating chart version for repository '{repo_name}'")

    if 'branch' not in repo:
        logging.warning(f"No branch specified for repository '{repo_name}', skipping chart version calculation")
        return chartVersion
    
    branch_name = repo['branch']
    logging.debug(f"Processing branch name: {branch_name}")

    version = branch_name.replace("release-", "").replace("backplane-", "")
    logging.debug(f"Extracted version after removing prefix: {version}")

    if not version.replace(".", "").isdecimal():
        logging.warning("Unable to use branch name '%s' as chart version for repo '%s', skip.", branch_name, repo_name)
        return chartVersion

    chartVersion = version
    logging.info(f"Detected chart version: {chartVersion}\n")

    return chartVersion

def renderChart(chart_path):
    # Define the path for the values.yaml file
    values_file_path = os.path.join(chart_path, 'values.yaml')
    
    # Load the values from the values.yaml file
    with open(values_file_path, 'r') as f:
        values = yaml.safe_load(f)

    try:
        # Use the Helm command to render the chart
        logging.info("Rendering chart '%s'...", chart_path)
        subprocess.run(
            ['helm', 'template', chart_path, '-f', values_file_path],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        logging.info("Chart rendered successfully.")
        return True

    except subprocess.CalledProcessError as e:
        logging.error("Error rendering chart: %s", e.stderr.decode())
        return False

def main():
    ## Initialize ArgParser
    parser = argparse.ArgumentParser()
    parser.add_argument("--component", dest="component", type=str, required=False, help="If provided, only this component will be processed")
    parser.add_argument("--config", dest="config", type=str, required=False, help="If provided, this config file will be processed")
    parser.add_argument("--destination", dest="destination", type=str, required=False, help="Destination directory of the created helm chart")
    parser.add_argument("--skipOverrides", dest="skipOverrides", type=bool, help="If true, overrides such as helm flow control will not be applied")
    parser.add_argument("--lint", dest="lint", action='store_true', help="If true, bundles will only be linted to ensure they can be transformed successfully. Default is False.")

    parser.set_defaults(skipOverrides=False)
    parser.set_defaults(lint=False)

    args = parser.parse_args()
    component = args.component
    config_override = args.config
    destination = args.destination
    lint = args.lint
    skipOverrides = args.skipOverrides

    if lint == False and not destination:
        logging.critical("Destination directory is required when not linting.")
        exit(1)

    logging.basicConfig(level=logging.DEBUG)

    # Config.yaml holds the configurations for Operator bundle locations to be used
    # Config.yaml holds the configurations for Operator bundle locations to be used
    if config_override:
        root_override_path = os.path.join(ROOT_DIR, config_override)
        script_override_path = os.path.join(SCRIPT_DIR, config_override)

        if os.path.exists(root_override_path):
            config_yaml = root_override_path
        else:
            config_yaml = script_override_path
    else:
        config_yaml = os.path.join(SCRIPT_DIR, "charts-config.yaml")

    with open(config_yaml, 'r') as f:
        config = yaml.safe_load(f)

    if not config:
        logging.critical("No charts listed in config to be moved!")
        exit(0)

    # Normalize config into a list of components
    if isinstance(config, dict):
        components = config.get("components", [])
    else:
        components = config

    # Optionally filter by a specific component
    if component:
        components = [repo for repo in components if repo.get("repo_name") == component]

    # Loop through each repo in the config.yaml
    for repo in components:
        repo_name = repo.get("repo_name")

        logging.info("Cloning: %s", repo_name)
        repo_path = os.path.join(SCRIPT_DIR, "tmp", repo_name)

        if os.path.exists(repo_path): # If path exists, remove and re-clone
            shutil.rmtree(repo_path)
        repository = Repo.clone_from(repo["github_ref"], repo_path) # Clone repo to above path

        if 'branch' in repo:
            branch = repo['branch']
            repository.git.checkout(branch) # If a branch is specified, checkout that branch
        else:
            branch = ""
        
        # Loop through each operator in the repo identified by the config
        for chart in repo["charts"]:
            if not chartConfigAcceptable(chart):
                logging.critical("Unable to generate helm chart without configuration requirements.")
                exit(1)

            chart_name = chart.get("name", "")
            logging.info(f"Helm Chartifying: '{chart_name}'")

            # Copy over all CRDs to the destination directory
            logging.info(f"Adding CRDs for chart: '{chart_name}'")
            addCRDs(repo_name, chart, destination)

            logging.info(f"Creating helm chart: '{chart_name}'")
            always_or_toggle = chart['always-or-toggle']
            destinationChartPath = os.path.join(destination, "charts", always_or_toggle, chart['name'])

            # Extract the chart version from the charts configuration, 
            # ensuring the version is derived from the repository branch when applicable.
            chartVersion = getChartVersion(chart['updateChartVersion'], repo)

            # Template Helm Chart Directory from 'chart-templates'
            logging.info(f"Templating helm chart '{chart_name}'")
            copyHelmChart(destinationChartPath, repo_name, chart, chartVersion, branch)

            # Render the helm chart before updating the chart resources.
            if not renderChart(destinationChartPath):
                logging.error(f"Failed to render chart {destinationChartPath}")
            
            # Update the helm chart resources with additional overrides
            updateResources(destination, repo_name, chart)

            if not skipOverrides:
                logging.info("Adding Overrides (set --skipOverrides=true to skip) ...")

                injectRequirements(destinationChartPath, chart, branch)
                logging.info("Overrides added.\n")

    logging.info("All repositories and operators processed successfully.")
    logging.info("Performing cleanup...")
    shutil.rmtree((os.path.join(os.path.dirname(os.path.realpath(__file__)), "tmp")), ignore_errors=True)

    logging.info("Cleanup completed.")
    logging.info("Script execution completed.")

if __name__ == "__main__":
   main()