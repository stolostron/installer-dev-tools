#!/usr/bin/env python3
# Copyright (c) 2025 Red Hat, Inc.
# Copyright Contributors to the Open Cluster Management project
# Assumes: Python 3.6+

from typing import Dict, List, Optional, Any, Callable
import argparse
import os
import re
import sys
import urllib.request
import urllib.error
import json
import tempfile
import shutil

# Check dependencies before importing
def check_dependencies() -> None:
    """Check that required dependencies are available.

    Exits with error message if dependencies are missing.
    """
    missing_deps = []

    try:
        import inquirer
    except ImportError:
        missing_deps.append("inquirer")

    try:
        import jsonschema
    except ImportError:
        missing_deps.append("jsonschema")

    try:
        import utils.common
    except ImportError:
        missing_deps.append("utils.common (from installer-dev-tools)")

    if missing_deps:
        print("❌ Missing required dependencies:")
        for dep in missing_deps:
            print(f"   - {dep}")
        print("\n💡 Install missing dependencies:")
        if "inquirer" in missing_deps or "jsonschema" in missing_deps:
            print("   pip3 install inquirer jsonschema")
        if "utils.common" in missing_deps:
            print("   Ensure you're running this from the correct directory")
        sys.exit(1)

check_dependencies()

import utils.common
import inquirer
import jsonschema

# Configuration - Modify these to add new options
EXCLUSION_OPTIONS = [
    "read-only-root-filesystem",
    # Add more exclusion options here as needed
]

INCLUSION_OPTIONS = [
    "pull-secret-override",
    # Add more inclusion options here as needed
]

ESCAPED_TEMPLATE_VARIABLES = [
    "CLUSTER_NAME",
    "GITOPS_OPERATOR_IMAGE",
    "GITOPS_OPERATOR_NAMESPACE",
    "GITOPS_IMAGE",
    "GITOPS_NAMESPACE",
    "HUB_KUBECONFIG",
    "INSTALL_NAMESPACE",
    "REDIS_IMAGE",
    "RECONCILE_SCOPE",
    # Add more template variables here as needed
]

RESOURCE_KINDS = [
    "Deployment",
    "Job",
    "StatefulSet",
    # Add more Kubernetes resource kinds here as needed
]

COMPONENT_STATUSES = [
    "dev-preview",
    "tech-preview",
    "GA",
]

SECCOMP_PROFILE_TYPES = [
    "RuntimeDefault",
    "Unconfined",
    "Localhost",
]

FSGROUP_CHANGE_POLICIES = [
    "OnRootMismatch",
    "Always",
]

# JSON Schema for onboard-request YAML validation
ONBOARD_REQUEST_SCHEMA = {
    "type": "object",
    "required": ["onboard-type", "components"],
    "properties": {
        "onboard-type": {
            "type": "string",
            "enum": ["olm", "helm"],
            "description": "Type of component to onboard"
        },
        "components": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["name"],
                "properties": {
                    "name": {
                        "type": "string",
                        "minLength": 1,
                        "description": "Component name"
                    },
                    "bundle-repo": {
                        "type": "string",
                        "description": "OLM bundle repository (required for olm type)"
                    },
                    "bundle-version": {
                        "type": "string",
                        "description": "OLM bundle version (required for olm type)"
                    },
                    "bundle-path": {
                        "type": "string",
                        "description": "Optional OLM bundle path"
                    },
                    "chart-repo": {
                        "type": "string",
                        "description": "Helm chart repository (required for helm type)"
                    },
                    "chart-name": {
                        "type": "string",
                        "description": "Helm chart name (required for helm type)"
                    },
                    "chart-version": {
                        "type": "string",
                        "description": "Helm chart version (required for helm type)"
                    },
                    "image-mappings": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["registry", "image"],
                            "properties": {
                                "registry": {"type": "string"},
                                "image": {"type": "string"}
                            },
                            "additionalProperties": False
                        }
                    },
                    "webhook-paths": {
                        "type": "array",
                        "items": {"type": "string"}
                    },
                    "security-context": {
                        "type": "object",
                        "properties": {
                            "pod": {
                                "type": "object",
                                "properties": {
                                    "runAsUser": {"type": "integer", "minimum": 0},
                                    "runAsGroup": {"type": "integer", "minimum": 0},
                                    "fsGroup": {"type": "integer", "minimum": 0},
                                    "fsGroupChangePolicy": {"type": "string", "enum": FSGROUP_CHANGE_POLICIES},
                                    "supplementalGroups": {
                                        "type": "array",
                                        "items": {"type": "integer", "minimum": 0}
                                    },
                                    "seLinuxOptions": {
                                        "type": "object",
                                        "properties": {
                                            "level": {"type": "string"},
                                            "role": {"type": "string"},
                                            "type": {"type": "string"},
                                            "user": {"type": "string"}
                                        }
                                    },
                                    "seccompProfile": {
                                        "type": "object",
                                        "required": ["type"],
                                        "properties": {
                                            "type": {"type": "string", "enum": SECCOMP_PROFILE_TYPES},
                                            "localhostProfile": {"type": "string"}
                                        }
                                    },
                                    "runAsNonRoot": {"type": "boolean"}
                                }
                            },
                            "container": {
                                "type": "object",
                                "properties": {
                                    "runAsUser": {"type": "integer", "minimum": 0},
                                    "runAsGroup": {"type": "integer", "minimum": 0},
                                    "runAsNonRoot": {"type": "boolean"},
                                    "allowPrivilegeEscalation": {"type": "boolean"},
                                    "readOnlyRootFilesystem": {"type": "boolean"},
                                    "capabilities": {
                                        "type": "object",
                                        "properties": {
                                            "add": {
                                                "type": "array",
                                                "items": {"type": "string"}
                                            },
                                            "drop": {
                                                "type": "array",
                                                "items": {"type": "string"}
                                            }
                                        }
                                    },
                                    "seLinuxOptions": {
                                        "type": "object",
                                        "properties": {
                                            "level": {"type": "string"},
                                            "role": {"type": "string"},
                                            "type": {"type": "string"},
                                            "user": {"type": "string"}
                                        }
                                    },
                                    "seccompProfile": {
                                        "type": "object",
                                        "required": ["type"],
                                        "properties": {
                                            "type": {"type": "string", "enum": SECCOMP_PROFILE_TYPES},
                                            "localhostProfile": {"type": "string"}
                                        }
                                    }
                                }
                            }
                        }
                    },
                    "exclusions": {
                        "type": "array",
                        "items": {"type": "string"}
                    },
                    "inclusions": {
                        "type": "array",
                        "items": {"type": "string"}
                    },
                    "escaped-template-variables": {
                        "type": "array",
                        "items": {"type": "string"}
                    },
                    "resource-kinds": {
                        "type": "array",
                        "items": {"type": "string"}
                    },
                    "component-status": {
                        "type": "string",
                        "enum": COMPONENT_STATUSES
                    }
                }
            }
        }
    },
    "additionalProperties": False
}

# ============================================================================
# Input Validation Functions
# ============================================================================

def validate_github_name(name: str) -> bool:
    """Validate GitHub organization or repository name.

    Args:
        name: The org or repo name to validate.

    Returns:
        True if valid, False otherwise.
    """
    # GitHub usernames/orgs: alphanumeric + hyphens, can't start/end with hyphen
    # Max 39 characters
    if not name or len(name) > 39:
        return False
    pattern = r'^[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?$'
    return bool(re.match(pattern, name))

def validate_branch_name(branch: str) -> bool:
    """Validate git branch name.

    Args:
        branch: The branch name to validate.

    Returns:
        True if valid, False otherwise.
    """
    if not branch or len(branch) > 255:
        return False
    # Branch names can't contain: .. \\ ~ ^ : ? * [ @ { space at start/end
    invalid_chars = r'[\s~^:?*\[\\@{]'
    if re.search(invalid_chars, branch) or branch.startswith('.') or branch.endswith('.'):
        return False
    if '..' in branch or branch.endswith('.lock'):
        return False
    return True

def validate_relative_path(path: str) -> bool:
    """Validate that a path is relative and doesn't contain path traversal.

    Args:
        path: The path to validate.

    Returns:
        True if valid, False otherwise.
    """
    if not path:
        return False
    # Reject absolute paths
    if os.path.isabs(path):
        return False
    # Reject path traversal attempts
    if '..' in path.split(os.sep):
        return False
    # Reject paths that resolve outside current directory
    try:
        normalized = os.path.normpath(path)
        if normalized.startswith('..') or normalized.startswith('/'):
            return False
    except Exception:
        return False
    return True

def validate_image_mapping_key(key: str) -> bool:
    """Validate image mapping key format.

    Args:
        key: The image mapping key to validate.

    Returns:
        True if valid, False otherwise.
    """
    if not key or len(key) > 100:
        return False
    # Should be alphanumeric with hyphens/underscores
    pattern = r'^[a-zA-Z0-9][a-zA-Z0-9_-]*$'
    return bool(re.match(pattern, key))

def validate_image_mapping_value(value: str) -> bool:
    """Validate image mapping value format.

    Args:
        value: The image mapping value to validate.

    Returns:
        True if valid, False otherwise.
    """
    if not value or len(value) > 100:
        return False
    # Should be alphanumeric with underscores
    pattern = r'^[a-zA-Z0-9_]+$'
    return bool(re.match(pattern, value))

def validate_container_name(name: str) -> bool:
    """Validate Kubernetes container name.

    Args:
        name: The container name to validate.

    Returns:
        True if valid, False otherwise.
    """
    if not name or len(name) > 253:
        return False
    # DNS-1123 subdomain: lowercase alphanumeric, -, .
    pattern = r'^[a-z0-9]([-a-z0-9]*[a-z0-9])?(\.[a-z0-9]([-a-z0-9]*[a-z0-9])?)*$'
    return bool(re.match(pattern, name))

def validate_uid_gid(value: str) -> bool:
    """Validate UID/GID value.

    Args:
        value: The UID or GID to validate.

    Returns:
        True if valid integer >= 0, False otherwise.
    """
    try:
        num = int(value)
        return 0 <= num <= 2147483647  # Max int32
    except (ValueError, TypeError):
        return False

def validate_onboard_config(config: Dict[str, Any], onboard_type: str) -> None:
    """Validate onboard configuration against JSON schema.

    Args:
        config: The configuration dictionary to validate.
        onboard_type: The type of onboarding ('olm' or 'helm').

    Raises:
        jsonschema.ValidationError: If the config doesn't match the schema.
        ValueError: If required fields for the onboard type are missing.
    """
    # Validate against JSON schema
    try:
        jsonschema.validate(instance=config, schema=ONBOARD_REQUEST_SCHEMA)
    except jsonschema.ValidationError as e:
        # Provide more user-friendly error message
        error_path = " -> ".join(str(p) for p in e.path) if e.path else "root"
        raise jsonschema.ValidationError(
            f"Schema validation failed at {error_path}: {e.message}"
        )

    # Additional validation for type-specific required fields
    if config.get("components"):
        for component in config["components"]:
            if onboard_type == "olm":
                missing_fields = []
                if not component.get("bundle-repo"):
                    missing_fields.append("bundle-repo")
                if not component.get("bundle-version"):
                    missing_fields.append("bundle-version")

                if missing_fields:
                    raise ValueError(
                        f"OLM component '{component.get('name')}' is missing required fields: {', '.join(missing_fields)}"
                    )

            elif onboard_type == "helm":
                missing_fields = []
                if not component.get("chart-repo"):
                    missing_fields.append("chart-repo")
                if not component.get("chart-name"):
                    missing_fields.append("chart-name")
                if not component.get("chart-version"):
                    missing_fields.append("chart-version")

                if missing_fields:
                    raise ValueError(
                        f"Helm component '{component.get('name')}' is missing required fields: {', '.join(missing_fields)}"
                    )

def prompt_user(
    prompt: str,
    default: Optional[str] = None,
    required: bool = False,
    example: Optional[str] = None,
    validator: Optional[Callable[[str], bool]] = None,
    validation_error_msg: Optional[str] = None
) -> Optional[str]:
    """Prompt the user for input, with optional validation.

    Args:
        prompt: The prompt message to display.
        default: Default value if user presses Enter.
        required: If True, user must provide a value.
        example: Example value to show in prompt.
        validator: Optional validation function that returns True if input is valid.
        validation_error_msg: Custom error message when validation fails.

    Returns:
        The validated user input, or None if not required and user skipped.
    """
    while True:
        example_text = f" (e.g., {example})" if example else ""
        default_text = f"[default: {default}]" if default else "[required]"
        user_input = input(f"{prompt}{example_text} {default_text}: ").strip()

        # Handle empty input
        if not user_input:
            if default is not None:
                # Validate default value if validator provided
                if validator and not validator(default):
                    print(f"⚠️ Default value '{default}' is invalid. Please enter a valid value.\n")
                    continue

                return default

            elif required:
                print("⚠️ This field is required. Please provide a value.\n")
                continue

            else:
                return None

        # Validate input if validator provided
        if validator and not validator(user_input):
            if validation_error_msg:
                print(f"❌ {validation_error_msg}\n")
            else:
                print(f"❌ Invalid input: '{user_input}'. Please try again.\n")

            continue

        return user_input

def display_operator_list(operators: List[Dict[str, Any]]) -> None:
    """Display a summary of collected operators.

    Args:
        operators: List of operator configurations.
    """
    if not operators:
        print("  (no operators added yet)")
        return

    for idx, op in enumerate(operators, 1):
        print(f"  {idx}. {op.get('name', 'unnamed')}")
        print(f"     Bundle: {op.get('bundle-path', 'N/A')}")
        print(f"     Images: {len(op.get('image-mappings', {}))} mapping(s)")
        if op.get('webhook-paths'):
            print(f"     Webhooks: {len(op['webhook-paths'])}")

def collect_single_operator() -> Dict[str, Any]:
    """Collect a single OLM operator configuration.

    Returns:
        Operator configuration dictionary.
    """
    name = prompt_user(
        "Enter the operator name",
        required=True,
        validator=validate_container_name,
        validation_error_msg="Operator name must be a valid Kubernetes name (lowercase alphanumeric with hyphens)"
    )
    bundle_path = prompt_user(
        "Enter the bundle path (relative to the repo)",
        required=True,
        example="bundles/manifests/",
        validator=validate_relative_path,
        validation_error_msg="Path must be relative and not contain path traversal (..)"
    )
    image_mappings = collect_image_mappings()
    exclusions = collect_exclusions_or_inclusions("exclusions", get_exclusion_options())
    inclusions = collect_exclusions_or_inclusions("inclusions", get_inclusion_options())
    escape_template_variables = collect_exclusions_or_inclusions("escape-template-variables", get_escaped_template_variables())
    security_context_constraints = collect_security_context_constraints()
    webhook_paths = collect_webhook_paths()

    if not bundle_path.endswith("/"):
        bundle_path += "/"

    return {
        "name": name,
        "bundle-path": bundle_path,
        "escape-template-variables": escape_template_variables if escape_template_variables else [],
        "exclusions": exclusions if exclusions else [],
        "image-mappings": image_mappings,
        "inclusions": inclusions if inclusions else [],
        "security-context-constraints": security_context_constraints if security_context_constraints else [],
        "webhook-paths": webhook_paths
    }

def collect_olm_operators() -> List[Dict[str, Any]]:
    """Collect OLM operator configurations interactively with improved UX.

    Returns:
        List of operator configuration dictionaries.
    """
    expected_count_str = prompt_user(
        "How many operators do you expect to add?",
        default="1"
    )
    try:
        expected_count = int(expected_count_str)
    except (ValueError, TypeError):
        expected_count = 1

    operators = []
    operator_num = 1

    while True:
        # Show progress
        if expected_count > 1:
            print(f"\n--- Operator {operator_num} of {expected_count} ---")
        else:
            print(f"\n--- Operator {operator_num} ---")

        # Collect operator
        operator = collect_single_operator()
        operators.append(operator)

        # Show what was added
        print(f"\n✓ Added: {operator['name']}")
        print(f"  Bundle: {operator['bundle-path']}")
        print(f"  Images: {len(operator['image-mappings'])} mapping(s)")

        # Show summary
        print(f"\n📋 Operators: {len(operators)} added")
        display_operator_list(operators)

        # Ask what to do next
        if operator_num >= expected_count:
            action = prompt_user(
                "\nContinue? (yes/add/cancel)",
                default="yes"
            )
        else:
            action = prompt_user(
                "\nContinue? (yes/skip/cancel)",
                default="yes"
            )

        if not action:
            action = "yes"

        action = action.lower().strip()

        if action in ["yes", "y", ""]:
            if operator_num >= expected_count:
                # Finished expected count
                break
            else:
                # Continue to next expected operator
                operator_num += 1
                continue

        elif action in ["add", "a"]:
            # Add another beyond expected count
            operator_num += 1
            continue

        elif action in ["skip", "s"]:
            # Skip remaining expected operators
            break

        elif action in ["cancel", "c", "no", "n"]:
            # Cancel and return what we have
            if operators:
                confirm = prompt_user(
                    f"Cancel? You will lose {len(operators)} operator(s). Confirm (yes/no)",
                    default="no"
                )
                if confirm and confirm.lower() == "yes":
                    return []
            break

        else:
            print(f"❌ Unknown option '{action}'. Please choose yes/add/cancel")
            continue

    return operators

def collect_toggle_setting() -> str:
    """Prompt whether the component should be toggleable or always on.

    Returns:
        Either "toggle" or "always".
    """
    question = [
        inquirer.List(
            "needs_toggle_or_always",
            message="Should this component be toggleable or always on?",
            choices=["toggle", "always"],
        )
    ]

    answer = inquirer.prompt(question)
    return answer["needs_toggle_or_always"]

def display_chart_list(charts: List[Dict[str, Any]]) -> None:
    """Display a summary of collected Helm charts.

    Args:
        charts: List of Helm chart configurations.
    """
    if not charts:
        print("  (no charts added yet)")
        return

    for idx, chart in enumerate(charts, 1):
        print(f"  {idx}. {chart.get('name', 'unnamed')}")
        print(f"     Path: {chart.get('chart-path', 'N/A')}")
        print(f"     Images: {len(chart.get('image-mappings', {}))} mapping(s)")
        print(f"     Auto-install: {chart.get('auto-install-for-all-clusters', False)}")

def collect_single_chart() -> Dict[str, Any]:
    """Collect a single Helm chart configuration.

    Returns:
        Helm chart configuration dictionary.
    """
    name = prompt_user(
        "Enter the chart name",
        required=True,
        validator=validate_container_name,
        validation_error_msg="Chart name must be a valid Kubernetes name (lowercase alphanumeric with hyphens)"
    )
    chart_path = prompt_user(
        "Enter the chart path (relative to the repo)",
        required=True,
        validator=validate_relative_path,
        validation_error_msg="Path must be relative and not contain path traversal (..)"
    )
    always_or_toggle = collect_toggle_setting()
    image_mappings = collect_image_mappings()
    exclusions = collect_exclusions_or_inclusions("exclusions", get_exclusion_options())
    inclusions = collect_exclusions_or_inclusions("inclusions", get_inclusion_options())
    skip_rbac = collect_rbac_skip()
    update_chart_version = collect_update_chart_version()
    escape_template_variables = collect_exclusions_or_inclusions("escape-template-variables", get_escaped_template_variables())
    auto_install = collect_auto_install()
    security_context_constraints = collect_security_context_constraints()

    if not chart_path.endswith("/"):
        chart_path += "/"

    return {
        "always-or-toggle": always_or_toggle,
        "auto-install-for-all-clusters": auto_install,
        "chart-path": chart_path,
        "escape-template-variables": escape_template_variables if escape_template_variables else [],
        "exclusions": exclusions if exclusions else [],
        "image-mappings": image_mappings,
        "inclusions": inclusions if inclusions else [],
        "name": name,
        "security-context-constraints": security_context_constraints if security_context_constraints else [],
        "skip-rbac-overrides": skip_rbac,
        "update-chart-version": update_chart_version,
    }

def collect_helm_charts() -> List[Dict[str, Any]]:
    """Collect Helm chart configurations interactively with improved UX.

    Returns:
        List of Helm chart configuration dictionaries.
    """
    expected_count_str = prompt_user(
        "How many Helm charts do you expect to add?",
        default="1"
    )
    try:
        expected_count = int(expected_count_str)
    except (ValueError, TypeError):
        expected_count = 1

    charts = []
    chart_num = 1

    while True:
        # Show progress
        if expected_count > 1:
            print(f"\n--- Helm Chart {chart_num} of {expected_count} ---")
        else:
            print(f"\n--- Helm Chart {chart_num} ---")

        # Collect chart
        chart = collect_single_chart()
        charts.append(chart)

        # Show what was added
        print(f"\n✓ Added: {chart['name']}")
        print(f"  Path: {chart['chart-path']}")
        print(f"  Images: {len(chart['image-mappings'])} mapping(s)")
        print(f"  Auto-install: {chart['auto-install-for-all-clusters']}")

        # Show summary
        print(f"\n📋 Charts: {len(charts)} added")
        display_chart_list(charts)

        # Ask what to do next
        if chart_num >= expected_count:
            action = prompt_user(
                "\nContinue? (yes/add/cancel)",
                default="yes"
            )
        else:
            action = prompt_user(
                "\nContinue? (yes/skip/cancel)",
                default="yes"
            )

        if not action:
            action = "yes"

        action = action.lower().strip()

        if action in ["yes", "y", ""]:
            if chart_num >= expected_count:
                # Finished expected count
                break
            else:
                # Continue to next expected chart
                chart_num += 1
                continue

        elif action in ["add", "a"]:
            # Add another beyond expected count
            chart_num += 1
            continue

        elif action in ["skip", "s"]:
            # Skip remaining expected charts
            break

        elif action in ["cancel", "c", "no", "n"]:
            # Cancel and return what we have
            if charts:
                confirm = prompt_user(
                    f"Cancel? You will lose {len(charts)} chart(s). Confirm (yes/no)",
                    default="no"
                )
                if confirm and confirm.lower() == "yes":
                    return []
            break

        else:
            print(f"❌ Unknown option '{action}'. Please choose yes/add/cancel")
            continue

    return charts

def collect_auto_install() -> bool:
    """Prompt whether the component should be automatically installed on all clusters.

    Returns:
        True if component should be auto-installed, False otherwise.
    """
    question = [
        inquirer.Confirm(
            "needs_auto_install",
            message="Should this component be automatically installed on all clusters?",
            default=True
        )
    ]

    answer = inquirer.prompt(question)
    return answer["needs_auto_install"]

def collect_image_mappings() -> Dict[str, str]:
    """Collect image mappings interactively.

    Returns:
        Dictionary mapping image keys to image values.
    """
    while True:
        print("Enter image mappings (format: key: value). Press Enter with no input to finish:")
        image_mappings = {}

        while True:
            image_input = input("Image mapping (e.g., my-image: my_image): ").strip()
            if not image_input:
                break

            if ":" not in image_input:
                print("❌ Invalid format. Please enter in 'key:value' format.\n")
                continue

            key, value = image_input.split(":", 1)
            key = key.strip()
            value = value.strip()

            # Validate key
            if not validate_image_mapping_key(key):
                print(f"❌ Invalid key '{key}'. Must be alphanumeric with hyphens/underscores.\n")
                continue

            # Validate value
            if not validate_image_mapping_value(value):
                print(f"❌ Invalid value '{value}'. Must be alphanumeric with underscores.\n")
                continue

            image_mappings[key] = value
            print(f"✓ Added mapping: {key} -> {value}")

        if image_mappings:
            return image_mappings

        else:
            print("⚠️ Image mappings are required. Please enter at least one image mapping.\n")

def collect_exclusions_or_inclusions(type_name: str, options: List[str]) -> List[str]:
    """Optionally collect exclusions or inclusions interactively.

    Args:
        type_name: The name of the setting type (e.g., "exclusions", "inclusions").
        options: List of available options to choose from.

    Returns:
        List of selected options, or empty list if none selected.
    """
    confirm_prompt = [
        inquirer.Confirm(
            "needs_global_settings",
            message=f"Does this component require global {type_name} settings?",
            default=False
        )
    ]

    confirm_answer = inquirer.prompt(confirm_prompt)    
    if not confirm_answer['needs_global_settings']:
        return []

    selection_prompt = [
        inquirer.Checkbox(
            type_name,
            message=f"Select {type_name} (press Space to select, Enter to finish):",
            choices=options,
        )
    ]

    selection_answers = inquirer.prompt(selection_prompt)
    return selection_answers[type_name]

def collect_security_context_constraints() -> List[Dict[str, Any]]:
    """Optionally collect security context constraints interactively.

    Returns:
        List of security context constraint configurations for workloads.
    """
    wants_scc_question = [
        inquirer.Confirm(
            "requires_scc",
            message="Does this component require specific security context constraints?",
            default=False
        )
    ]

    answer = inquirer.prompt(wants_scc_question)    
    if not answer['requires_scc']:
        return []

    print("Enter security context constraints for specific workloads (select 'Done' to finish):")
    constraints = []

    # Add 'Done' option to the resource kinds
    resource_kind_choices = RESOURCE_KINDS + ["Done"]

    while True:
        kind_question = [
            inquirer.List(
                "kind",
                message="Select the kind of Kubernetes resource",
                choices=resource_kind_choices
            )
        ]
        kind_answer = inquirer.prompt(kind_question)
        kind = kind_answer["kind"]

        if kind == "Done":
            break

        # Step 2: Input the name of kind of resource.
        name = prompt_user(
            f"Enter the name of the {kind} resource (e.g, discovery-operator)",
            required=True,
            validator=validate_container_name,
            validation_error_msg="Resource name must be a valid Kubernetes name (lowercase alphanumeric with hyphens)"
        )

        print(f"\n--- Pod-level security context for {name} ---")

        # Collect basic pod security settings
        questions = [
            inquirer.Confirm("runAsNonRoot", message="Enable runAsNonRoot?", default=True),
        ]
        answers = inquirer.prompt(questions)

        pod_context = {
            "runAsNonRoot": answers["runAsNonRoot"],
        }

        # Optional: runAsUser (UID)
        run_as_user = prompt_user(
            "Specify runAsUser (UID, press Enter to skip)",
            required=False,
            validator=validate_uid_gid,
            validation_error_msg="UID must be a non-negative integer"
        )
        if run_as_user:
            pod_context["runAsUser"] = int(run_as_user)

        # Optional: runAsGroup (GID)
        run_as_group = prompt_user(
            "Specify runAsGroup (GID, press Enter to skip)",
            required=False,
            validator=validate_uid_gid,
            validation_error_msg="GID must be a non-negative integer"
        )
        if run_as_group:
            pod_context["runAsGroup"] = int(run_as_group)

        # Optional: fsGroup (GID for volumes)
        fs_group = prompt_user(
            "Specify fsGroup (GID for volumes, press Enter to skip)",
            required=False,
            validator=validate_uid_gid,
            validation_error_msg="fsGroup must be a non-negative integer"
        )
        if fs_group:
            pod_context["fsGroup"] = int(fs_group)

            # If fsGroup is set, ask about fsGroupChangePolicy
            policy_question = [
                inquirer.List(
                    "fsGroupChangePolicy",
                    message="Select fsGroupChangePolicy",
                    choices=FSGROUP_CHANGE_POLICIES,
                    default="OnRootMismatch"
                )
            ]
            policy_answer = inquirer.prompt(policy_question)
            pod_context["fsGroupChangePolicy"] = policy_answer["fsGroupChangePolicy"]

        # Optional: supplementalGroups (list of GIDs)
        print("\nSupplemental Groups (additional GIDs):")
        supplemental_groups = []
        while True:
            gid = prompt_user(
                "Add supplemental group GID (press Enter to finish)",
                required=False,
                validator=validate_uid_gid,
                validation_error_msg="GID must be a non-negative integer"
            )
            if not gid:
                break
            supplemental_groups.append(int(gid))
            print(f"✓ Added GID: {gid}")

        if supplemental_groups:
            pod_context["supplementalGroups"] = supplemental_groups

        # Optional: SELinux options
        selinux_question = [
            inquirer.Confirm(
                "configure_selinux",
                message="Configure SELinux options?",
                default=False
            )
        ]
        selinux_answer = inquirer.prompt(selinux_question)

        if selinux_answer["configure_selinux"]:
            print("\nSELinux Options:")
            selinux_level = prompt_user("SELinux level (e.g., s0:c123,c456)", required=False)
            selinux_role = prompt_user("SELinux role (e.g., object_r)", required=False)
            selinux_type = prompt_user("SELinux type (e.g., svirt_sandbox_file_t)", required=False)
            selinux_user = prompt_user("SELinux user (e.g., system_u)", required=False)

            selinux_options = {}
            if selinux_level:
                selinux_options["level"] = selinux_level
            if selinux_role:
                selinux_options["role"] = selinux_role
            if selinux_type:
                selinux_options["type"] = selinux_type
            if selinux_user:
                selinux_options["user"] = selinux_user

            if selinux_options:
                pod_context["seLinuxOptions"] = selinux_options

        # Step 4: Select container level security context 
        print(f"\n--- Container-level security context for {name} ---")
        containers = []
        while True:
            container_name = prompt_user(
                "Enter container name (press Enter to finish):",
                required=False,
                validator=validate_container_name,
                validation_error_msg="Container name must be a valid Kubernetes name (lowercase alphanumeric with hyphens)"
            )
            if not container_name:
                break

            questions = [
                inquirer.Confirm("readOnlyRootFilesystem", message="Enable readOnlyRootFilesystem?", default=True),
                inquirer.Confirm("runAsNonRoot", message="Enable runAsNonRoot?", default=True),
                inquirer.Confirm("allowPrivilegeEscalation", message="Allow privilege escalation?", default=False),
                inquirer.Confirm("privileged", message="Run as privileged?", default=False),
                inquirer.List("seccompType", message="Select a seccompProfile type", choices=SECCOMP_PROFILE_TYPES, default="RuntimeDefault"),
            ]

            answers = inquirer.prompt(questions)
            seccomp_profile = {"type": answers["seccompType"]}
            if answers["seccompType"] == "Localhost":
                localhost_profile = prompt_user("Enter the localhostProfile path", required=True, example="profiles/my-seccomp.json")
                seccomp_profile["localhostProfile"] = localhost_profile

            container_context = {
                "name": container_name,
                "readOnlyRootFilesystem": answers["readOnlyRootFilesystem"],
                "runAsNonRoot": answers["runAsNonRoot"],
                "allowPrivilegeEscalation": answers["allowPrivilegeEscalation"],
                "privileged": answers["privileged"],
                "seccompProfile": seccomp_profile,
            }

            # Optional: Container-level runAsUser (overrides pod-level)
            container_run_as_user = prompt_user(
                f"Specify runAsUser for {container_name} (UID, press Enter to skip/use pod-level)",
                required=False,
                validator=validate_uid_gid,
                validation_error_msg="UID must be a non-negative integer"
            )
            if container_run_as_user:
                container_context["runAsUser"] = int(container_run_as_user)

            # Optional: Container-level runAsGroup (overrides pod-level)
            container_run_as_group = prompt_user(
                f"Specify runAsGroup for {container_name} (GID, press Enter to skip/use pod-level)",
                required=False,
                validator=validate_uid_gid,
                validation_error_msg="GID must be a non-negative integer"
            )
            if container_run_as_group:
                container_context["runAsGroup"] = int(container_run_as_group)

            containers.append(container_context)

        constraints.append({
            "kind": kind,
            "name": name,
            **pod_context,
            "containers": containers
        })
    
    return constraints

def collect_webhook_paths() -> List[str]:
    """Optionally collect webhook paths interactively.

    Returns:
        List of webhook configuration file paths, or empty list if none.
    """
    wants_webhook_question = [
        inquirer.Confirm(
            "requires_webhook",
            message="Does this component require a webhook?",
            default=False
        )
    ]
    answer = inquirer.prompt(wants_webhook_question)

    if answer['requires_webhook']:
        paths = []
        while True:
            path = prompt_user(
                f"Enter path to webhook config (relative to component's repo root, press Enter to finish)",
                required=False
            )
            
            if not path:
                break
            paths.append(path)
        return paths

    else:
        return []

def collect_rbac_skip() -> bool:
    """Optionally collect RBAC skip setting interactively.

    Returns:
        True if RBAC overrides are needed, False otherwise.
    """
    question = [
        inquirer.Confirm(
            "needs_rbac_settings",
            message=f"Does this component require RBAC overrides?",
            default=True
        )
    ]

    answer = inquirer.prompt(question)
    return answer["needs_rbac_settings"]

def collect_update_chart_version() -> bool:
    """Prompt whether the chart version should be automatically updated.

    Returns:
        True if chart version should be auto-updated, False otherwise.
    """
    question = [
        inquirer.Confirm(
            "needs_chart_version_update",
            message="Should the chart version be automatically updated?",
            default=True
        )
    ]

    answer = inquirer.prompt(question)
    return answer["needs_chart_version_update"]

def collect_tech_preview_status() -> str:
    """Prompt for component status (dev-preview, tech-preview, or GA).

    Returns:
        The selected component status.
    """
    question = [
        inquirer.List(
            "needs_component_status",
            message="What is the component status?",
            choices=COMPONENT_STATUSES,
        )
    ]

    answer = inquirer.prompt(question)
    return answer["needs_component_status"]

def get_exclusion_options() -> List[str]:
    """Get the list of available exclusion options.

    Returns:
        List of available exclusion option names.
    """
    return EXCLUSION_OPTIONS

def get_inclusion_options() -> List[str]:
    """Get the list of available inclusion options.

    Returns:
        List of available inclusion option names.
    """
    return INCLUSION_OPTIONS

def get_escaped_template_variables() -> List[str]:
    """Get the list of template variables that should be escaped.

    Returns:
        List of template variable names that need escaping.
    """
    return ESCAPED_TEMPLATE_VARIABLES

def display_summary(config: Dict[str, Any]) -> None:
    """Display a summary of the configuration that will be saved.

    Args:
        config: The configuration dictionary to display.
    """
    print("\n" + "=" * 60)
    print("📋 SUMMARY OF ONBOARD REQUEST")
    print("=" * 60)

    print(f"\nOnboard Type: {config.get('onboard-type', 'N/A')}")

    components = config.get('components', [])
    if components:
        for idx, component in enumerate(components, 1):
            print(f"\n--- Component #{idx} ---")
            print(f"Repository: {component.get('github-ref', 'N/A')}")
            print(f"Branch: {component.get('branch', 'N/A')}")
            print(f"Status: {component.get('status', 'N/A')}")

            if 'operators' in component:
                print(f"Operators: {len(component['operators'])}")
                for op in component['operators']:
                    print(f"  - {op.get('name', 'unnamed')}")
                    print(f"    Bundle Path: {op.get('bundle-path', 'N/A')}")
                    print(f"    Image Mappings: {len(op.get('image-mappings', {}))}")

            if 'charts' in component:
                print(f"Helm Charts: {len(component['charts'])}")
                for chart in component['charts']:
                    print(f"  - {chart.get('name', 'unnamed')}")
                    print(f"    Chart Path: {chart.get('chart-path', 'N/A')}")
                    print(f"    Auto-install: {chart.get('auto-install-for-all-clusters', False)}")
                    print(f"    Image Mappings: {len(chart.get('image-mappings', {}))}")

    print("\n" + "=" * 60)
    print("Full YAML Preview:")
    print("=" * 60)

    try:
        import yaml
        print(yaml.dump(config, default_flow_style=False, sort_keys=False))
    except ImportError:
        # Fallback to JSON if PyYAML not available
        print(json.dumps(config, indent=2))

    print("=" * 60 + "\n")

def validate_github_repo(org: str, repo: str) -> bool:
    """Validate that a GitHub repository exists and is accessible.

    Args:
        org: GitHub organization or username.
        repo: Repository name.

    Returns:
        True if the repository exists and is accessible, False otherwise.
    """
    url = f"https://api.github.com/repos/{org}/{repo}"

    try:
        req = urllib.request.Request(url)
        req.add_header('User-Agent', 'stolostron-onboarding-script')

        with urllib.request.urlopen(req, timeout=10) as response:
            return response.status == 200
    except urllib.error.HTTPError as e:
        if e.code == 404:
            print(f"⚠️  Repository {org}/{repo} not found on GitHub")
        elif e.code == 403:
            print(f"⚠️  Access forbidden to {org}/{repo} (may be private or rate limited)")
        else:
            print(f"⚠️  HTTP error {e.code} when checking {org}/{repo}")
        return False
    except urllib.error.URLError as e:
        print(f"⚠️  Network error when checking {org}/{repo}: {e.reason}")
        return False
    except Exception as e:
        print(f"⚠️  Unexpected error when checking {org}/{repo}: {e}")
        return False

def onboarding_new_component(config_file: str, onboarding_type: str, dry_run: bool = False) -> None:
    """Interactive process to onboard a new repository entry.

    Args:
        config_file: Path to the YAML configuration file to update.
        onboarding_type: Type of onboarding ("olm" or "helm").
        dry_run: If True, show what would be created without saving.

    Raises:
        KeyboardInterrupt: If user cancels with Ctrl+C.
        Exception: For other unexpected errors.
    """
    print("\n--- Add a New Repository Entry ---")

    # Load existing YAML with error handling
    try:
        config = utils.common.load_yaml(config_file)

    except FileNotFoundError:
        # File doesn't exist yet, start with empty config
        config = {}

    except Exception as e:
        print(f"❌ Error loading {config_file}: {e}")
        print("Starting with empty configuration...")
        config = {}

    if "onboard-type" not in config:
        config["onboard-type"] = onboarding_type

    # Step 2: Collect basic repository details
    org = prompt_user(
        "Enter the GitHub organization or username",
        required=True,
        default="stolostron",
        validator=validate_github_name,
        validation_error_msg="GitHub org/username must be alphanumeric with hyphens (max 39 chars)"
    )
    repo = prompt_user(
        "Enter the repository name",
        required=True,
        example="discovery",
        validator=validate_github_name,
        validation_error_msg="GitHub repo name must be alphanumeric with hyphens (max 39 chars)"
    )

    # Validate that the repository exists
    print(f"🔍 Validating repository {org}/{repo}...")
    if not validate_github_repo(org, repo):
        proceed = prompt_user(
            "Repository validation failed. Do you want to proceed anyway? (yes/no)",
            default="no"
        )
        if proceed and proceed.lower() != "yes":
            print("❌ Onboarding cancelled.")
            return

    branch = prompt_user(
        "Enter the branch name",
        default="main",
        validator=validate_branch_name,
        validation_error_msg="Branch name contains invalid characters or format"
    )
    github_ref = f"https://github.com/{org}/{repo}.git"
    status = collect_tech_preview_status()

    # Start building the component entry with onboard-type set globally
    component_entry = {
        "repo-name": repo,
        "github-ref": github_ref,
        "branch": branch,
        "status": status,
    }

    if onboarding_type == "olm":
        component_entry["operators"] = collect_olm_operators()
    else:
        component_entry["charts"] = collect_helm_charts()

    # Add new component entries to onboard-request config
    config["components"] = [component_entry]

    # Display summary of what will be saved
    display_summary(config)

    # Ask for confirmation before proceeding
    confirm = prompt_user(
        f"\nDo you want to save this configuration to {config_file}? (yes/no)",
        default="yes"
    )

    if not confirm or confirm.lower() != "yes":
        print("❌ Onboarding cancelled. No files were modified.")
        return

    # If dry-run mode, exit without saving
    if dry_run:
        print("\n🔍 DRY RUN MODE - No files were modified")
        print("Run without --dry-run to save this configuration")
        return

    # Check if file exists and warn before overwriting
    if os.path.exists(config_file):
        print(f"\n⚠️  Warning: {config_file} already exists and will be overwritten!")
        overwrite = prompt_user(
            "Do you want to overwrite the existing file? (yes/no)",
            default="no"
        )
        if overwrite and overwrite.lower() != "yes":
            print("❌ Onboarding cancelled. No files were modified.")
            return

    # Validate configuration against schema before saving
    try:
        print("\n🔍 Validating configuration schema...")
        validate_onboard_config(config, onboarding_type)
        print("✅ Schema validation passed")

    except jsonschema.ValidationError as e:
        print(f"\n❌ Schema validation failed: {e.message}")
        print("The generated configuration does not match the expected format.")
        sys.exit(1)

    except ValueError as e:
        print(f"\n❌ Validation failed: {e}")
        sys.exit(1)

    # Save the updated YAML with error handling (using temp file for atomicity)
    temp_path = None
    try:
        # Create temp file in same directory for atomic rename
        config_dir = os.path.dirname(config_file) or '.'
        temp_fd, temp_path = tempfile.mkstemp(
            dir=config_dir,
            prefix='.onboard-request.',
            suffix='.yaml.tmp'
        )
        os.close(temp_fd)  # Close file descriptor, we'll use the path

        # Write to temp file
        utils.common.save_yaml(temp_path, config)

        # Validate temp file can be read back and matches schema
        loaded_config = utils.common.load_yaml(temp_path)
        validate_onboard_config(loaded_config, onboarding_type)

        # Atomically move to final location
        shutil.move(temp_path, config_file)
        temp_path = None  # Successfully moved, no cleanup needed

        print(f"✅ Successfully added '{repo}' to {config_file}!")

    except PermissionError:
        print(f"❌ Permission denied: Cannot write to {config_file}")
        print("Check file permissions and try again.")
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)
        sys.exit(1)

    except Exception as e:
        print(f"❌ Error saving configuration to {config_file}: {e}")
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)
        sys.exit(1)

    # Display next steps based on onboarding type
    print(f"\n💡 Next steps:")
    print(f"   1. Review the generated {config_file}")

    if onboarding_type == "olm":
        print(f"   2. Run: make regenerate-charts-from-bundles CONFIG={config_file}")
    else:  # helm
        print(f"   2. Run: make regenerate-charts CONFIG={config_file}")

    print(f"   3. Review generated files with: git status && git diff")
    print(f"   4. Commit and create a PR")

def main() -> None:
    """Main entry point for the onboarding script.

    Prompts user for onboarding type and initiates the onboarding process.
    """
    try:
        parser = argparse.ArgumentParser(
            description="Interactive tool for onboarding new components to backplane-operator"
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview what would be created without saving any files"
        )
        parser.add_argument(
            "--config",
            default="onboard-request.yaml",
            help="Path to the config file to create (default: onboard-request.yaml)"
        )
        args = parser.parse_args()

        if args.dry_run:
            print("🔍 Running in DRY RUN mode - no files will be modified\n")

        question = [
            inquirer.List("type", message="What type of onboarding is this? (olm/helm)", choices=["olm", "helm"])
        ]
        answer = inquirer.prompt(question)

        # Handle case where user cancelled the prompt
        if not answer or "type" not in answer:
            print("\n❌ Onboarding cancelled.")
            sys.exit(0)

        onboarding_new_component(args.config, answer["type"], dry_run=args.dry_run)

    except KeyboardInterrupt:
        print("\n\n⚠️  Onboarding interrupted by user (Ctrl+C)")
        print("No files were modified.")
        sys.exit(130)  # Standard exit code for Ctrl+C

    except EOFError:
        print("\n\n❌ Unexpected end of input")
        sys.exit(1)

    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        print("\nIf this issue persists, please report it at:")
        print("https://github.com/stolostron/installer-dev-tools/issues")
        import traceback
        print("\nFull error trace:")
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()