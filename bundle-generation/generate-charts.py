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
import common

from git import Repo, exc
from packaging import version

from validate_csv import *

# Configure logging with coloredlogs
coloredlogs.install(level='DEBUG')  # Set the logging level as needed

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
    addonTemplates = common.find_templates_of_type(helmChart, 'AddOnTemplate')
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
            logging.warning(f"Skipping unsupported kind '{kind}' in {filePath}. No updates applied")
            continue # Skip unsupported kinds

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


# Copy chart-templates to a new helmchart directory
def copyHelmChart(destinationChartPath, repo, chart, chartVersion):
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

    specificValues = os.path.join(os.path.dirname(os.path.realpath(__file__)), "chart-values", chart['name'], "values.yaml")
    if os.path.exists(specificValues):
        logging.info(f"Using specific values.yaml for chart '{chartName}' from: {specificValues}")
        shutil.copyfile(specificValues, os.path.join(chartPath, "values.yaml"))
    else:
        logging.warning(f"No specific values.yaml found for chart '{chartName}'")

    logging.info(f"Running 'helm template' for chart: '{chartName}'")
    helmTemplateOutput = subprocess.getoutput(['helm template '+ chartPath])

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
    parser.add_argument("--destination", dest="destination", type=str, required=False, help="Destination directory of the created helm chart")
    parser.add_argument("--skipOverrides", dest="skipOverrides", type=bool, help="If true, overrides such as helm flow control will not be applied")
    parser.add_argument("--lint", dest="lint", action='store_true', help="If true, bundles will only be linted to ensure they can be transformed successfully. Default is False.")
    parser.set_defaults(skipOverrides=False)
    parser.set_defaults(lint=False)

    args = parser.parse_args()
    skipOverrides = args.skipOverrides
    destination = args.destination
    lint = args.lint

    if lint == False and not destination:
        logging.critical("Destination directory is required when not linting.")
        exit(1)

    logging.basicConfig(level=logging.DEBUG)

    # Config.yaml holds the configurations for Operator bundle locations to be used
    configYaml = os.path.join(os.path.dirname(os.path.realpath(__file__)),"charts-config.yaml")
    with open(configYaml, 'r') as f:
        config = yaml.safe_load(f)

    if not config:
        logging.critical("No charts listed in config to be moved!")
        exit(0)

    # Loop through each repo in the config.yaml
    for repo in config:
        logging.info("Cloning: %s", repo["repo_name"])
        repo_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), "tmp/" + repo["repo_name"]) # Path to clone repo to
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
            addCRDs(repo["repo_name"], chart, destination)

            logging.info(f"Creating helm chart: '{chart_name}'")
            always_or_toggle = chart['always-or-toggle']
            destinationChartPath = os.path.join(destination, "charts", always_or_toggle, chart['name'])

            # Extract the chart version from the charts configuration, 
            # ensuring the version is derived from the repository branch when applicable.
            chartVersion = getChartVersion(chart['updateChartVersion'], repo)

            # Template Helm Chart Directory from 'chart-templates'
            logging.info(f"Templating helm chart '{chart_name}'")
            copyHelmChart(destinationChartPath, repo["repo_name"], chart, chartVersion)

            # Render the helm chart before updating the chart resources.
            if not renderChart(destinationChartPath):
                logging.error(f"Failed to render chart {destinationChartPath}")
            
            # Update the helm chart resources with additional overrides
            updateResources(destination, repo["repo_name"], chart)

            if not skipOverrides:
                logging.info("Adding Overrides (set --skipOverrides=true to skip) ...")
                image_mappings = chart.get("imageMappings", {})
                exclusions = chart.get("exclusions", [])
                inclusions = chart.get("inclusions", [])
                skip_rbac_overrides = chart.get("skipRBACOverrides", False)

                common.inject_requirements(destinationChartPath, chart_name, chart, image_mappings, skip_rbac_overrides, exclusions,
                                   inclusions, branch)
                logging.info("Overrides added.\n")

    logging.info("All repositories and operators processed successfully.")
    logging.info("Performing cleanup...")
    shutil.rmtree((os.path.join(os.path.dirname(os.path.realpath(__file__)), "tmp")), ignore_errors=True)

    logging.info("Cleanup completed.")
    logging.info("Script execution completed.")

if __name__ == "__main__":
   main()
