#!/usr/bin/env python3
# Copyright (c) 2026 Red Hat, Inc.
# Copyright Contributors to the Open Cluster Management project
# Assumes: Python 3.6+

"""
CLI for the bundle-generation config schema validator.

The schema itself lives in ``utils/config_validator.py`` so the generators
can validate their own config at startup. This script is the standalone /
manual entry point.

Detects:
  - Missing required keys
  - Unknown keys (typos or stale config)
  - Type mismatches (e.g. string where list expected)
  - Structural issues (e.g. missing operators/charts list)

Usage:
  python validate-config.py --config config.yaml --type operators
  python validate-config.py --config charts-config.yaml --type charts
  python validate-config.py --config copy-config.yaml --type copy
  python validate-config.py --config config.yaml --type operators --strict
"""

import argparse
import sys

from utils.config_validator import validate_file


def main():
    """Entry point for the config schema validator."""
    parser = argparse.ArgumentParser(
        description="Validate bundle-generation config files against the known schema."
    )
    parser.add_argument(
        "--config",
        required=True,
        help="Path to the config YAML file to validate",
    )
    parser.add_argument(
        "--type",
        required=True,
        choices=["operators", "charts", "copy"],
        dest="config_type",
        help=(
            "Config type: 'operators' for config.yaml, "
            "'charts' for charts-config.yaml, 'copy' for copy-config.yaml"
        ),
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat warnings (unknown keys) as errors",
    )
    parser.add_argument(
        "--debug",
        "-v",
        action="store_true",
        help="Enable DEBUG-level logging",
    )

    args = parser.parse_args()

    import coloredlogs

    coloredlogs.install(level="DEBUG" if args.debug else "INFO")

    success = validate_file(args.config, args.config_type, strict=args.strict)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
