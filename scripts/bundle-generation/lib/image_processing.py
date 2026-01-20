#!/usr/bin/env python3
# Copyright (c) 2024 Red Hat, Inc.
# Copyright Contributors to the Open Cluster Management project

"""
Image reference parsing and templating utilities.
"""

import os
import logging
import yaml


def parse_image_ref(image_ref):
    """
    Parse an image reference and extract its components.

    Args:
        image_ref (str): Full image reference (e.g., "registry/repo:tag@digest")

    Returns:
        dict: Dictionary containing parsed components:
            - registry_and_ns: Registry and namespace portion
            - repository: Repository name
            - tag: Image tag
            - digest: Image digest (if present)
    """
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
        parsed_ref["registry_and_ns"] = remaining_ref[0:slash_pos]
        parsed_ref["repository"] = remaining_ref[slash_pos+1:]
    else:
        parsed_ref["registry_and_ns"] = None
        parsed_ref["repository"] = remaining_ref

    return parsed_ref


def find_templates_of_type(helmChart, kind):
    """
    Find all template files of a specific Kubernetes resource kind.

    Args:
        helmChart (str): Path to the Helm chart
        kind (str): Kubernetes resource kind to find (e.g., "Deployment", "Service")

    Returns:
        list: List of file paths containing resources of the specified kind
    """
    templates = []
    template_path = os.path.join(helmChart, "templates")

    if not os.path.exists(template_path):
        logging.warning(f"Template path does not exist: {template_path}")
        return templates

    for filename in os.listdir(template_path):
        if not filename.endswith(".yaml"):
            continue

        filepath = os.path.join(template_path, filename)
        try:
            with open(filepath, 'r') as f:
                resource = yaml.safe_load(f)

            if resource and resource.get("kind") == kind:
                templates.append(filepath)
        except Exception as e:
            logging.debug(f"Error reading {filepath}: {e}")
            continue

    return templates


def fixImageReferences(helmChart, imageKeyMapping):
    """
    Replace hard-coded image references with Helm template variables.

    Args:
        helmChart (str): Path to the Helm chart
        imageKeyMapping (dict): Mapping of image names to values.yaml keys

    Returns:
        None: Modifies files in place
    """
    if not imageKeyMapping:
        logging.debug("No image mappings provided, skipping image reference fixes")
        return

    logging.info("Fixing image and pull policy references in deployments and values.yaml ...")

    # Find all Deployment templates
    deployment_files = find_templates_of_type(helmChart, "Deployment")

    for deployment_file in deployment_files:
        with open(deployment_file, 'r') as f:
            lines = f.readlines()

        modified = False
        new_lines = []

        for i, line in enumerate(lines):
            # Look for image: references
            if 'image:' in line and '{{' not in line:
                # Extract the image value
                image_match = line.split('image:', 1)
                if len(image_match) == 2:
                    image_value = image_match[1].strip().strip('"').strip("'")
                    parsed = parse_image_ref(image_value)
                    repo_name = parsed.get('repository', '')

                    # Check if we have a mapping for this image
                    if repo_name in imageKeyMapping:
                        values_key = imageKeyMapping[repo_name]
                        indent = line[:len(line) - len(line.lstrip())]
                        new_line = f"{indent}image: '{{{{ .Values.global.imageOverrides.{values_key} }}}}'\n"
                        new_lines.append(new_line)
                        modified = True
                        logging.debug(f"Replaced image reference {repo_name} with template variable {values_key}")
                        continue

            # Look for imagePullPolicy and template it
            if 'imagePullPolicy:' in line and '{{' not in line:
                indent = line[:len(line) - len(line.lstrip())]
                new_line = f"{indent}imagePullPolicy: '{{{{ .Values.global.pullPolicy }}}}'\n"
                new_lines.append(new_line)
                modified = True
                continue

            new_lines.append(line)

        if modified:
            with open(deployment_file, 'w') as f:
                f.writelines(new_lines)
            logging.debug(f"Updated image references in {deployment_file}")

    logging.info("Image references and pull policy in deployments and values.yaml updated successfully.\n")


def fixEnvVarImageReferences(helmChart, imageKeyMapping):
    """
    Replace hard-coded image references in environment variables with Helm template variables.

    Args:
        helmChart (str): Path to the Helm chart
        imageKeyMapping (dict): Mapping of image names to values.yaml keys

    Returns:
        None: Modifies files in place
    """
    if not imageKeyMapping:
        logging.debug("No image mappings provided, skipping env var image reference fixes")
        return

    logging.info("Fixing image references in container 'env' section in deployments and values.yaml ...")

    deployment_files = find_templates_of_type(helmChart, "Deployment")

    for deployment_file in deployment_files:
        with open(deployment_file, 'r') as f:
            lines = f.readlines()

        modified = False
        new_lines = []

        for i, line in enumerate(lines):
            # Look for value: with image references in env sections
            if 'value:' in line and '{{' not in line:
                value_match = line.split('value:', 1)
                if len(value_match) == 2:
                    value_content = value_match[1].strip().strip('"').strip("'")

                    # Check if this looks like an image reference
                    if '/' in value_content or ':' in value_content:
                        parsed = parse_image_ref(value_content)
                        repo_name = parsed.get('repository', '')

                        if repo_name in imageKeyMapping:
                            values_key = imageKeyMapping[repo_name]
                            indent = line[:len(line) - len(line.lstrip())]
                            new_line = f"{indent}value: '{{{{ .Values.global.imageOverrides.{values_key} }}}}'\n"
                            new_lines.append(new_line)
                            modified = True
                            logging.debug(f"Replaced env var image reference {repo_name} with template variable {values_key}")
                            continue

            new_lines.append(line)

        if modified:
            with open(deployment_file, 'w') as f:
                f.writelines(new_lines)
            logging.debug(f"Updated env var image references in {deployment_file}")

    logging.info("Image container env references in deployments and values.yaml updated successfully.\n")
