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

        if user_input:
            return user_input

        elif default is not None:
            return default

        elif required:
            print("⚠️ This field is required. Please provide a value.\n")

        else:
            return None

def collect_olm_operators():
    operators = []
    while True:
        print("\n--- Add an OLM Operator ---")
        name = prompt_user("Enter the operator name", required=True)
        bundle_path = prompt_user("Enter the bundle path (relative to the repo)", required=True, example="bundles/manifests/")
        image_mappings = collect_image_mappings()
        exclusions = collect_exclusions_or_inclusions("exclusions", get_exclusion_options())
        inclusions = collect_exclusions_or_inclusions("inclusions", get_inclusion_options())
        escape_template_variables = collect_exclusions_or_inclusions("escape-template-variables", get_escaped_template_variables())
        security_context_constraints = collect_security_context_constraints()
        webhook_paths = collect_webhook_paths()

        if not bundle_path.endswith("/"):
            bundle_path += "/"

        operators.append({
            "name": name,
            "bundlePath": bundle_path,
            "escape-template-variables": escape_template_variables if escape_template_variables else [],
            "exclusions": exclusions if exclusions else [],
            "imageMappings": image_mappings,
            "inclusions": inclusions if inclusions else [],
            "security-context-constraints": security_context_constraints if security_context_constraints else [],
            "webhook_paths": webhook_paths
        })

        add_another = prompt_user("\nWould you like to add another operator? (yes/no)", default="no")
        if add_another.lower() != "yes":
            break
    return operators

def collect_toggle_setting():
    """Prompt whether the component should be automatically installed on all clusters."""
    question = [
        inquirer.List(
            "needs_toggle_or_always",
            message="Should this component be toggleable or always on?",
            choices=["toggle", "always"],
        )
    ]

    answer = inquirer.prompt(question)
    return answer["needs_toggle_or_always"]

def collect_helm_charts():
    charts = []
    while True:
        print("\n--- Add a Helm Chart ---")
        name = prompt_user("Enter the chart name", required=True)
        chart_path = prompt_user("Enter the chart path (relative to the repo)", required=True)
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

        charts.append({
            "always-or-toggle": always_or_toggle,
            "auto-install-for-all-clusters": auto_install,
            "chart-path": chart_path,
            "escape-template-variables": escape_template_variables if escape_template_variables else [],
            "exclusions": exclusions if exclusions else [],
            "imageMappings": image_mappings,
            "inclusions": inclusions if inclusions else [],
            "name": name,
            "security-context-constraints": security_context_constraints if security_context_constraints else [],
            "skipRBACOverrides": skip_rbac,
            "updateChartVersion": update_chart_version,
        })

        add_another = prompt_user("\nWould you like to add another chart? (yes/no)", default="no")
        if add_another.lower() != "yes":
            break
    return charts

def collect_auto_install():
    """Prompt whether the component should be automatically installed on all clusters."""
    question = [
        inquirer.Confirm(
            "needs_auto_install",
            message="Should this component be automatically installed on all clusters?",
            default=True
        )
    ]

    answer = inquirer.prompt(question)
    return answer["needs_auto_install"]

def collect_image_mappings():
    """Collect image mappings interactively."""
    while True:
        print("Enter image mappings (format: key: value). Press Enter with no input to finish:")
        image_mappings = {}

        while True:
            image_input = input("Image mapping (e.g., my-image: my_image): ").strip()
            if not image_input:
                break

            if ":" in image_input:
                key, value = image_input.split(":", 1)
                image_mappings[key.strip()] = value.strip()
            else:
                print("❌ Invalid format. Please enter in 'key:value' format.\n")
        
        if image_mappings:
            return image_mappings

        else:
            print("⚠️ Image mappings are required. Please enter at least one image mapping.\n")

def collect_exclusions_or_inclusions(type_name, options):
    """Optionally collect exclusions or inclusions interactively."""
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

def collect_security_context_constraints():
    """Optionally collect security context constraints interactively."""
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

    resource_kinds = [
        "Deployment",
        "Job",
        "StatefulSet",
        "Done",
    ]
    
    while True:
        kind_question = [
            inquirer.List(
                "kind",
                message="Select the kind of Kubernetes resource",
                choices=resource_kinds
            )
        ]
        kind_answer = inquirer.prompt(kind_question)
        kind = kind_answer["kind"]

        if kind == "Done":
            break

        # Step 2: Input the name of kind of resource.
        name = prompt_user(f"Enter the name of the {kind} resource (e.g, discovery-operator)", required=True)

        print(f"\n--- Pod-level security context for {name} ---")
        questions = [
            inquirer.Confirm("runAsNonRoot", message="Enable runAsNonRoot?", default=True),
            # inquirer.Confirm("runAsUser", message="Allow privilege escalation?", default=False),
            # inquirer.Confirm("runAsGroup", message="Run as privileged?", default=False),
            # inquirer.Confirm("fsGroup", message="Not supported yet", default=False),
            # inquirer.Confirm("fsGroupChangePolicy", message="Not supported yet", default=False),
            # inquirer.Confirm("SELinux", message="Not supported yet", default=False),
            # inquirer.Confirm("supplementalGroups", message="Not supported yet", default=False),
            # inquirer.Confirm("supplementalGroupsPolicy", message="Not supported yet", default=False),
        ]
        answers = inquirer.prompt(questions)
        pod_context = {
            "runAsNonRoot": answers["runAsNonRoot"],
            # "runAsUser": answers["runAsUser"],
            # "runAsGroup": answers["runAsGroup"],
            # "fsGroup": answers["fsGroup"],
            # "fsGroupChangePolicy": answers["fsGroupChangePolicy"],
            # "SELinux": answers["SELinux"],
            # "supplementalGroups": answers["supplementalGroups"],
            # "supplementalGroupsPolicy": answers["supplementalGroupsPolicy"],
        }

        # Step 4: Select container level security context 
        print(f"\n--- Container-level security context for {name} ---")
        containers = []
        while True:
            container_name = prompt_user("Enter container name (press Enter to finish):", required=False)
            if not container_name:
                break

            questions = [
                inquirer.Confirm("readOnlyRootFilesystem", message="Enable readOnlyRootFilesystem?", default=True),
                inquirer.Confirm("runAsNonRoot", message="Enable runAsNonRoot?", default=True),
                inquirer.Confirm("allowPrivilegeEscalation", message="Allow privilege escalation?", default=False),
                inquirer.Confirm("privileged", message="Run as privileged?", default=False),
                inquirer.List("seccompType", message="Select a seccompProfile type", choices=["RuntimeDefault", "Unconfined", "Localhost"], default="RuntimeDefault"),
            ]

            answers = inquirer.prompt(questions)
            seccomp_profile = {"type": answers["seccompType"]}
            if answers["seccompType"] == "Localhost":
                localhost_profile = prompt_user("Enter the localhostProfile path", required=True, example="profiles/my-seccomp.json")
                seccomp_profile["localhostProfile"] = localhost_profile

            containers.append({
                "name": container_name,
                "readOnlyRootFilesystem": answers["readOnlyRootFilesystem"],
                "runAsNonRoot": answers["runAsNonRoot"],
                "allowPrivilegeEscalation": answers["allowPrivilegeEscalation"],
                "privileged": answers["privileged"],
                "seccompProfile": seccomp_profile,
            })

        constraints.append({
            "kind": kind,
            "name": name,
            **pod_context,
            "containers": containers
        })
    
    return constraints

def collect_webhook_paths():
    """Optionally collect webhook paths interactively."""
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

def collect_rbac_skip():
    """Optionally collect RBAC skip setting interactively."""
    question = [
        inquirer.Confirm(
            "needs_rbac_settings",
            message=f"Does this component require RBAC overrides?",
            default=True
        )
    ]

    answer = inquirer.prompt(question)
    return answer["needs_rbac_settings"]

def collect_update_chart_version():
    """Prompt whether the chart version should be automatically updated."""
    question = [
        inquirer.Confirm(
            "needs_chart_version_update",
            message="Should the chart version be automatically updated?",
            default=True
        )
    ]

    answer = inquirer.prompt(question)
    return answer["needs_chart_version_update"]

def collect_tech_preview_status():
    question = [
        inquirer.List(
            "needs_component_status",
            message="Should the chart version be automatically updated?",
            choices=["dev-preview", "tech-preview", "GA"],
        )
    ]

    answer = inquirer.prompt(question)
    return answer["needs_component_status"]

def get_exclusion_options():
    """_summary_

    Returns:
        _type_: _description_
    """
    return ["readOnlyRootFilesystem"]

def get_inclusion_options():
    """_summary_

    Returns:
        _type_: _description_
    """
    return ["pullSecretOverride"]

def get_escaped_template_variables():
    """_summary_

    Returns:
        _type_: _description_
    """
    return ["CLUSTER_NAME", "GITOPS_OPERATOR_IMAGE", "GITOPS_OPERATOR_NAMESPACE", "GITOPS_IMAGE",
        "GITOPS_NAMESPACE", "HUB_KUBECONFIG", "INSTALL_NAMESPACE", "REDIS_IMAGE", "RECONCILE_SCOPE"]

def onboarding_new_component(config_file, onboarding_type):
    """Interactive process to onboard a new repository entry."""
    print("\n--- Add a New Repository Entry ---")

    # Load existing YAML
    config = utils.common.load_yaml(config_file)
    if "onboard-type" not in config:
        config["onboard-type"] = onboarding_type

    # Step 2: Collect basic repository details
    org = prompt_user("Enter the GitHub organization or username", required=True, default="stolostron")
    repo = prompt_user("Enter the repository name", required=True, example="discovery")
    branch = prompt_user("Enter the branch name", default="main")
    github_ref = f"https://github.com/{org}/{repo}.git"
    status = collect_tech_preview_status()

    # Start building the component entry with onboard-type set globally
    component_entry = {
        "repo_name": repo,
        "github_ref": github_ref,
        "branch": branch,
        "status": status,
    }

    if onboarding_type == "olm":
        component_entry["operators"] = collect_olm_operators()
    else:
        component_entry["charts"] = collect_helm_charts()

    # Add new component entries to onboard-request config
    config["components"] = [component_entry]

    # Save the updated YAML
    utils.common.save_yaml(config_file, config)
    print("Successfully added '%s' to the YAML config!", repo)

def main():
    """_summary_
    """

    question = [
        inquirer.List("type", message="What type of onboarding is this? (olm/helm)", choices=["olm", "helm"])
    ]
    answer = inquirer.prompt(question)

    config_file = f"onboard-request.yaml"
    onboarding_new_component(config_file, answer["type"])

if __name__ == "__main__":
    main()