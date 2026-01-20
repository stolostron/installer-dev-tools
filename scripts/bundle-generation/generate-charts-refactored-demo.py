#!/usr/bin/env python3
# Copyright (c) 2021 Red Hat, Inc.
# Copyright Contributors to the Open Cluster Management project
# Assumes: Python 3.6+

"""
REFACTORED VERSION DEMO - Shows how generate-charts.py would look using the shared library.

This is a demonstration of the refactoring approach. The actual refactoring would involve:
1. Replacing duplicate functions with imports from lib/
2. Both generate-charts.py and bundles-to-charts.py would use the same shared code
"""

import argparse
import os
import shutil
import yaml
import logging
import coloredlogs
import subprocess
import re
from git import Repo, exc
from packaging import version

# Import shared library functions
from lib.version_utils import is_version_compatible
from lib.image_processing import (
    parse_image_ref,
    find_templates_of_type,
    fixImageReferences,
    fixEnvVarImageReferences
)
from lib.namespace_templating import (
    ensure_webhook_namespace,
    ensure_certificate_namespace_references,
    process_crd_namespaces,
    update_helm_resources
)
from lib.helm_utils import (
    log_header,
    split_at,
    insertFlowControlIfAround,
    escape_template_variables
)

# Configure logging with coloredlogs
coloredlogs.install(level='DEBUG')

# Config Constants
SCRIPT_DIR = os.path.join(os.path.dirname(os.path.realpath(__file__)))
ROOT_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))


# ============================================================================
# Functions that are specific to generate-charts.py (not in bundles-to-charts)
# ============================================================================

def updateAddOnDeploymentConfig(yamlContent):
    """Chart-specific function - only in generate-charts.py"""
    pass


def updateClusterManagementAddOn(yamlContent):
    """Chart-specific function - only in generate-charts.py"""
    pass


def installAddonForAllClusters(yamlContent):
    """Chart-specific function - only in generate-charts.py"""
    pass


def updateServiceAccount(yamlContent):
    """Chart-specific function - only in generate-charts.py"""
    pass


def updateClusterRoleBinding(yamlContent):
    """Chart-specific function - only in generate-charts.py"""
    pass


def copyHelmChart(destinationChartPath, repo, chart, chartVersion, branch):
    """
    Copy and customize Helm charts from source to destination.
    This is specific to generate-charts.py workflow.
    """
    logging.info(f"Copying Helm chart for {chart['name']}")
    # Implementation...
    pass


def updateResources(outputDir, repo, chart):
    """
    Update specific resources in the chart.
    This is specific to generate-charts.py workflow.
    """
    logging.info(f"Updating resources for {chart['name']}")
    # Implementation...
    pass


def deep_update(overwrite, original):
    """Recursively update dictionary"""
    for key, value in overwrite.items():
        if isinstance(value, dict):
            original[key] = deep_update(value, original.get(key, {}))
        else:
            original[key] = value
    return original


def updateValues(overwrite, original):
    """Merge values.yaml files"""
    if not os.path.exists(overwrite):
        return

    with open(overwrite, 'r') as f:
        overwrite_data = yaml.safe_load(f)

    with open(original, 'r') as f:
        original_data = yaml.safe_load(f)

    merged = deep_update(overwrite_data, original_data)

    with open(original, 'w') as f:
        yaml.dump(merged, f, default_flow_style=False)


def addCRDs(repo, chart, outputDir):
    """
    Add CRDs from chart to output directory with namespace templating.
    Uses shared process_crd_namespaces() function.
    """
    if not 'chart-path' in chart:
        logging.critical(f"Chart path missing in the provided chart configuration: {chart}")
        exit(1)

    chartPath = os.path.join(os.path.dirname(os.path.realpath(__file__)), "tmp", repo, chart["chart-path"])

    if not os.path.exists(chartPath):
        logging.critical(f"Chart path not found at: {chartPath}")
        exit(1)

    crdPath = os.path.join(chartPath, "crds")
    if not os.path.exists(crdPath):
        logging.info(f"No CRDs for repo: {repo}")
        return

    destinationCRDPath = os.path.join(outputDir, "crds", chart['name'])

    if os.path.exists(destinationCRDPath):
        logging.warning(f"Destination CRDs path already exists. Removing: {destinationCRDPath}")
        shutil.rmtree(destinationCRDPath)

    os.makedirs(destinationCRDPath)
    logging.info(f"Created destination path for CRDs: {destinationCRDPath}")

    for filename in os.listdir(crdPath):
        if not filename.endswith(".yaml"):
            continue

        filepath = os.path.join(crdPath, filename)
        with open(filepath, 'r') as f:
            resourceFile = yaml.safe_load(f)

        if resourceFile["kind"] == "CustomResourceDefinition":
            # Use shared library function for namespace templating
            process_crd_namespaces(resourceFile, filename)

            targetPath = os.path.join(destinationCRDPath, filename)
            with open(targetPath, 'w') as f:
                yaml.dump(resourceFile, f, width=float("inf"), default_flow_style=False, allow_unicode=True)
            logging.info(f"Generated CRD file '{filename}'")

    logging.info(f"Finished processing CRDs for chart '{chart['name']}'\n")


# ============================================================================
# Main execution
# ============================================================================

def main():
    """Main entry point"""
    logging.info("🔧 Refactored generate-charts.py using shared library")

    # Example of using shared library functions:

    # 1. Version checking (from lib.version_utils)
    if is_version_compatible("backplane-2.11", "2.13", "2.8", "2.13"):
        logging.info("✅ Version is compatible")

    # 2. Image processing (from lib.image_processing)
    image_ref = "quay.io/stolostron/backplane-operator:latest"
    parsed = parse_image_ref(image_ref)
    logging.info(f"📦 Parsed image: {parsed}")

    # 3. Logging (from lib.helm_utils)
    log_header("Processing Helm Chart: {}", "my-chart")

    logging.info("""
    ✨ Benefits of refactoring:
    ─────────────────────────────────────────────
    ✅ No code duplication between scripts
    ✅ Bug fixes apply to both scripts automatically
    ✅ Easier to test individual functions
    ✅ Cleaner, more maintainable code
    ✅ Shared library can be versioned
    """)


if __name__ == "__main__":
    main()
