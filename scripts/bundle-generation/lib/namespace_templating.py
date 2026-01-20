#!/usr/bin/env python3
# Copyright (c) 2024 Red Hat, Inc.
# Copyright Contributors to the Open Cluster Management project

"""
Namespace templating utilities for Kubernetes resources and CRDs.
"""

import os
import re
import logging
import yaml


def ensure_webhook_namespace(resource_data, resource_name, default_namespace):
    """
    Ensures that webhook service namespace is templated with Helm values.

    Args:
        resource_data (dict): The webhook configuration resource data
        resource_name (str): The name of the webhook configuration
        default_namespace (str): The default namespace to use

    Returns:
        None: Modifies resource_data in place
    """
    if 'webhooks' not in resource_data:
        return

    for webhook in resource_data['webhooks']:
        if 'clientConfig' in webhook and 'service' in webhook['clientConfig']:
            service = webhook['clientConfig']['service']
            service_name = service.get('name', 'unknown')
            service_namespace = service.get('namespace')
            service_path = service.get('path', '/')

            if service_namespace is None:
                # Use the default Helm namespace if not specified
                service_namespace = default_namespace
            elif service_namespace == default_namespace:
                # Already set to the plain template variable, leave as is
                pass
            elif '{{' in str(service_namespace) and 'default' in str(service_namespace):
                # Already has the default template pattern, leave as is
                pass
            else:
                # Update Helm templating to override existing namespace
                service_namespace = f"{{{{ default \"{service_namespace}\" .Values.global.namespace }}}}"

            service['namespace'] = service_namespace

            logging.info(f"Webhook Configuration: {resource_name}")
            logging.info(f"  Service: {service_name}")
            logging.info(f"  Namespace: {service_namespace}")
            logging.info(f"  Path: {service_path}\n")


def ensure_certificate_namespace_references(resource_data, resource_name, resource_namespace):
    """
    Ensures that namespace references in Certificate spec fields (commonName, dnsNames)
    use the same templated namespace as metadata.namespace.

    Args:
        resource_data (dict): The Certificate resource data
        resource_name (str): The name of the Certificate resource
        resource_namespace (str): The templated namespace string to use for replacements

    Returns:
        None: Modifies resource_data in place
    """
    if 'spec' not in resource_data:
        return

    spec = resource_data['spec']

    # Extract the actual namespace value from the templated string if it exists
    namespace_match = re.search(r'default\s+"([^"]+)"', resource_namespace)
    if namespace_match:
        hardcoded_namespace = namespace_match.group(1)
    else:
        # If no default found, try to extract plain namespace
        namespace_match = re.search(r'([a-z0-9-]+)', resource_namespace)
        if namespace_match:
            hardcoded_namespace = namespace_match.group(1)
        else:
            logging.warning(f"Could not extract namespace from: {resource_namespace}")
            return

    # Update commonName if it contains the hardcoded namespace
    if 'commonName' in spec:
        common_name = spec['commonName']
        if hardcoded_namespace in common_name:
            # Replace hardcoded namespace with templated version
            templated_common_name = common_name.replace(
                f".{hardcoded_namespace}.",
                f".{{{{ default \"{hardcoded_namespace}\" .Values.global.namespace }}}}."
            )
            spec['commonName'] = templated_common_name
            logging.info(f"Certificate '{resource_name}' commonName updated to: {templated_common_name}")

    # Update dnsNames entries that contain the hardcoded namespace
    if 'dnsNames' in spec:
        dns_names = spec['dnsNames']
        for i, dns_name in enumerate(dns_names):
            if hardcoded_namespace in dns_name:
                # Replace hardcoded namespace with templated version
                templated_dns_name = dns_name.replace(
                    f".{hardcoded_namespace}.",
                    f".{{{{ default \"{hardcoded_namespace}\" .Values.global.namespace }}}}."
                )
                dns_names[i] = templated_dns_name
                logging.info(f"Certificate '{resource_name}' dnsName[{i}] updated to: {templated_dns_name}")


def process_crd_namespaces(crd_data, crd_name):
    """
    Process CRD to template namespace references in webhook service configs and annotations.

    Args:
        crd_data (dict): The CRD resource data
        crd_name (str): The name of the CRD file

    Returns:
        None: Modifies crd_data in place
    """
    # Process webhook conversion service namespace
    if 'spec' in crd_data and 'conversion' in crd_data['spec']:
        conversion = crd_data['spec']['conversion']
        if conversion.get('strategy') == 'Webhook' and 'webhook' in conversion:
            webhook = conversion['webhook']
            if 'clientConfig' in webhook and 'service' in webhook['clientConfig']:
                service = webhook['clientConfig']['service']
                service_namespace = service.get('namespace')

                if service_namespace and '{{' not in str(service_namespace):
                    # Template the namespace
                    templated_namespace = f"{{{{ default \"{service_namespace}\" .Values.global.namespace }}}}"
                    service['namespace'] = templated_namespace
                    logging.info(f"CRD '{crd_name}': Templated webhook service namespace from '{service_namespace}' to '{templated_namespace}'")

    # Process cert-manager annotation namespace references
    if 'metadata' in crd_data and 'annotations' in crd_data['metadata']:
        annotations = crd_data['metadata']['annotations']
        cert_annotation_key = 'cert-manager.io/inject-ca-from'

        if cert_annotation_key in annotations:
            annotation_value = annotations[cert_annotation_key]
            # Format is typically: namespace/certificate-name
            if '/' in annotation_value and '{{' not in annotation_value:
                parts = annotation_value.split('/', 1)
                if len(parts) == 2:
                    namespace_part, cert_name = parts
                    templated_annotation = f"{{{{ default \"{namespace_part}\" .Values.global.namespace }}}}/{cert_name}"
                    annotations[cert_annotation_key] = templated_annotation
                    logging.info(f"CRD '{crd_name}': Templated cert-manager annotation from '{annotation_value}' to '{templated_annotation}'")


def update_helm_resources(chartName, helmChart, skip_rbac_overrides, exclusions, inclusions, branch):
    """
    Update Helm chart resources to use templated namespaces and other Helm values.

    This function processes all YAML templates in a Helm chart and adds namespace templating,
    handles RoleBindings, and ensures proper Helm value references.

    Args:
        chartName (str): Name of the chart being processed
        helmChart (str): Path to the Helm chart directory
        skip_rbac_overrides (bool): If True, skip RBAC namespace overrides
        exclusions (list): List of resource types to exclude from processing
        inclusions (list): List of resource types to explicitly include
        branch (str): Git branch name (used for version-specific logic)

    Returns:
        None: Modifies template files in place
    """
    logging.info(f"Updating resources chart: {chartName}")

    default_namespace = """{{ .Values.global.namespace }}"""

    # Namespace-scoped resource types that should have namespace templating
    namespace_scoped_kinds = [
        "ServiceAccount", "Role", "RoleBinding", "Service", "Deployment", "StatefulSet",
        "ConfigMap", "Secret", "Ingress", "PersistentVolumeClaim", "Pod", "ReplicaSet",
        "DaemonSet", "Job", "CronJob", "HorizontalPodAutoscaler", "NetworkPolicy",
        "PodDisruptionBudget", "Lease", "EndpointSlice", "Endpoints",
        "ClusterManagementAddOn", "Placement", "ManagedClusterSetBinding",
        "AddOnDeploymentConfig", "Certificate", "Issuer"
    ]

    templates_path = os.path.join(helmChart, "templates")

    if not os.path.exists(templates_path):
        logging.warning(f"Templates path does not exist: {templates_path}")
        return

    # Process all YAML files in templates directory
    for filename in os.listdir(templates_path):
        if not filename.endswith(".yaml"):
            continue

        file_path = os.path.join(templates_path, filename)

        try:
            with open(file_path, 'r') as f:
                resource_data = yaml.safe_load(f)

            if not resource_data or 'kind' not in resource_data:
                continue

            kind = resource_data['kind']
            resource_name = resource_data.get('metadata', {}).get('name', filename)

            # Apply exclusions/inclusions
            if exclusions and kind in exclusions:
                logging.debug(f"Skipping excluded resource type: {kind}")
                continue

            if inclusions and kind not in inclusions:
                logging.debug(f"Skipping non-included resource type: {kind}")
                continue

            # Update namespace for namespace-scoped resources
            if kind in namespace_scoped_kinds:
                resource_namespace = resource_data['metadata'].get('namespace')

                if resource_namespace is None or resource_namespace == "PLACEHOLDER_NAMESPACE" or resource_namespace == default_namespace:
                    # Use the default Helm namespace if not specified
                    resource_namespace = default_namespace
                    logging.debug(f"Namespace for '{resource_name}' set to template variable: {resource_namespace}")
                elif '{{' in str(resource_namespace) and 'default' in str(resource_namespace):
                    # Already has the default template pattern, leave as is
                    logging.debug(f"Namespace for '{resource_name}' already has default template: {resource_namespace}")
                else:
                    # Transform hardcoded namespace to use default with fallback
                    resource_namespace = f"{{{{ default \"{resource_namespace}\" .Values.global.namespace }}}}"
                    logging.debug(f"Namespace for '{resource_name}' transformed to: {resource_namespace}")

                resource_data['metadata']['namespace'] = resource_namespace
                logging.info(f"Namespace for '{resource_name}' set to: {resource_namespace}")

            # Special handling for Certificate resources
            if kind == 'Certificate':
                ensure_certificate_namespace_references(resource_data, resource_name, resource_namespace)

            # Special handling for webhooks
            if kind in ["MutatingWebhookConfiguration", "ValidatingWebhookConfiguration"]:
                ensure_webhook_namespace(resource_data, resource_name, default_namespace)

            # Special handling for RoleBindings
            if kind in ["RoleBinding", "ClusterRoleBinding"]:
                if 'subjects' in resource_data:
                    for subject in resource_data['subjects']:
                        if subject.get('kind') in ['ServiceAccount', 'User', 'Group']:
                            subject_namespace = subject.get('namespace')
                            target_namespace = default_namespace

                            if subject_namespace is None:
                                subject['namespace'] = target_namespace
                            elif subject_namespace == default_namespace:
                                target_namespace = subject_namespace
                            elif '{{' in str(subject_namespace) and 'default' in str(subject_namespace):
                                target_namespace = subject_namespace
                            else:
                                target_namespace = f"{{{{ default \"{subject_namespace}\" .Values.global.namespace }}}}"
                                subject['namespace'] = target_namespace

                            if not skip_rbac_overrides:
                                logging.info(f"Updated RoleBinding subject namespace to: {target_namespace}")

            # Write the modified resource back
            with open(file_path, 'w') as f:
                yaml.dump(resource_data, f, width=float("inf"), default_flow_style=False, allow_unicode=True)

        except Exception as e:
            logging.error(f"Error processing {file_path}: {e}")
            continue

    logging.info(f"Finished updating resources for chart: {chartName}\n")
