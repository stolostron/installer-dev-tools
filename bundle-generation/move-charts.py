#!/usr/bin/env python3
# Copyright (c) 2021 Red Hat, Inc.
# Copyright Contributors to the Open Cluster Management project
# Assumes: Python 3.6+

import argparse
import os
import shutil
import yaml
import logging
import subprocess
from git import Repo, exc

from validate_csv import *

# Copy chart-templates to a new helmchart directory
import os
import shutil
import logging

def copyHelmChart(destinationChartPath, repo, chart):
    chartName = chart['name']
    logging.info(f"Copying templates into new {chartName} chart directory ...")

    # Create main folder
    chartPath = os.path.join(os.path.dirname(os.path.realpath(__file__)), "tmp", repo, chart["chart-path"])
    if os.path.exists(destinationChartPath):
        logging.info(f"Removing existing directory at: {destinationChartPath}")
        shutil.rmtree(destinationChartPath)

    # Copy Chart.yaml, values.yaml, and templates dir
    chartTemplatesPath = os.path.join(chartPath, "templates/")
    destinationTemplateDir = os.path.join(destinationChartPath, "templates/")
    os.makedirs(destinationTemplateDir)
    logging.debug(f"Created destination template directory at: {destinationTemplateDir}")

    # Fetch template files
    logging.info(f"Copying template files from '{chartTemplatesPath}' to '{destinationTemplateDir}'")
    for file_name in os.listdir(chartTemplatesPath):
        # Construct full file path
        source = os.path.join(chartTemplatesPath, file_name)
        destination = os.path.join(destinationTemplateDir, file_name)

        # Copy only files
        if os.path.isfile(source):
            logging.debug(f"Copying file '{source}' to '{destination}'")
            shutil.copyfile(source, destination)
        else:
            logging.warning(f"Skipping non-file item: {source}")

    chartYamlPath = os.path.join(chartPath, "Chart.yaml")
    if not os.path.exists(chartYamlPath):
        logging.error(f"No Chart.yaml found for chart: '{chartName}'")
        return

    logging.info("Copying Chart.yaml to '%s'", os.path.join(destinationChartPath, "Chart.yaml"))
    shutil.copyfile(chartYamlPath, os.path.join(destinationChartPath, "Chart.yaml"))

    valuesYamlPath = os.path.join(chartPath, "values.yaml")
    if not os.path.exists(valuesYamlPath):
        logging.error(f"No values.yaml found for chart: '{chartName}'")
        return

    shutil.copyfile(valuesYamlPath, os.path.join(destinationChartPath, "values.yaml"))
    logging.info("Chart copied.\n")

def addCRDs(repo, chart, outputDir):
    if not 'chart-path' in chart:
        logging.critical("Could not validate chart path in given chart: " + chart)
        exit(1) 

    chartPath = os.path.join(os.path.dirname(os.path.realpath(__file__)), "tmp", repo, chart["chart-path"])
    if not os.path.exists(chartPath):
        logging.critical("Could not validate chartPath at given path: " + chartPath)
        exit(1)
    
    crdPath = os.path.join(chartPath, "crds")
    if not os.path.exists(crdPath):
        logging.info(f"No CRDs for repo: {repo}")
        return

    destinationPath = os.path.join(outputDir, "crds", chart['name'])
    if os.path.exists(destinationPath): # If path exists, remove and re-clone
        shutil.rmtree(destinationPath)
    os.makedirs(destinationPath)
    for filename in os.listdir(crdPath):
        if not filename.endswith(".yaml"): 
            continue
        filepath = os.path.join(crdPath, filename)
        with open(filepath, 'r') as f:
            resourceFile = yaml.safe_load(f)

        if resourceFile["kind"] == "CustomResourceDefinition":
            shutil.copyfile(filepath, os.path.join(destinationPath, filename))

def chartConfigAcceptable(chart):
    helmChart = chart["name"]
    if helmChart == "":
        logging.critical("Unable to generate helm chart without a name.")
        return False
    return True

def main():
    ## Initialize ArgParser
    parser = argparse.ArgumentParser()
    parser.add_argument("--destination", dest="destination", type=str, required=False, help="Destination directory of the created helm chart")

    args = parser.parse_args()
    destination = args.destination

    logging.basicConfig(level=logging.DEBUG)

    # Config.yaml holds the configurations for Operator bundle locations to be used
    configYaml = os.path.join(os.path.dirname(os.path.realpath(__file__)), "copy-config.yaml")
    with open(configYaml, 'r') as f:
        config = yaml.safe_load(f)

    # Loop through each repo in the config.yaml
    for repo in config:
        logging.info("Cloning: %s", repo["repo_name"])
        repo_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), "tmp/" + repo["repo_name"]) # Path to clone repo to
        if os.path.exists(repo_path): # If path exists, remove and re-clone
            shutil.rmtree(repo_path)

        repository = Repo.clone_from(repo["github_ref"], repo_path) # Clone repo to above path
        if 'branch' in repo:
            repository.git.checkout(repo['branch']) # If a branch is specified, checkout that branch

        # Loop through each operator in the repo identified by the config
        for chart in repo["charts"]:
            if not chartConfigAcceptable(chart):
                logging.critical("Unable to generate helm chart without configuration requirements.")
                exit(1)

            logging.info("Helm Chartifying -  %s!\n", chart["name"])

            logging.info("Adding CRDs -  %s!\n", chart["name"])
            # Copy over all CRDs to the destination directory
            addCRDs(repo["repo_name"], chart, destination)

            logging.info("Creating helm chart: '%s' ...", chart["name"])

            always_or_toggle = chart['always-or-toggle']
            destinationChartPath = os.path.join(destination, "charts", always_or_toggle, chart['name'])

            # Template Helm Chart Directory from 'chart-templates'
            logging.info("Templating helm chart '%s' ...", chart["name"])
            copyHelmChart(destinationChartPath, repo["repo_name"], chart)

    logging.info("All repositories and operators processed successfully.")
    logging.info("Performing cleanup...")
    shutil.rmtree((os.path.join(os.path.dirname(os.path.realpath(__file__)), "tmp")), ignore_errors=True)

    logging.info("Cleanup completed.")
    logging.info("Script execution completed.")

if __name__ == "__main__":
   main()
