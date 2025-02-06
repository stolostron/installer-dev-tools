#!/usr/bin/env python3
# Copyright (c) 2024 Red Hat, Inc.
# Copyright Contributors to the Open Cluster Management project
# Assumes: Python 3.6+

import argparse
import logging
import os
import shutil

from git import Repo

TARGET_DIR = "config/images"
TARGET_FILE = os.path.join(TARGET_DIR, "image-alias.json")

def fetch_image_alias_json(image_path):
    # Fetch the file from the source repo (assuming the file is in the root of the other repo)
    source_file = os.path.join(image_path, "image-alias.json")
    
    # Ensure the target directory exists
    os.makedirs(TARGET_DIR, exist_ok=True)

    # Copy the file to the target directory
    shutil.copy(source_file, TARGET_FILE)
    
    print(f"Successfully fetched 'image-alias.json' from repo into {TARGET_FILE}")
    
    return source_file
    
def clone_pipeline_repo(org, repo_name, branch, target_path, pat=None):
    """
    Clone the pipeline repository.

    Args:
        org (str): The organization name of the repository.
        repo_name (str): The name of the repository to clone.
        branch (str): The branch to checkout after cloning.
        target_path (str): The directory path to clone the repository into.
    """
    logging.info(f"Cloning repository: {repo_name} from branch: {branch} into path: {target_path}")
    if pat:
        # Construct the URL with the PAT
        clone_url = f"https://{pat}@github.com/{org}/{repo_name}.git"

    else:
        logging.warning("Personal Access Token (PAT) not provided. Cloning without authentication.")
        clone_url = f"https://github.com/{org}/{repo_name}.git"

    repository = Repo.clone_from(clone_url, target_path)
    repository.git.checkout(branch)

def main():
    logging.basicConfig(level=logging.INFO)
    logging.info("Fetching latest image manifest ... ")
    
    parser = argparse.ArgumentParser()
    parser.add_argument("--org", dest="org", default="stolostron", required=False, type=str,
                        help="Organization of the repository")

    parser.add_argument("--repo", dest="repo", required=True, type=str,
                        help="Destination repository of the pipeline manifest")

    parser.add_argument("--branch", dest="branch", required=True, type=str,
                        help="Target branch of the pipeline manifest")

    # Parse the command line arguments.
    args = parser.parse_args()

    # Clone pipeline repository into temporary directory path.
    repo_directory = os.path.join(os.path.dirname(os.path.realpath(__file__)), f"tmp/{args.repo}")
    if os.path.exists(repo_directory): # If path exists, remove and re-clone
        logging.warning("The repository directory already exists, removing directory at: %s" % repo_directory)
        shutil.rmtree(repo_directory)
    logging.info("Cloning pipeline repository: %s/%s (branch: %s)" % (args.org, args.repo, args.branch))
    clone_pipeline_repo(args.org, args.repo, args.branch, target_path=repo_directory, pat=os.getenv("GH_READ_PAT"))

    # Fetch latest manifest
    snapshots_path = os.path.join(repo_directory, ".")
    if not os.path.exists(snapshots_path):
        logging.error("Snapshots directory does not exist in repository: %s" % args.repo)
        exit(1)
        
    logging.info("Fetching latest manifest from snapshots directory")
    manifest_file_path = fetch_image_alias_json(snapshots_path)
    logging.info("Manifest file path: %s" % manifest_file_path)
    if not manifest_file_path:
        logging.error("Failed to fetch latest manifest file from snapshots in repository: %s" % args.repo)
        exit(1)
    logging.info("Latest manifest file fetched successfully from snapshots in repository: %s" % args.repo)


    logging.info("All repositories and operators processed successfully.")
    logging.info("Performing cleanup...")
    shutil.rmtree((os.path.join(os.path.dirname(os.path.realpath(__file__)), "tmp")), ignore_errors=True)

    logging.info("Cleanup completed.")
    logging.info("Script execution completed.")

if __name__ == "__main__":
    main()
