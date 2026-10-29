#!/usr/bin/env python3
# Copyright (c) 2021 Red Hat, Inc.
# Copyright Contributors to the Open Cluster Management project
# Assumes: Python 3.6+

"""
Shared utilities for bundle-generation chart generators.

This module provides the single, canonical implementation of functions
that were previously duplicated (and diverging) between generate-charts.py
and bundles-to-charts.py.  Both scripts import from here so that
resource_kinds tables, template discovery, image rewriting, and Helm
flow-control injection are defined once.
"""

import logging
import os
import re

import yaml
from packaging import version

# ---------------------------------------------------------------------------
# Canonical resource kind tables (superset of both scripts)
# ---------------------------------------------------------------------------

RESOURCE_KINDS = [
    "AddOnTemplate", "Certificate", "ClusterManagementAddOn",
    "ClusterRole", "ClusterRoleBinding", "ConfigMap", "ConsolePlugin",
    "Deployment", "Issuer", "Job", "ManagedClusterSetBinding",
    "MulticlusterRoleAssignment", "MutatingWebhookConfiguration",
    "NetworkPolicy", "PersistentVolumeClaim", "Placement",
    "PodDisruptionBudget", "Role", "RoleBinding", "Route", "Secret",
    "Service", "StatefulSet", "ValidatingWebhookConfiguration",
    "VerticalPodAutoscaler",
]

NAMESPACE_SCOPED_KINDS = [
    "Certificate", "ConfigMap", "Deployment", "Issuer", "Job",
    "ManagedClusterSetBinding", "MulticlusterRoleAssignment",
    "NetworkPolicy", "PersistentVolumeClaim", "Placement",
    "PodDisruptionBudget", "Role", "RoleBinding", "Route", "Secret",
    "Service", "StatefulSet", "VerticalPodAutoscaler",
]


# ---------------------------------------------------------------------------
# Unified version compatibility check
# ---------------------------------------------------------------------------

def is_version_compatible(branch, min_release_version, min_backplane_version,
                          min_ocm_version, enforce_master_check=True):
    """Determine whether a branch meets a minimum version threshold.

    Returns True when the branch version is at or above the stated
    minimums.  ``"main"`` and ``"master"`` are treated as trunk and
    return ``enforce_master_check``.
    """
    acm_release_version = os.getenv('ACM_RELEASE_VERSION')
    mce_release_version = os.getenv('MCE_RELEASE_VERSION')

    if not acm_release_version and not mce_release_version:
        pattern = r'(\d+\.\d+)'

        if branch in ("main", "master"):
            return bool(enforce_master_check)

        match = re.search(pattern, branch)
        if match:
            v = match.group(1)
            branch_version = version.Version(v)

            if "release-ocm" in branch:
                min_branch_version = version.Version(min_ocm_version)
            elif "release" in branch:
                min_branch_version = version.Version(min_release_version)
            elif "backplane" in branch or "mce" in branch:
                min_branch_version = version.Version(min_backplane_version)
            else:
                logging.error("Unrecognized branch type for branch: %s", branch)
                return False

            return branch_version >= min_branch_version
        else:
            logging.error("Version not found in branch: %s", branch)
            return False

    return bool(
        acm_release_version
        and version.Version(acm_release_version)
        >= version.Version(min_release_version)
        or mce_release_version
        and version.Version(mce_release_version)
        >= version.Version(min_backplane_version)
    )


# ---------------------------------------------------------------------------
# Unified find_templates_of_type
# ---------------------------------------------------------------------------

def find_templates_of_type(helmChart, kind, branch=None):
    """Return filepaths of templates matching a given resource Kind.

    Supports multi-document YAML files when *branch* triggers version
    gating (ACM 2.16+ / MCE 2.11+).  When *branch* is ``None`` or
    the version is too old, falls back to single-document parsing.
    """
    resources = []
    templates_dir = os.path.join(helmChart, "templates")
    if not os.path.isdir(templates_dir):
        return resources
    for filename in os.listdir(templates_dir):
        if not filename.endswith((".yaml", ".yml")):
            continue
        filePath = os.path.join(templates_dir, filename)
        with open(filePath, 'r', encoding='utf-8') as f:
            try:
                if branch is not None and is_version_compatible(
                    branch, '2.16', '2.11', '2.16'
                ):
                    docs = list(yaml.safe_load_all(f))
                else:
                    single_doc = yaml.safe_load(f)
                    docs = [single_doc] if single_doc else []
                for doc in docs:
                    if doc and doc.get('kind') == kind:
                        resources.append(filePath)
                        break
            except yaml.YAMLError:
                continue
    return resources


# ---------------------------------------------------------------------------
# Shared image-reference helpers
# ---------------------------------------------------------------------------

def split_at(the_str, the_delim, favor_right=True):
    """Split a string at a delimiter; if absent, treat as all-left or all-right."""
    split_pos = the_str.find(the_delim)
    if split_pos > 0:
        return the_str[:split_pos], the_str[split_pos + 1:]
    if favor_right:
        return None, the_str
    return the_str, None


def parse_image_ref(image_ref):
    """Parse a container image reference into its components."""
    parsed_ref = {}
    remaining_ref = image_ref

    at_pos = remaining_ref.rfind("@")
    if at_pos > 0:
        parsed_ref["digest"] = remaining_ref[at_pos + 1:]
        remaining_ref = remaining_ref[:at_pos]
    else:
        parsed_ref["digest"] = None

    colon_pos = remaining_ref.rfind(":")
    if colon_pos > 0 and colon_pos > remaining_ref.rfind("/"):
        parsed_ref["tag"] = remaining_ref[colon_pos + 1:]
        remaining_ref = remaining_ref[:colon_pos]
    else:
        parsed_ref["tag"] = None

    slash_pos = remaining_ref.rfind("/")
    if slash_pos > 0:
        parsed_ref["repository"] = remaining_ref[slash_pos + 1:]
        rgy_and_ns = remaining_ref[:slash_pos]
    else:
        parsed_ref["repository"] = remaining_ref
        rgy_and_ns = "localhost"
    parsed_ref["registry_and_namespace"] = rgy_and_ns

    rgy, ns = split_at(rgy_and_ns, "/", favor_right=False)
    parsed_ref["registry"] = rgy
    parsed_ref["namespace"] = ns or ""

    slash_pos = image_ref.rfind("/")
    parsed_ref["repository_and_suffix"] = (
        image_ref[slash_pos + 1:] if slash_pos > 0 else image_ref
    )
    return parsed_ref


def env_value_looks_like_image_ref(value):
    """True when a string looks like a container image reference."""
    if not isinstance(value, str) or not value:
        return False
    return "/" in value and (":" in value or "@" in value)


def lookup_image_key(repository, image_key_mapping):
    """Look up a repository in the image-key mapping."""
    return image_key_mapping.get(repository)


def format_image_mapping_error(operator_name, file_path, field, repository):
    """Format a consistent error message for missing image-key mappings."""
    return (
        f"[{operator_name}] No image key mapping for repository '{repository}' "
        f"in {field} ({file_path})"
    )


# ---------------------------------------------------------------------------
# Unified image-reference rewriting
# ---------------------------------------------------------------------------

def fix_image_references(helmChart, imageKeyMapping, branch=None,
                         operator_name=None, apply=True):
    """Rewrite container image: fields in Deployments/Jobs/StatefulSets.

    Returns a list of error strings (empty on success).
    When *apply* is False, validates mappings without writing files.
    """
    logging.info("Fixing image and pull policy references in deployments and values.yaml ...")
    valuesYaml = os.path.join(helmChart, "values.yaml")

    if not os.path.exists(valuesYaml):
        logging.error("%s does not exist. Skipping image and pull policy updates.", valuesYaml)
        return []

    with open(valuesYaml, 'r', encoding='utf-8') as f:
        values = yaml.safe_load(f)

    resource_kinds = ["Deployment", "Job", "StatefulSet"]
    errors = []
    pending_updates = []
    imageKeys = []

    for kind in resource_kinds:
        resource_templates = find_templates_of_type(helmChart, kind, branch)
        for template_path in resource_templates:
            with open(template_path, 'r', encoding='utf-8') as f:
                resource_data = yaml.safe_load(f)

            for container_section in ('containers', 'initContainers'):
                containers = (
                    resource_data.get('spec', {})
                    .get('template', {})
                    .get('spec', {})
                    .get(container_section, [])
                )
                if not containers:
                    continue
                for container in containers:
                    if 'image' not in container:
                        continue
                    repository = parse_image_ref(container['image'])["repository"]
                    container_name = container.get('name', 'unknown')
                    image_key = lookup_image_key(repository, imageKeyMapping)
                    if image_key is None:
                        label = operator_name or os.path.basename(helmChart)
                        errors.append(format_image_mapping_error(
                            label,
                            os.path.relpath(template_path, helmChart),
                            f"container[{container_name}].image",
                            repository,
                        ))
                        logging.error(errors[-1])
                        continue
                    imageKeys.append(image_key)
                    if apply:
                        container['image'] = "{{ .Values.global.imageOverrides." + image_key + " }}"
                        container['imagePullPolicy'] = "{{ .Values.global.pullPolicy }}"

                # Handle --agent-image-name args for init containers in Deployments
                if container_section == 'initContainers' and kind == "Deployment" and apply and not errors:
                    for container in containers:
                        args = container.get('args', [])
                        refreshed_args = []
                        for arg in args:
                            if "--agent-image-name" not in arg:
                                refreshed_args.append(arg)
                            else:
                                refreshed_args.append(
                                    "--agent-image-name={{ .Values.global.imageOverrides."
                                    + imageKeys[-1] + " }}"
                                )
                        container['args'] = refreshed_args

            if apply and not errors:
                pending_updates.append((template_path, resource_data))

    if errors or not apply:
        return errors

    for template_path, resource_data in pending_updates:
        with open(template_path, 'w', encoding='utf-8') as f:
            yaml.dump(resource_data, f, width=float("inf"), sort_keys=True)

    try:
        del values['global']['imageOverrides']['imageOverride']
    except KeyError:
        pass
    for imageKey in imageKeys:
        values['global']['imageOverrides'][imageKey] = ""
    with open(valuesYaml, 'w', encoding='utf-8') as f:
        yaml.dump(values, f, width=float("inf"), sort_keys=True)
    logging.info("Image references and pull policy in deployments and values.yaml updated successfully.\n")
    return errors


def fix_env_var_image_references(helmChart, imageKeyMapping, branch=None,
                                 operator_name=None, apply=True,
                                 envImageMappings=None):
    """Rewrite env var image references in Deployments.

    Returns a list of error strings (empty on success).
    When *apply* is False, validates mappings without writing files.
    Env vars using ``valueFrom`` are silently skipped.
    """
    logging.info("Fixing image references in container 'env' section in deployments and values.yaml ...")
    envImageMappings = envImageMappings or {}
    valuesYaml = os.path.join(helmChart, "values.yaml")

    if not os.path.exists(valuesYaml):
        logging.error("%s does not exist. Skipping environment variable image reference updates.", valuesYaml)
        return []

    deployments = find_templates_of_type(helmChart, 'Deployment', branch)
    label = operator_name or os.path.basename(helmChart)
    errors = []
    pending_updates = []
    imageKeys = []

    for deployment in deployments:
        with open(deployment, 'r', encoding='utf-8') as f:
            deploy = yaml.safe_load(f)

        containers = deploy['spec']['template']['spec']['containers']
        for container in containers:
            if 'env' not in container:
                continue
            for env in container['env']:
                env_var_name = env['name']
                # Skip valueFrom entries (fieldRef, secretKeyRef, etc.)
                if 'value' not in env:
                    if 'valueFrom' in env:
                        logging.info(
                            "[%s] Skipping env var '%s' in %s -- uses valueFrom, not a literal value",
                            label, env_var_name,
                            os.path.relpath(deployment, helmChart),
                        )
                    continue
                explicit_key = envImageMappings.get(env_var_name)
                if explicit_key is None and not env_var_name.endswith('_IMAGE'):
                    if env_value_looks_like_image_ref(env.get('value')):
                        logging.warning(
                            "[%s] Skipping image-like env var '%s' in %s; "
                            "add it to envImageMappings to template it",
                            label, env_var_name,
                            os.path.relpath(deployment, helmChart),
                        )
                    continue
                repository = parse_image_ref(env['value'])['repository']
                if explicit_key is not None:
                    if explicit_key not in imageKeyMapping.values():
                        errors.append(
                            f"[{label}] envImageMappings entry '{env_var_name}' maps to unknown "
                            f"image key '{explicit_key}' in {os.path.relpath(deployment, helmChart)}; "
                            f"expected one of the imageMappings values"
                        )
                        logging.error(errors[-1])
                        continue
                    repository_key = lookup_image_key(repository, imageKeyMapping)
                    if repository_key is not None and repository_key != explicit_key:
                        logging.warning(
                            "envImageMappings entry '%s' -> '%s' overrides repository mapping '%s' for image '%s'",
                            env_var_name, explicit_key, repository_key, repository,
                        )
                    image_key = explicit_key
                else:
                    image_key = lookup_image_key(repository, imageKeyMapping)
                    if image_key is None:
                        errors.append(format_image_mapping_error(
                            label,
                            os.path.relpath(deployment, helmChart),
                            f"env.{env_var_name}",
                            repository,
                        ))
                        logging.error(errors[-1])
                        continue
                imageKeys.append(image_key)
                if apply:
                    env['value'] = "{{ .Values.global.imageOverrides." + image_key + " }}"

        if apply:
            pending_updates.append((deployment, deploy))

    if errors or not apply:
        return errors

    for deployment, deploy in pending_updates:
        with open(deployment, 'w', encoding='utf-8') as f:
            yaml.dump(deploy, f, width=float("inf"), sort_keys=True)

    with open(valuesYaml, 'r', encoding='utf-8') as f:
        values = yaml.safe_load(f)
    for imageKey in imageKeys:
        values['global']['imageOverrides'][imageKey] = ""
    with open(valuesYaml, 'w', encoding='utf-8') as f:
        yaml.dump(values, f, width=float("inf"), sort_keys=True)
    logging.info("Image container env references in deployments and values.yaml updated successfully.\n")
    return errors


def fix_addon_template_image_references(helmChart, imageKeyMapping, branch=None,
                                        operator_name=None, apply=True):
    """Rewrite image references inside AddOnTemplate manifests.

    Handles Deployment and Job manifests within the AddOnTemplate's
    agentSpec.workload.manifests.
    Returns a list of error strings (empty on success).
    """
    logging.info("Fixing image references in addon templates and values.yaml ...")
    addonTemplates = find_templates_of_type(helmChart, 'AddOnTemplate', branch)
    label = operator_name or os.path.basename(helmChart)
    errors = []
    all_imageKeys = []
    pending_updates = []

    for addonTemplate in addonTemplates:
        with open(addonTemplate, 'r', encoding='utf-8') as f:
            if branch is not None and is_version_compatible(branch, '2.16', '2.11', '2.16'):
                docs = list(yaml.safe_load_all(f))
            else:
                single_doc = yaml.safe_load(f)
                docs = [single_doc] if single_doc else []

        for templateContent in docs:
            if not templateContent or templateContent.get('kind') != 'AddOnTemplate':
                continue
            agentSpec = templateContent.get('spec', {}).get('agentSpec', {})
            if 'workload' not in agentSpec:
                continue
            workload = agentSpec['workload']
            if 'manifests' not in workload:
                continue
            for manifest in workload['manifests']:
                if manifest.get('kind') not in ('Deployment', 'Job'):
                    continue
                manifest_kind = manifest['kind']
                manifest_name = manifest.get('metadata', {}).get('name', 'unknown')
                containers = (
                    manifest.get('spec', {})
                    .get('template', {})
                    .get('spec', {})
                    .get('containers', [])
                )
                for container in containers:
                    if 'image' not in container:
                        continue
                    repository = parse_image_ref(container['image'])["repository"]
                    container_name = container.get('name', 'unknown')
                    image_key = lookup_image_key(repository, imageKeyMapping)
                    if image_key is None:
                        errors.append(format_image_mapping_error(
                            label,
                            os.path.relpath(addonTemplate, helmChart),
                            f"{manifest_kind}[{manifest_name}].container[{container_name}].image",
                            repository,
                        ))
                        logging.error(errors[-1])
                        continue
                    all_imageKeys.append(image_key)
                    if apply:
                        container['image'] = "{{ .Values.global.imageOverrides." + image_key + " }}"

        if apply:
            pending_updates.append((addonTemplate, docs))

    if errors or not apply:
        return errors

    if not all_imageKeys:
        return errors

    for addonTemplate, docs in pending_updates:
        with open(addonTemplate, 'w', encoding='utf-8') as f:
            yaml.dump_all(docs, f, width=float("inf"), sort_keys=True)
        logging.info("AddOnTemplate updated with image override successfully.")

    valuesYaml = os.path.join(helmChart, "values.yaml")
    with open(valuesYaml, 'r', encoding='utf-8') as f:
        values = yaml.safe_load(f)
    try:
        del values['global']['imageOverrides']['imageOverride']
    except KeyError:
        pass
    for imageKey in all_imageKeys:
        values['global']['imageOverrides'][imageKey] = ""
    with open(valuesYaml, 'w', encoding='utf-8') as f:
        yaml.dump(values, f, width=float("inf"), sort_keys=True)
    logging.info("Image references in addon templates and values.yaml updated successfully.\n")
    return errors


# ---------------------------------------------------------------------------
# Unified Helm flow-control injection
# ---------------------------------------------------------------------------

def insertFlowControlIfAround(lines_list, first_line_index, last_line_index,
                              if_condition):
    """Insert Helm if/end around first_line..last_line without shifting indices."""
    lines_list[first_line_index] = (
        f"{{{{- if {if_condition} }}}}\n{lines_list[first_line_index]}"
    )
    lines_list[last_line_index] = (
        f"{lines_list[last_line_index]}{{{{- end }}}}\n"
    )


def inject_helm_flow_control(deployment, branch, sizes=None):
    """Inject Helm flow control for nodeSelector, proxy, tolerations, seccomp, and sizes.

    This is the single converged implementation.  Key behaviours preserved:
    - sizes.yaml resource injection (from bundles-to-charts)
    - ``"- env:"`` detection (from generate-charts)
    - ``semverCompare`` guard with ``prev_line`` check (from generate-charts)
    - File is written **once** after the loop (O(n) not O(n^2))
    """
    logging.info("Adding Helm flow control for NodeSelector, Proxy Overrides, and SeccompProfile ...")

    # Load the deployment YAML for sizes matching (only if sizes provided)
    deployx = None
    if sizes:
        with open(deployment, 'r', encoding='utf-8') as f:
            deployx = yaml.safe_load(f)

    with open(deployment, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    for i, line in enumerate(lines):
        stripped = line.strip()

        if stripped == "nodeSelector: ''":
            lines[i] = (
                "{{- with .Values.hubconfig.nodeSelector }}\n"
                "      nodeSelector:\n"
                "{{ toYaml . | indent 8 }}\n"
                "{{- end }}\n"
            )

        if stripped == "imagePullSecrets: ''":
            lines[i] = (
                "{{- if .Values.global.pullSecret }}\n"
                "      imagePullSecrets:\n"
                "      - name: {{ .Values.global.pullSecret }}\n"
                "{{- end }}\n"
            )

        if stripped == "tolerations: ''":
            lines[i] = (
                "{{- with .Values.hubconfig.tolerations }}\n"
                "      tolerations:\n"
                "      {{- range . }}\n"
                "      - {{ if .Key }} key: {{ .Key }} {{- end }}\n"
                "        {{ if .Operator }} operator: {{ .Operator }} {{- end }}\n"
                "        {{ if .Value }} value: {{ .Value }} {{- end }}\n"
                "        {{ if .Effect }} effect: {{ .Effect }} {{- end }}\n"
                "        {{ if .TolerationSeconds }} tolerationSeconds: {{ .TolerationSeconds }} {{- end }}\n"
                "        {{- end }}\n"
                "{{- end }}\n"
            )

        # Detect env: with all variants (including "- env:" from generate-charts)
        if stripped in ("env:", "- env:", "env: {}", "env: []"):
            # Preserve the original indentation and YAML list marker prefix.
            # When a container's first field is `env`, the line reads
            # "        - env:" — the `- ` list marker must be kept or the
            # rendered YAML is structurally broken.
            leading = line[: len(line) - len(line.lstrip())]
            if stripped.startswith("- "):
                prefix = leading + "- "
                # Indent child keys relative to the `- ` item
                child_indent = leading + "  "
            else:
                prefix = leading
                child_indent = leading
            lines[i] = (
                f"{prefix}env:\n"
                "{{- if .Values.hubconfig.proxyConfigs }}\n"
                f"{child_indent}- name: HTTP_PROXY\n"
                f"{child_indent}  value: {{{{ .Values.hubconfig.proxyConfigs.HTTP_PROXY }}}}\n"
                f"{child_indent}- name: HTTPS_PROXY\n"
                f"{child_indent}  value: {{{{ .Values.hubconfig.proxyConfigs.HTTPS_PROXY }}}}\n"
                f"{child_indent}- name: NO_PROXY\n"
                f"{child_indent}  value: {{{{ .Values.hubconfig.proxyConfigs.NO_PROXY }}}}\n"
                "{{- end }}\n"
            )

        if is_version_compatible(branch, '9.9', '9.9', '9.9', False):
            if 'replicas:' in stripped:
                lines[i] = "  replicas: {{ .Values.hubconfig.replicaCount }}\n"

        # Sizes.yaml resource injection (from bundles-to-charts)
        if sizes and deployx:
            for sizDeployment in sizes.get("deployments", []):
                if sizDeployment["name"] == deployx.get("metadata", {}).get("name"):
                    for container in sizDeployment["containers"]:
                        if stripped == "resources: REPLACE-" + container["name"]:
                            lines[i] = (
                                "        resources:\n"
                                '{{-  if eq .values.hubconfig.hubSize "Small" }}\n'
                                "          limits:\n"
                                "            cpu: " + container["Small"]["limits"]["cpu"] + "\n"
                                "            memory: " + container["Small"]["limits"]["memory"] + "\n"
                                "          requests:\n"
                                "            cpu: " + container["Small"]["requests"]["cpu"] + "\n"
                                "            memory: " + container["Small"]["requests"]["memory"] + "\n"
                                "{{- end }}\n"
                                '{{ if eq .values.hubconfig.hubSize "Medium" }}\n'
                                "          limits:\n"
                                "            cpu: " + container["Medium"]["limits"]["cpu"] + "\n"
                                "            memory: " + container["Medium"]["limits"]["memory"] + "\n"
                                "          requests:\n"
                                "            cpu: " + container["Medium"]["requests"]["cpu"] + "\n"
                                "            memory: " + container["Medium"]["requests"]["memory"] + "\n"
                                "{{- end }}\n"
                                '{{-  if eq .values.hubconfig.hubSize "Large" }}\n'
                                "          limits:\n"
                                "            cpu: " + container["Large"]["limits"]["cpu"] + "\n"
                                "            memory: " + container["Large"]["limits"]["memory"] + "\n"
                                "          requests:\n"
                                "            cpu: " + container["Large"]["requests"]["cpu"] + "\n"
                                "            memory: " + container["Large"]["requests"]["memory"] + "\n"
                                "{{- end }}\n"
                                '{{ if eq .values.hubconfig.hubSize "ExtraLarge" }}\n'
                                "          limits:\n"
                                "            cpu: " + container["ExtraLarge"]["limits"]["cpu"] + "\n"
                                "            memory: " + container["ExtraLarge"]["limits"]["memory"] + "\n"
                                "          requests:\n"
                                "            cpu: " + container["ExtraLarge"]["requests"]["cpu"] + "\n"
                                "            memory: " + container["ExtraLarge"]["requests"]["memory"] + "\n"
                                "{{- end }}\n"
                            )

        # seccompProfile with semverCompare guard and prev_line check
        if stripped == "seccompProfile:":
            next_line = lines[i + 1] if i + 1 < len(lines) else ""
            prev_line = lines[i - 1] if i > 0 else ""
            if (next_line.strip() == "type: RuntimeDefault"
                    and "semverCompare" not in prev_line):
                insertFlowControlIfAround(
                    lines, i, i + 1,
                    'semverCompare ">=4.11.0" .Values.hubconfig.ocpVersion',
                )
                if is_version_compatible(branch, '9.9', '2.7', '2.12'):
                    insertFlowControlIfAround(
                        lines, i, i + 1, ".Values.global.deployOnOCP",
                    )

    # Write once after the loop (not inside the loop)
    with open(deployment, 'w', encoding='utf-8') as f:
        f.writelines(lines)
    logging.info("Added Helm flow control for NodeSelector, Proxy, and SeccompProfile Overrides.\n")
