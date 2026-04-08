#!/usr/bin/env python3
# Copyright (c) 2025 Red Hat, Inc.
# Copyright Contributors to the Open Cluster Management project
# Assumes: Python 3.6+

import os
import shutil
import sys
import logging

REQUIRED_BUNDLE_FIELD_DESCRIPTION = "This is necessary for generating tool-specific bundles."

def get_required_config_value(config, key, description=REQUIRED_BUNDLE_FIELD_DESCRIPTION):
    """
    Retrieves a required configuration value. If the value is not found,
    logs an error and exits the program.
    :param config: The configuration dictionary.
    :param key: The key in the configuration to retrieve.
    :param description: A description of the required field for logging.
    :return: The value from the configuration if it exists.
    """
    value = config.get(key)
    if not value:
        logging.critical(
            f"Missing required field '{key}'. "
            f"{description} Please provide a valid {key}."
        )
        sys.exit(1)
    return value

def sync_owners_file(repo_root_path, destination_chart_path, chart_name):
    """
    Syncs OWNERS file from upstream repository root to destination chart directory.
    Upstream is the single source of truth:
    - If upstream has OWNERS -> copy to destination
    - If upstream has no OWNERS -> remove any existing downstream OWNERS

    :param repo_root_path: Path to the root of the cloned upstream repository
    :param destination_chart_path: Path to the destination chart directory
    :param chart_name: Name of the chart (for logging)
    """
    upstream_owners = os.path.join(repo_root_path, "OWNERS")
    dest_owners = os.path.join(destination_chart_path, "OWNERS")

    if os.path.exists(upstream_owners):
        # Upstream has OWNERS -> copy it
        shutil.copyfile(upstream_owners, dest_owners)
        logging.info(f"Copied OWNERS file from upstream repository root for chart: {chart_name}")
    else:
        # Upstream has no OWNERS -> remove any existing downstream OWNERS
        if os.path.exists(dest_owners):
            os.remove(dest_owners)
            logging.info(f"Removed OWNERS file for chart '{chart_name}' (not present in upstream repository root)")
        else:
            logging.debug(f"No OWNERS file in upstream repository root for chart: {chart_name}, will fallback to root OWNERS")