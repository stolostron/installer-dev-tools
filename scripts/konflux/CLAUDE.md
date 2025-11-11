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

# Filter by squad ownership
./compliance.sh --squad=grc acm-215
./compliance.sh --squad=observability mce-29
```

**Output**: Creates CSV files in `data/` directory with compliance results.

### batch-compliance.sh - Parallel Processing
Runs compliance checks for multiple applications in parallel:

```bash
# Run compliance checks for multiple applications
./batch-compliance.sh acm-215 mce-29 acm-214

# Filter by squad ownership
./batch-compliance.sh --squad=grc acm-215 mce-210
./batch-compliance.sh --squad=observability --retrigger acm-215 mce-210
```

**Output**: Creates log files in `logs/` directory for each application.

### check-component-promotions.sh - Component Status
Monitors component promotion status and build information:

```bash
# Check promotions for specific release (defaults to mce-29)
./check-component-promotions.sh mce-29
```

**Output**: Creates timestamped log files with promotion status.

### create-compliance-jira-issues.sh - JIRA Issue Creator
Automatically creates JIRA issues for non-compliant components from compliance.sh output.

**Purpose**: Streamlines JIRA issue creation for Konflux compliance failures by generating standardized, detailed bug reports with automated field mapping and duplicate prevention.

```bash
# First time setup - configure environment variables
cp .env.template .env
# Edit .env file with JIRA_USER, JIRA_API_TOKEN, JIRA_AUTH_TYPE
source .env

# Preview what would be created (dry-run)
./create-compliance-jira-issues.sh --dry-run data/acm-215-compliance.csv

# Create issues with default settings
./create-compliance-jira-issues.sh data/acm-215-compliance.csv

# Skip duplicates and save output
./create-compliance-jira-issues.sh --skip-duplicates --output-json issues.json data/acm-215-compliance.csv

# Custom labels and priority
./create-compliance-jira-issues.sh --labels "konflux,compliance,urgent" --priority "Critical" data/acm-215-compliance.csv

# Debug mode to see jira-cli commands
./create-compliance-jira-issues.sh --debug --dry-run data/acm-215-compliance.csv
```

**Key Features**:

- **Automatic jira-cli initialization** - Configures jira-cli non-interactively using environment variables
- **Smart duplicate detection** - `--skip-duplicates` searches for existing open issues with same labels
- **Squad-based component mapping** - Auto-assigns JIRA Component/s field from component-squad.yaml
- **Version derivation** - Auto-populates Affects Version/s (e.g., "ACM 2.15.0" from acm-215)
- **Rich issue descriptions** - Includes compliance status table, actionable remediation steps, and pipeline run links
- **Parallel processing** - Handles multiple components efficiently

**Compliance Checks Tracked**:

- **Image Promotion**: Failed, IMAGE_PULL_FAILURE, INSPECTION_FAILURE, DIGEST_FAILURE
- **Hermetic Builds**: Not Enabled (checks hermetic, build-source-image, prefetch-input)
- **Enterprise Contract**: Not Compliant, Push Failure
- **Multiarch Support**: Not Enabled (requires 4 platforms: amd64, arm64, ppc64le, s390x)
- **Push Pipeline**: Failed

**JIRA Issue Fields Auto-Set**:

- **Project**: ACM (or specified via --project)
- **Type**: Bug (configurable via --issue-type)
- **Priority**: Critical (configurable via --priority)
- **Severity**: Critical
- **Activity Type**: Quality / Stability / Reliability
- **Affects Version/s**: Auto-derived from filename (acm-215 → "ACM 2.15.0", mce-29 → "MCE 2.9.0")
- **Component/s**: Auto-mapped from component-squad.yaml (e.g., "Server Foundation", "GRC", "Installer")
- **Labels**: konflux, compliance, auto-created (configurable via --labels)
- **Summary**: `[app-name] component-name - Konflux compliance failure`

**Issue Description Format**:

1. Component metadata (name, application, build time)
2. Compliance status table showing pass/fail for each check
3. Required Actions section with specific remediation guidance based on failures:
   - Fix image promotion issues
   - Enable hermetic builds (with YAML parameters)
   - Fix Enterprise Contract violations
   - Enable multiarch support (with platform list)
   - Fix push pipeline failures
4. Pipeline Run Links section with direct URLs to failed runs

**Command Line Options**:

```bash
--project PROJECT        JIRA project key (default: ACM)
--issue-type TYPE        Issue type (default: Bug)
--priority PRIORITY      Priority (default: Critical)
--component COMPONENT    Override auto-detection from component-squad.yaml
--labels LABELS          Comma-separated labels (default: konflux,compliance,auto-created)
--dry-run               Preview without creating issues
--skip-duplicates       Skip if similar open issue exists
--output-json FILE      Save created issue keys to JSON file
--debug                 Show jira-cli commands and description content
```

**Environment Variables Required** (for auto-initialization):

```bash
JIRA_USER=your-email@redhat.com          # Your JIRA username/email
JIRA_API_TOKEN=your-pat-token            # Personal Access Token
JIRA_AUTH_TYPE=bearer                    # Auth type for PAT

# Optional
JIRA_PROJECT=ACM                         # Default project
JIRA_SERVER=https://issues.redhat.com    # JIRA server URL
JIRA_INSTALLATION=Local                  # Installation type
```

**Prerequisites**:

- `jira-cli` - [ankitpokhrel/jira-cli](https://github.com/ankitpokhrel/jira-cli) - Auto-configured by script
- `jq` - JSON processor
- `yq` - YAML processor (for component-squad.yaml parsing)

**Output**:

- Creates JIRA issues with detailed descriptions and proper field mapping
- Prints summary with counts: total processed, compliant (skipped), created, failed
- Lists created issues with URLs: `component-name: https://issues.redhat.com/browse/ACM-12345`
- Optionally saves issue keys to JSON file for tracking

**Component-Squad Mapping**:

The script uses `component-squad.yaml` to automatically map components to JIRA Component/s field:

```yaml
squads:
  server-foundation:
    jira-component: "Server Foundation"
    components:
      - cluster-curator-controller
      - managedcluster-import-controller
```

Result: Issues for these components get Component/s = "Server Foundation"

**Example Output**:

```text
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Konflux Compliance JIRA Issue Creator
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Project: ACM
Application: acm-215
Affects Version: ACM 2.15.0

Total components processed: 45
Compliant (skipped): 30
Issues created: 12
Failed: 3

Issues:
  • cluster-curator-controller-215: https://issues.redhat.com/browse/ACM-12345
  • managedcluster-import-controller-215: https://issues.redhat.com/browse/ACM-12346
```

**TODO / Future Enhancements**:

1. **Auto-close resolved issues**
   - When a new compliance scan shows a component is now compliant, automatically close the existing JIRA issue
   - Add a closing comment with the new scan results showing all checks passing
   - Implementation: Query for open issues with same component name + labels, check if component is now compliant, close with resolution comment

2. **Handle updated scan results for existing issues**
   - Decision needed on how to handle components that remain non-compliant across scans:
   - **Option A**: Close old issue, create new one with updated scan data (keeps issue history clean, clear timeline)
   - **Option B**: Add comment to existing issue with new scan results (preserves discussion thread, shows progression)
   - **Option C**: Update existing issue description with latest scan data (single source of truth, but loses history)
   - Recommended: Option B (comment-based updates) to preserve context and discussion
   - Implementation considerations:
     - Track issue creation timestamp vs scan timestamp
     - Compare old vs new compliance status to show what changed
     - Use JIRA transitions to update status if needed (e.g., Reopened if previously In Progress)

3. **Add compliance-specific labels**
   - Tag issues with specific compliance failure types for better filtering and tracking
   - Proposed labels based on failure type:
     - `image-promotion-failure` - Image promotion issues (IMAGE_PULL_FAILURE, INSPECTION_FAILURE, DIGEST_FAILURE)
     - `hermetic-builds-failure` - Hermetic builds not configured
     - `enterprise-contract-failure` - Enterprise Contract violations
     - `multiarch-support-failure` - Multiarch support missing
     - `push-failure` - Push pipeline failed

   - Benefits:
     - Easy filtering: `labels=konflux AND labels=push-failure`
     - Squad-specific queries: "Show me all hermetic build issues for Server Foundation"
     - Trend analysis: Track which compliance checks fail most frequently
     - Automated prioritization: Critical failures like push-failure could auto-escalate
   - Implementation: Add labels in `create_jira_issue()` function based on which status checks fail

4. **Automated periodic execution**
   - Set up automated compliance scanning and JIRA issue creation
   - Implementation options:
     - **Konflux CronJob**: Add Tekton PipelineRun with CronJob trigger in Konflux cluster
   - Prerequisites needed:
     - **GitHub Token**: ACM bot account with read access to Konflux repos (for compliance.sh API calls)
       - Contact: ACM bot owners or GitHub admin team
       - Scope: `repo:status`, `public_repo` for check runs API
     - **JIRA Token**: Service account or bot JIRA Personal Access Token
       - Contact: JIRA admin team for service account creation
       - Scope: Issue creation, search, and comment permissions on ACM project
   - Recommended schedule: Daily

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
- `component-squad.yaml` - Component to squad ownership mapping

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
