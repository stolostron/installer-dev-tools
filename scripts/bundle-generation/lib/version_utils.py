#!/usr/bin/env python3
# Copyright (c) 2024 Red Hat, Inc.
# Copyright Contributors to the Open Cluster Management project

"""
Version compatibility checking utilities.
"""

import os
import re
import logging
from packaging import version


def is_version_compatible(branch, min_release_version, min_backplane_version, min_ocm_version, enforce_master_check=True):
    """
    Checks if a branch or release version is compatible with minimum version requirements.

    Args:
        branch (str): Branch name (e.g., "release-2.11", "backplane-2.11")
        min_release_version (str): Minimum ACM release version required
        min_backplane_version (str): Minimum MCE/backplane version required
        min_ocm_version (str): Minimum OCM version required
        enforce_master_check (bool): If True, main/master branches return True

    Returns:
        bool: True if version is compatible, False otherwise
    """
    acm_release_version = os.getenv('ACM_RELEASE_VERSION')
    mce_release_version = os.getenv('MCE_RELEASE_VERSION')

    if not acm_release_version and not mce_release_version:
        logging.error("Neither ACM nor MCE release version is set in environment variables.")

        pattern = r'(\d+\.\d+)'

        if branch == "main" or branch == "master" or branch == "k8s-chart-fix":
            if enforce_master_check:
                logging.debug(f"Branch '{branch}' is main/master, version check returning True")
                return True
            else:
                logging.debug(f"Branch '{branch}' is main/master but enforce_master_check=False, returning False")
                return False

        match = re.search(pattern, branch)
        if match:
            v = match.group(1)  # Extract the version
            branch_version = version.Version(v)  # Create a Version object
            logging.debug(f"Extracted version from branch '{branch}': {v} -> {branch_version}")

            if "release-ocm" in branch:
                min_branch_version = version.Version(min_ocm_version)  # Use the minimum release version
                logging.debug(f"Using OCM min version: {min_branch_version}")

            elif "release" in branch:
                min_branch_version = version.Version(min_release_version)  # Use the minimum release version
                logging.debug(f"Using release min version: {min_branch_version}")

            elif "backplane" in branch or "mce" in branch:
                min_branch_version = version.Version(min_backplane_version)  # Use the minimum backplane version
                logging.debug(f"Using backplane min version: {min_branch_version}")

            else:
                logging.error("Unrecognized branch type for branch: %s", branch)
                return False

            # Check if the branch version is compatible with the specified minimum branch
            result = branch_version >= min_branch_version
            logging.debug(f"Comparing {branch_version} >= {min_branch_version}: {result}")
            return result

        else:
            logging.error("Version not found in branch: %s", branch)
            return False

    # When release versions are set via environment or config, use proper version comparison
    if acm_release_version and version.Version(acm_release_version) >= version.Version(min_release_version):
        logging.debug(f"ACM version check: {acm_release_version} >= {min_release_version}")
        return True

    elif mce_release_version and version.Version(mce_release_version) >= version.Version(min_backplane_version):
        logging.debug(f"MCE version check: {mce_release_version} >= {min_backplane_version}")
        return True

    else:
        logging.debug("Version checks failed")
        return False
