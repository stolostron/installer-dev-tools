#!/usr/bin/env python3
# Copyright (c) 2025 Red Hat, Inc.
# Copyright Contributors to the Open Cluster Management project
# Assumes: Python 3.6+

import coloredlogs
import logging
import os
import shutil
import yaml

# Configure logging with coloredlogs
coloredlogs.install(level='DEBUG')  # Set the logging level as needed

def copy_yaml(source_file_dir, source_file_name, dest_file_dir, dest_file_name):
    """Copy an existing YAML file from source to destination."""
    source_path = os.path.join(source_file_dir, source_file_name)
    target_path = os.path.join(dest_file_dir, dest_file_name)

    # Ensure the destination directory exists
    os.makedirs(dest_file_dir, exist_ok=True)

    try:
        shutil.copy(source_path, target_path)
        return target_path

    except Exception as e:
        logging.error(f"Failed to copy source file: {source_path} to destination: {target_path}: {e}")
        return None

def load_yaml(file_path):
    """Load an existing YAML file."""
    if not os.path.exists(file_path):
        logging.debug(f"{file_path} does not exists")
        return {}

    try:
        with open(file_path, 'r') as f:
            return yaml.safe_load(f) or {}

    except Exception as e:
        logging.error(f"Failed to load YAML file {file_path}: {e}")
        return {}

def save_yaml(file_path, data):
    """Save the updated data back to the YAML file."""
    try:
        with open(file_path, "w") as f:
            yaml.dump(data, f, default_flow_style=False)
        logging.info(f"Updated YAML file saved to: {file_path}")

    except Exception as e:
        logging.error(f"Error saving YAML file {file_path}: {e}")
