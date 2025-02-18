#!/usr/bin/env python3
# Copyright (c) 2025 Red Hat, Inc.
# Copyright Contributors to the Open Cluster Management project
# Assumes: Python 3.6+

"""
Pipeline Manifest SHA Sync Script

This script is designed to automate the process of synchronizing repository SHA values
between a pipeline manifest (in JSON format) and a configuration YAML file.

It performs the following tasks:
1. Clones the specified pipeline repository from GitHub.
2. Fetches the latest manifest file from the repository's snapshots directory.
3. Reads the manifest and compares the SHA values for each repository
   listed in the configuration YAML.
4. Updates the SHA values in the YAML file if a mismatch is found.
5. Cleans up temporary files after the process is complete.

Requirements:
- Python 3.6 or higher
- External libraries:
    `argparse`, `glob`, `json`, `logging`, `os`, `shutil`, `sys`,
    `coloredlogs`, `yaml`, `gitpython`

Usage:
    python3 generate-sha-commits.py --org <organization> --repo <repository> --branch <branch>

Arguments:
    --org       Organization of the repository (default: "stolostron").
    --repo      Destination repository of the pipeline manifest (required).
    --branch    Target branch of the pipeline manifest (required).
"""

import argparse
import glob
import json
import logging
import os
import shutil
import sys
from typing import Optional

import coloredlogs
import yaml

from git import Repo

# Configure logging with coloredlogs
coloredlogs.install(level='DEBUG')  # Set the logging level as needed

def save_yaml(file_path, yaml_data):
    """
    Save YAML data to a file.

    Args:
        file_path (str): The path to the YAML file.
        yaml_data (dict): The data to be written to the YAML file.
    """
    with open(file_path, "w", encoding="utf-8") as file:
        yaml.dump(yaml_data, file)

def update_yaml_field(file_path, repo_name, new_sha):
    """
    Update the 'sha' field in a YAML file.

    Args:
        file_path (str): The path to the YAML file.
        repo_name (str): The name of the repository to update.
        new_sha (str): The new SHA value to set for the repository.
    """
    with open(file_path, "r", encoding="utf-8") as file:
        yaml_data = yaml.safe_load(file)

    for entry in yaml_data:
        if "repo_name" in entry and entry["repo_name"] == repo_name and "sha" in entry:
            logging.info("Updating YAML field for repository: %s", repo_name)
            entry["sha"] = new_sha
            break

    save_yaml(file_path, yaml_data)

def clone_pipeline_repo(org, repo_name, branch, target_path, pat=None):
    """
    Clone the pipeline repository.

    Args:
        org (str): The organization name of the repository.
        repo_name (str): The name of the repository to clone.
        branch (str): The branch to checkout after cloning.
        target_path (str): The directory path to clone the repository into.
    """
    logging.info(
        "Cloning repository: %s from branch: %s into path: %s",
        repo_name, branch, target_path
    )
    if pat:
        # Construct the URL with the PAT
        clone_url = f"https://{pat}@github.com/{org}/{repo_name}.git"

    else:
        logging.warning("Personal Access Token (PAT) not provided. Cloning without authentication.")
        clone_url = f"https://github.com/{org}/{repo_name}.git"

    repository = Repo.clone_from(clone_url, target_path)
    repository.git.checkout(branch)

def fetch_latest_manifest(dir_path) -> Optional[str]:
    """
    Fetch the latest manifest file from the snapshots directory.

    Args:
        dir_path (str): The path to the directory containing manifest files.

    Returns:
        str or None: The path to the latest manifest file, or None if no manifest is found.
    """
    manifest = glob.glob(os.path.join(dir_path, "manifest.json"))

    return manifest[-1] if manifest else None

def read_json_file(file_path) -> dict:
    """
    Read JSON data from a file.

    Args:
        file_path (str): The path to the JSON file.

    Returns:
        dict: The JSON data read from the file.
    """
    logging.info("Reading JSON data from file: %s", file_path)
    with open(file_path, "r", encoding="utf-8") as file:
        data = json.load(file)

    logging.info("JSON data read successfully.\n")
    return data

def main():
    """
    Main function that orchestrates the synchronization of SHA values between
    a pipeline manifest (in JSON format) and a configuration YAML file.
    """

    logging.basicConfig(level=logging.INFO)
    logging.info("Starting Pipeline Manifest Sha Sync script...")

    parser = argparse.ArgumentParser()
    parser.add_argument("--org", dest="org", default="stolostron", required=False, type=str,
                        help="Organization of the repository")

    parser.add_argument("--repo", dest="repo", required=True, type=str,
                        help="Destination repository of the pipeline manifest")

    parser.add_argument("--branch", dest="branch", required=True, type=str,
                        help="Target branch of the pipeline manifest")

    # Parse the command line arguments.
    args = parser.parse_args()

    # Define paths
    base_path = os.path.dirname(os.path.realpath(__file__))
    config_yaml = os.path.join(base_path, "config.yaml")
    repo_directory = os.path.join(base_path, f"tmp/{args.repo}")

    # Load configuration
    logging.info("Loading configuration from: %s", config_yaml)
    with open(config_yaml, 'r', encoding="utf-8") as file:
        config = yaml.safe_load(file)

    # Clone pipeline repository into temporary directory path.
    if os.path.exists(repo_directory): # If path exists, remove and re-clone
        logging.warning(
            "The repository directory already exists, removing directory at: %s",
            repo_directory
        )
        shutil.rmtree(repo_directory)

    logging.info(
        "Cloning pipeline repository: %s/%s (branch: %s)",
        args.org, args.repo, args.branch
    )
    clone_pipeline_repo(
        args.org, args.repo, args.branch,
        target_path=repo_directory, pat=os.getenv("GH_READ_PAT")
    )

    # Fetch latest manifest
    if not os.path.exists(repo_directory):
        logging.error("Repo directory does not exist in repository: %s", args.repo)
        sys.exit(1)

    logging.info("Fetching latest manifest from repo directory")
    manifest_file_path = fetch_latest_manifest(repo_directory)
    if not manifest_file_path:
        logging.error(
            "Failed to fetch latest manifest file from snapshots in repository: %s",
            args.repo
        )
        sys.exit(1)
    logging.info(
        "Latest manifest file fetched successfully from snapshots in repository: %s",
        args.repo
    )

    # Read manifest data
    logging.info("Reading manifest data from file: %s", manifest_file_path)
    for repo in config:
        repo_name, repo_sha = repo.get("repo_name"), repo.get("sha")

        if repo_name and repo_sha:
            logging.info("Checking repository for updates: %s", repo_name)
            found_match = False

            # Compare git-sha256 values
            for entry in read_json_file(manifest_file_path):
                entry_name, entry_sha = entry.get("image-name"), entry.get("git-sha256")

                if entry_name == repo_name and entry_sha != repo_sha:
                    found_match = True
                    logging.warning("Sha mismatch for repository %s: YAML sha %s, JSON sha %s",
                                    repo_name, repo_sha, entry_sha)

                    update_yaml_field(config_yaml, repo_name, entry_sha)
                    break

            if not found_match:
                logging.info("No SHA mismatch found for repository %s", repo_name)
            print("\n")

    logging.info("All repositories and operators processed successfully.")
    logging.info("Performing cleanup...")
    shutil.rmtree(
        (os.path.join(os.path.dirname(os.path.realpath(__file__)), "tmp")),
        ignore_errors=True,
    )

    logging.info("Cleanup completed.")
    logging.info("Script execution completed.")

if __name__ == '__main__':
    main()
