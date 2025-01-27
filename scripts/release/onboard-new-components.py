#!/usr/bin/env python3
# Copyright (c) 2025 Red Hat, Inc.
# Copyright Contributors to the Open Cluster Management project
# Assumes: Python 3.6+

import utils.common
import inquirer

def prompt_user(prompt, default=None, required=False, example=None):
    """Prompt the user for input, with an optional default, example, and required flag."""
    while True:
        example_text = f" (e.g., {example})" if example else ""
        default_text = f"[default: {default}]" if default else "[required]"
        user_input = input(f"{prompt}{example_text} {default_text}: ").strip()
    
        # user_input = input(f"{prompt}{example} [{'default: ' + default if default else 'required'}]: ").strip()
        if user_input:
            return user_input
        elif default is not None:
            return default
        elif required:
            print("This field is required. Please provide a value.")
        else:
            return None

def collect_image_mappings():
    """Collect image mappings interactively."""
    image_mappings = {}
    print("Enter image mappings (key:value). Type 'done' when finished.")
    while True:
        image_input = input("Image mapping (e.g., key:value): ").strip()
        if image_input.lower() == "done":
            break
        if ":" in image_input:
            key, value = image_input.split(":", 1)
            image_mappings[key.strip()] = value.strip()
        else:
            print("Invalid format. Please enter in 'key:value' format.")
    return image_mappings

def collect_exclusions_or_inclusions(type_name, options):
    """Collect exclusions or inclusions interactively."""
    questions = [
        inquirer.Checkbox(
            f"{type_name.capitalize()}",
            message=f"Select {type_name} (space to select, enter to finish)",
            choices=options,
        )
    ]

    answers = inquirer.prompt(questions)
    return answers.get(f"{type_name.capitalize()}", [])

def onboarding_new_component(config_file, onboarding_type):
    """Interactive process to onboard a new repository entry."""
    print("\n--- Add a New Repository Entry ---")

    # Load existing YAML
    config = utils.common.load_yaml(config_file)

    # Step 2: Collect basic repository details
    repo_name = prompt_user("Enter the repository name", required=True)
    github_ref = prompt_user("Enter the GitHub repository URL", required=True, example="https://github.com/org/repo.git")
    branch = prompt_user("Enter the branch name", default="main")

    if onboarding_type == "olm":
        # Collect OLM bundle details
        operators = []
        while True:
            print("\n--- Add an OLM Operator ---")
            name = prompt_user("Enter the operator name", required=True)
            bundle_path = prompt_user("Enter the bundle path (relative to the repo)", required=True, example="bundles/manifests/")
            image_mappings = collect_image_mappings()
            exclusions = collect_exclusions_or_inclusions("exclusions", ["readOnlyRootFilesystem"])
            
            operators.append({
                "name": name,
                "bundlePath": bundle_path,
                "imageMappings": image_mappings,
                "exclusions": exclusions if exclusions else [],
            })

            add_another = prompt_user("Would you like to add another operator? (yes/no)", default="no")
            if add_another.lower() != "yes":
                break

        # Add to config
        config.append({
            "repo_name": repo_name,
            "github_ref": github_ref,
            "branch": branch,
            "operators": operators,
        })

    elif onboarding_type == "helm":
        # Collect Helm chart details
        charts = []
        while True:
            print("\n--- Add a Helm Chart ---")
            name = prompt_user("Enter the chart name", required=True)
            chart_path = prompt_user("Enter the chart path (relative to the repo)", required=True)
            always_or_toggle = prompt_user("Is this chart 'always' or 'toggle'?", default="toggle")
            image_mappings = collect_image_mappings()
            inclusions = collect_exclusions_or_inclusions("inclusions", ["pullSecretOverride"])
            skip_rbac = prompt_user("Skip RBAC overrides? (true/false)", default="true").lower() == "true"
            update_chart_version = prompt_user("Update chart version? (true/false)", default="true").lower() == "true"
            escape_template_variables = collect_exclusions_or_inclusions("escape-template-variables", ["CLUSTER_NAME", "HUB_KUBECONFIG", "INSTALL_NAMESPACE"])
            auto_install = prompt_user("Auto-install for all clusters? (true/false)", default="true").lower() == "true"

            charts.append({
                "name": name,
                "chart-path": chart_path,
                "always-or-toggle": always_or_toggle,
                "imageMappings": image_mappings,
                "inclusions": inclusions if inclusions else [],
                "skipRBACOverrides": skip_rbac,
                "updateChartVersion": update_chart_version,
                "escape-template-variables": escape_template_variables if escape_template_variables else None,
                "auto-install-for-all-clusters": auto_install,
            })

            add_another = prompt_user("Would you like to add another chart? (yes/no)", default="no")
            if add_another.lower() != "yes":
                break

        # Add to config
        config.append({
            "repo_name": repo_name,
            "github_ref": github_ref,
            "branch": branch,
            "charts": charts,
        })

    # Save the updated YAML
    utils.common.save_yaml(config_file, config)
    print(f"\nSuccessfully added '{repo_name}' to the YAML config!")

# Run the onboarding process
if __name__ == "__main__":
    # Step 1: Choose onboarding type
    onboarding_type = prompt_user("What type of onboarding is this? (olm/helm)", required=True).lower()

    if onboarding_type not in ["olm", "helm"]:
        print("Invalid choice. Please enter 'olm' or 'helm'.")
        exit(1)

    config_file = (
        "hack/bundle-automation/config.yaml"
        if onboarding_type == "olm"
        else "hack/bundle-automation/charts-config.yaml"
    )
    onboarding_new_component(config_file, onboarding_type)
