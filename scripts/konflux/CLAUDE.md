# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Overview

This is the Konflux scripts directory within the Red Hat installer-dev-tools repository. It contains shell scripts for monitoring and validating compliance of Konflux components in OpenShift environments.

## Core Scripts and Usage

### compliance.sh - Main Compliance Checker
Primary script for checking Konflux component compliance across multiple dimensions:

```bash
# Check compliance for a specific application
./compliance.sh acm-215

# Debug mode with verbose output
./compliance.sh --debug acm-215

# Debug specific component only
./compliance.sh --debug=my-component acm-215
```

**Output**: Creates CSV files in `data/` directory with compliance results.

### batch-compliance.sh - Parallel Processing
Runs compliance checks for multiple applications in parallel:

```bash
# Run compliance checks for multiple applications
./batch-compliance.sh acm-215 mce-29 acm-214
```

**Output**: Creates log files in `logs/` directory for each application.

### check-component-promotions.sh - Component Status
Monitors component promotion status and build information:

```bash
# Check promotions for specific release (defaults to mce-29)
./check-component-promotions.sh mce-29
```

**Output**: Creates timestamped log files with promotion status.

## Prerequisites

### Required Tools
- `oc` (OpenShift CLI) - Must be logged into cluster
- `yq` - YAML processor
- `curl` - HTTP requests to GitHub API
- `skopeo` - Container image inspection
- `jq` - JSON processor

### Authentication
- Create `authorization.txt` file with GitHub token for API access
- Login to OpenShift cluster with `oc login`
- For macOS ARM64: Scripts automatically add skopeo platform overrides

## Architecture

### Compliance Checking Logic
The compliance.sh script validates four key areas:

1. **Image Promotion Status** - Checks if components have valid promoted images
2. **Hermetic Builds** - Validates build-source-image, hermetic, and prefetch-input parameters
3. **Enterprise Contract** - Verifies enterprise contract compliance via GitHub check runs
4. **Multiarch Support** - Ensures build-platforms includes all 4 required architectures

### Data Flow
1. Queries OpenShift for component metadata (`oc get components`)
2. Fetches Tekton pipeline YAML files from GitHub repos
3. Inspects container images using skopeo
4. Validates GitHub check runs via API
5. Outputs structured CSV data for analysis

### File Structure
- `data/` - CSV compliance reports (e.g., `acm-215-compliance.csv`)
- `logs/` - Execution logs and error output
- `authorization.txt` - GitHub API token (gitignored)

## Development Guidelines

### Script Conventions
- All scripts use bash with `#!/usr/bin/env bash` or `#!/bin/bash`
- Error handling via HTTP status codes and exit codes
- Debug output directed to file descriptor 3 (`>&3`)
- Parallel processing with proper signal handling

### Adding New Checks
When adding compliance checks:
1. Follow the function pattern: `check_<feature_name>()`
2. Return standardized output format: "Enabled/Not Enabled" or "Compliant/Not Compliant"
3. Add debug logging with `[[ -n "$debug" ]]` guards
4. Handle both `.spec.params` and `.spec.pipelineSpec.params` locations

### Testing
- Test with various application names (acm-*, mce-*)
- Verify with components that have different pipeline configurations
- Test error conditions (missing files, API failures, invalid images)

## Common Issues

### GitHub API Rate Limits
Use `authorization.txt` file with valid GitHub token to avoid rate limiting.

### macOS Compatibility
Scripts detect macOS ARM64 and automatically add skopeo platform overrides.

### Pipeline Parameter Locations
The scripts check multiple YAML locations for parameters due to Konflux pipeline evolution:
- `.spec.params[].value` (current)
- `.spec.pipelineSpec.params[].default` (fallback)