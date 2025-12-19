# Installer Dev Tools - Scripts

This directory contains utility scripts for managing ACM (Advanced Cluster Management) and MCE (Multicluster Engine) operator development, build monitoring, compliance checking, and release management.

## Table of Contents

- [Konflux Scripts](#konflux-scripts)
  - [Build Monitoring](#build-monitoring)
  - [Compliance Management](#compliance-management)
  - [Release Management](#release-management)
  - [Vulnerability Scanning](#vulnerability-scanning)
  - [Snapshot Analysis](#snapshot-analysis)
  - [Catalog Management](#catalog-management)
- [QE Scripts](#qe-scripts)
- [Bundle Generation](#bundle-generation)
- [Release Scripts](#release-scripts)
- [Compliance Scripts](#compliance-scripts)
- [AKS Scripts](#aks-scripts)
- [Tools & Utilities](#tools--utilities)

---

## Konflux Scripts

Scripts for monitoring and managing Konflux builds, compliance, and releases for ACM and MCE operators.

**Location:** `scripts/konflux/`

### Build Monitoring

#### konflux-build-monitor-v3.py

Enhanced build monitor for ACM and MCE operator releases across Konflux applications, snapshots, releases, and Quay repositories.

```bash
# Monitor all releases
./konflux-build-monitor-v3.py

# Catalog-only mode
./konflux-build-monitor-v3.py --catalog-only

# Skip image age checks
./konflux-build-monitor-v3.py --skip-image-age-check

# Auto-retrigger failed pipelines
./konflux-build-monitor-v3.py --retrigger
```

**Features:**
- Configurable scan behavior (skip image age checks, catalog-only mode)
- Retry logic to eliminate "unknown" status values
- In-progress pipeline reporting with previous run info
- Failed push pipeline detection
- Automatic retrigger capability for failed pipelines
- Last successful push job completion time tracking
- GitHub branch age checking for stale nudge branches
- Improved display of stale images

**Configuration:** Edit the script to customize monitored applications for ACM (2.11-2.15) and MCE (2.6-2.10).

#### konflux-build-monitor-v2.py

Previous version of the build monitor with separate dev-publish and stage-publish release plan handling.

```bash
./konflux-build-monitor-v2.py
```

---

### Compliance Management

#### compliance.sh

Main compliance checker for Konflux components across multiple dimensions: image promotion, hermetic builds, Enterprise Contract, and multiarch support.

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

**Output:** Creates CSV files in `data/` directory with compliance results.

**Compliance Checks:**
1. **Image Promotion Status** - Validates promoted images exist
2. **Hermetic Builds** - Checks build-source-image, hermetic, and prefetch-input parameters
3. **Enterprise Contract** - Verifies EC compliance via GitHub check runs
4. **Multiarch Support** - Ensures all 4 required architectures (amd64, arm64, ppc64le, s390x)

#### batch-compliance.sh

Runs compliance checks for multiple applications in parallel.

```bash
# Run compliance checks for multiple applications
./batch-compliance.sh acm-215 mce-29 acm-214

# Filter by squad ownership
./batch-compliance.sh --squad=grc acm-215 mce-210
./batch-compliance.sh --squad=observability --retrigger acm-215 mce-210
```

**Output:** Creates log files in `logs/` directory for each application.

#### create-compliance-jira-issues.sh

Automatically creates and manages JIRA issues for non-compliant components from compliance.sh output.

**Prerequisites:**
- `jira-cli` - [ankitpokhrel/jira-cli](https://github.com/ankitpokhrel/jira-cli)
- `jq` - JSON processor
- `yq` - YAML processor

**Setup:**
```bash
# Configure environment variables
cp .env.template .env
# Edit .env with JIRA_USER, JIRA_API_TOKEN, JIRA_AUTH_TYPE
source .env
```

**Usage:**
```bash
# Preview what would be created (dry-run)
./create-compliance-jira-issues.sh --dry-run data/acm-215-compliance.csv

# Create issues with default settings
./create-compliance-jira-issues.sh data/acm-215-compliance.csv

# Skip duplicates and save output
./create-compliance-jira-issues.sh --skip-duplicates --output-json issues.json data/acm-215-compliance.csv

# Auto-close resolved issues
./create-compliance-jira-issues.sh --auto-close data/acm-215-compliance.csv

# Combine: create new issues AND close resolved ones
./create-compliance-jira-issues.sh --skip-duplicates --auto-close data/acm-215-compliance.csv

# Custom labels and priority
./create-compliance-jira-issues.sh --labels "konflux,compliance,urgent" --priority "Critical" data/acm-215-compliance.csv
```

**Features:**
- Auto-initialization of jira-cli using environment variables
- Smart duplicate detection and update handling
- Squad-based component mapping from `component-squad.yaml`
- Version derivation (acm-215 → "ACM 2.15.0")
- Rich issue descriptions with compliance status tables
- Automatic compliance-specific labeling (e.g., `push-failure`, `hermetic-builds-failure`)
- Progressive label updates as new failures are detected
- Auto-closing of resolved issues
- Parallel processing of multiple components

#### check-component-promotions.sh

Monitors component promotion status and build information.

```bash
# Check promotions for specific release (defaults to mce-29)
./check-component-promotions.sh mce-29
```

**Output:** Creates timestamped log files with promotion status.

#### summarize_violations.py

Summarizes Enterprise Contract violations from compliance reports.

```bash
./summarize_violations.py
```

---

### Release Management

#### release-manager.sh

Manages the creation, application, and monitoring of ACM and MCE releases.

```bash
# Create and apply a release
./release-manager.sh --create-and-apply

# Monitor release status
./release-manager.sh --monitor RELEASE_NAME

# Show latest releases
./release-manager.sh --show-latest
```

**Features:**
- Automatic release type mapping (RHSA, RHBA, RHEA)
- Release creation from templates
- Status monitoring with color-coded output
- Integration with acm-release-management repository

#### update-advisory.py

Updates payload YAML files with bug fixes and CVEs from Jira.

```bash
# Update advisory for a release
./update-advisory.py --release acm-2.15.0

# Dry-run mode
./update-advisory.py --release acm-2.15.0 --dry-run
```

**Features:**
- Fetches bug fixes and CVEs from Jira
- Updates component registry
- Validates changes before applying

---

### Vulnerability Scanning

#### scan-cluster-vulnerabilities.sh

Comprehensive vulnerability scanning tool for OpenShift clusters using Trivy.

📖 **Full Documentation:** [`README-vulnerability-scanner.md`](konflux/README-vulnerability-scanner.md)
🚀 **Quick Start:** [`QUICKSTART-vulnerability-scanner.md`](konflux/QUICKSTART-vulnerability-scanner.md)
📝 **Changelog:** [`CHANGELOG-vulnerability-scanner.md`](konflux/CHANGELOG-vulnerability-scanner.md)

**Basic Usage:**
```bash
# Scan all images in the cluster (CRITICAL and HIGH severity only)
./scan-cluster-vulnerabilities.sh

# Scan specific namespace
./scan-cluster-vulnerabilities.sh --namespace openshift-gitops

# Detailed scan with per-image reports
./scan-cluster-vulnerabilities.sh --detailed

# Generate JSON output for automation
./scan-cluster-vulnerabilities.sh --format json

# Scan only ACM images
./scan-cluster-vulnerabilities.sh --image-filter "acm-d"
```

**Features:**
- ✅ Auto-installation of Trivy
- ✅ Cluster-wide or namespace-specific scanning
- ✅ Severity filtering (CRITICAL, HIGH, MEDIUM, LOW, UNKNOWN)
- ✅ Multiple output formats (table, JSON, SARIF, CycloneDX, SPDX)
- ✅ **Detailed CVE Report (CSV)** with CVSS scores, package details, and fix versions
- ✅ Summary reports (text and JSON)
- ✅ Offline mode support
- ✅ Parallel scanning for performance
- ✅ Image filtering by pattern

**Output Files:**
- `vulnerability-summary-TIMESTAMP.txt` - Human-readable summary
- `vulnerability-summary-TIMESTAMP.json` - Machine-readable summary
- `detailed-vulnerabilities-TIMESTAMP.csv` - **Actionable CVE details** ⭐
- `IMAGE-NAME-TIMESTAMP.json` - Per-image reports (with --detailed)

**Prerequisites:**
- OpenShift CLI (`oc`) - logged into cluster
- `jq` - JSON processor
- Trivy (auto-installed if missing)

#### scan-stolostron-vulnerabilities.sh

Security vulnerability scanner for github.com/stolostron repositories. Scans go.mod files in active repositories for vulnerabilities with CVSS >= 4.0.

```bash
# Scan all stolostron repositories
./scan-stolostron-vulnerabilities.sh

# Set custom CVSS threshold
MIN_CVSS_SCORE=7.0 ./scan-stolostron-vulnerabilities.sh
```

**Features:**
- Scans active repositories in stolostron GitHub organization
- Identifies vulnerabilities in Go dependencies
- CVSS-based filtering
- Generates JSON and text reports

**Prerequisites:**
- GitHub CLI (`gh`)
- `jq`, `curl`

**Output:**
- `vulnerability-report-TIMESTAMP.json`
- `vulnerability-summary-TIMESTAMP.txt`

---

### Snapshot Analysis

#### konflux-snapshot-difftool.sh

Generates git diffs between Konflux component snapshots or tags for analysis.

```bash
# Compare two snapshots
./konflux-snapshot-difftool.sh -v acm-2.15.0 -s release-acm-215-abc123 -s release-acm-215-def456

# Compare two tags
./konflux-snapshot-difftool.sh -v acm-2.14.1 -t 2.14.1-DOWNSTREAM-2025-09-29-02-19-47 -t 2.14.1-DOWNSTREAM-2025-10-05-14-32-18

# Force re-rendering of catalog YAML files
./konflux-snapshot-difftool.sh -v acm-2.15.0 -s SNAP1 -s SNAP2 --force-opm-render
```

**Output:** Creates diff files in `diffs/` directory for each component.

**Use Case:** Feed output to `analyze-diffs.sh` for policy violation checking.

#### analyze-diffs.sh

Analyzes git diffs created by `konflux-snapshot-difftool.sh` to identify commits that violate development phase policies.

📖 **Full Documentation:** [`README-analyze-diffs.md`](konflux/README-analyze-diffs.md)

**Usage:**
```bash
# Analyze diffs in feature-complete mode (default)
./analyze-diffs.sh --mode feature-complete

# Analyze diffs in code-lockdown mode with verbose output
./analyze-diffs.sh --mode code-lockdown --verbose

# Generate JSON report
./analyze-diffs.sh --mode code-lockdown --format json > report.json

# Show all changes including allowed ones
./analyze-diffs.sh --show-allowed

# Generate CSV for tracking
./analyze-diffs.sh --mode code-lockdown --format csv > status.csv
```

**Development Phases:**

**Feature Complete Mode** - Allows:
- Bug fixes, refactoring, tests, docs, dependencies, build/CI changes
- Rejects: New features, significant code additions

**Code Lockdown Mode** - Allows:
- Tests, docs, dependencies, build/CI changes only
- Rejects: ALL product code changes

**Output Formats:**
- Text (human-readable with colors)
- JSON (machine-readable)
- CSV (spreadsheet-compatible)

**Exit Codes:**
- `0` - No violations
- `1` - Policy violations detected

---

### Catalog Management

#### get-catalogs-from-release.sh

Extracts catalog information from a Konflux release.

```bash
./get-catalogs-from-release.sh <releaseName>
```

**Output:** Lists OCP versions and index images for the release.

#### get-catalogs-from-fbc-iib-log.sh

Extracts catalog information from FBC IIB (Index Image Build) logs.

```bash
./get-catalogs-from-fbc-iib-log.sh
```

#### refresh-catalog.sh

Refreshes the catalog build for ACM and MCE operators by creating PR branches in the acm-mce-operator-catalogs repository.

```bash
# Refresh both ACM and MCE catalogs
./refresh-catalog.sh

# Refresh specific catalog
./refresh-catalog.sh acm-redhat-operators
```

**Process:**
1. Clones acm-mce-operator-catalogs repository
2. Creates refresh branches for each catalog
3. Updates catalog-request.yaml with current timestamp
4. Pushes branches for PR creation

#### rebuild-component.sh

Triggers a rebuild of Konflux components by annotating them.

```bash
# Edit script to specify components to rebuild
./rebuild-component.sh
```

**Note:** Edit the `comps` variable in the script to specify which components to rebuild.

---

## QE Scripts

Scripts for QE team to monitor build notifications and PR downstream status.

**Location:** `scripts/qe/`

### konflux-build-notification.sh

Monitors ACM and MCE bundle releases and generates diff reports for posting to forums.

**Prerequisites:**
- `skopeo` (recommended)
- Podman login to quay.io

**Usage:**
```bash
./konflux-build-notification.sh
```

**Output:**
- `latest-acm.txt`, `latest-mce.txt` - Latest bundle tags
- `diff-acm.txt`, `diff-mce.txt` - Diff contents for forum posts
- `tmp/` directory - Bundle YAML files and summary files

**Note:** First run will report new builds (initializing latest files). Subsequent runs only show actual new builds.

### konflux-build-status.sh

Checks the build status of Konflux pipelines.

```bash
./konflux-build-status.sh
```

### konflux-pr-downstream-status.sh

Monitors PR downstream build status for ACM/MCE components.

```bash
./konflux-pr-downstream-status.sh
```

### pr-downstream-status.py / pr-downstream-status.sh

Legacy scripts for PR downstream status checking.

---

## Bundle Generation

Scripts for generating Helm charts from operator bundles.

**Location:** `scripts/bundle-generation/`

### generate-charts.py

Main script for generating Helm charts from ACM/MCE operator bundles.

```bash
./generate-charts.py --help
```

**Features:**
- Converts operator bundles to Helm charts
- CSV validation
- Git repository integration
- Version packaging

### bundles-to-charts.py

Helper script for bundle-to-chart conversion.

### generate-sha-commits.py

Generates SHA commits for bundle tracking.

### move-charts.py

Moves generated charts to appropriate directories.

### helper.py

Common utility functions for bundle generation scripts.

---

## Release Scripts

Scripts for managing releases and version tracking.

**Location:** `scripts/release/`

### release-version.sh

Validates version matches between component versions and annotations.

```bash
./release-version.sh
```

**Output:** `version-matches.csv` - Records version match status for components.

### onboard-new-components.py

Assists with onboarding new components to the release process.

### refresh-image-aliases.py

Refreshes image aliases in component registry.

---

## Compliance Scripts

Scripts for checking and enforcing pod security compliance in OpenShift.

**Location:** `scripts/compliance/`

### pod-linter.sh

Scans all pods installed by ACM Installer for security compliance, filtering out system namespaces.

**Checks:**
- Restricted SCC usage
- Security context settings
- Read-only root filesystem
- Pod anti-affinity rules
- Hard anti-affinity requirements

**Output:** `lint.yaml` - Results in format `namespace.pod.container.context:{desired: <state>, actual: <state>}`

### pod-enforce.sh

Patches deployments, statefulsets, and jobs with security settings based on pod-linter.sh results.

**Settings Applied:**
- `privileged: false`
- `readOnlyRootFilesystem: true`

**Process:**
1. Reads `lint.yaml` from pod-linter.sh
2. Creates `enforce.yaml` to track successfully found resources
3. Applies patches to deployments, statefulsets, and jobs

**Note:** Assumes pod naming convention `pod_name_xxxxxxxxx_xxxx` where the last two underscore-separated values are unique identifiers.

---

## AKS Scripts

Scripts for managing Azure Kubernetes Service (AKS) clusters.

**Location:** `scripts/aks/`

### create-aks.sh

Creates an AKS cluster with OIDC issuer enabled.

```bash
./create-aks.sh -r REGION -n CLUSTER_NAME -g RESOURCE_GROUP
```

**Example:**
```bash
./create-aks.sh -r eastus -n my-aks-cluster -g my-resource-group
```

**Actions:**
1. Azure login
2. Creates resource group
3. Creates AKS cluster with OIDC issuer
4. Retrieves cluster credentials

### delete-aks.sh

Deletes an AKS cluster and its resource group.

```bash
./delete-aks.sh -n CLUSTER_NAME -g RESOURCE_GROUP
```

---

## Tools & Utilities

**Location:** `scripts/tools/` and `scripts/utils/`

### tools/image_check.py

Utility for checking container image properties.

### utils/common.py

Common Python utilities shared across scripts.

### utils/utils.py

General utility functions for shell and Python scripts.

---

## Prerequisites

### Common Requirements

- **OpenShift CLI (`oc`)** - Required for Konflux and compliance scripts
- **Podman/Docker** - For image inspection
- **GitHub CLI (`gh`)** - For repository scanning and API access
- **`jq`** - JSON processing
- **`yq`** - YAML processing
- **`skopeo`** - Container image inspection
- **Python 3.6+** - For Python scripts
- **Trivy** - Vulnerability scanning (auto-installed by scan-cluster-vulnerabilities.sh)
- **jira-cli** - JIRA integration (for create-compliance-jira-issues.sh)

### Authentication

#### GitHub
Create `authorization.txt` file with GitHub token for API access:
```bash
echo "YOUR_GITHUB_TOKEN" > scripts/konflux/authorization.txt
```

#### OpenShift
Login to the Konflux cluster:
```bash
oc login --server=YOUR_CLUSTER_URL --token=YOUR_TOKEN
```

#### Quay
For build notification scripts:
```bash
podman login -u='<user>' -p='<quay token>' quay.io
```

#### JIRA
For JIRA issue creation:
```bash
cp scripts/konflux/.env.template scripts/konflux/.env
# Edit .env with JIRA_USER, JIRA_API_TOKEN, JIRA_AUTH_TYPE
source scripts/konflux/.env
```

---

## Component Squad Mapping

The `scripts/konflux/component-squad.yaml` file maps components to squad ownership for:
- Filtering compliance checks by squad
- Auto-assigning JIRA components in issue creation

Example structure:
```yaml
squads:
  server-foundation:
    jira-component: "Server Foundation"
    components:
      - cluster-curator-controller
      - managedcluster-import-controller
  grc:
    jira-component: "GRC"
    components:
      - governance-policy-framework
      - config-policy-controller
```

---

## Recommended Workflows

### 1. Monitoring Konflux Builds

```bash
# Daily monitoring
cd scripts/konflux
./konflux-build-monitor-v3.py

# Check compliance
./compliance.sh acm-215
./compliance.sh mce-29

# Create JIRA issues for failures
./create-compliance-jira-issues.sh --skip-duplicates --auto-close data/acm-215-compliance.csv
```

### 2. Release Code Freeze Validation

```bash
# Generate diffs between snapshots
./konflux-snapshot-difftool.sh -v acm-2.15.0 -s OLD_SNAPSHOT -s NEW_SNAPSHOT

# Check for policy violations
./analyze-diffs.sh --mode code-lockdown --format json > violations.json
```

### 3. Vulnerability Management

```bash
# Scan cluster for vulnerabilities
./scan-cluster-vulnerabilities.sh --namespace crt-redhat-acm-tenant --detailed

# Scan stolostron repositories
./scan-stolostron-vulnerabilities.sh

# Analyze CSV output for remediation planning
open vulnerability-reports/detailed-vulnerabilities-*.csv
```

### 4. Release Management

```bash
# Update advisories from Jira
./update-advisory.py --release acm-2.15.0

# Create and monitor release
./release-manager.sh --create-and-apply
./release-manager.sh --monitor RELEASE_NAME
```

---

## Additional Documentation

- **Konflux Scripts:** [`scripts/konflux/CLAUDE.md`](konflux/CLAUDE.md) - Detailed Konflux scripts documentation
- **Diff Analysis:** [`scripts/konflux/README-analyze-diffs.md`](konflux/README-analyze-diffs.md)
- **Vulnerability Scanner:** [`scripts/konflux/README-vulnerability-scanner.md`](konflux/README-vulnerability-scanner.md)
- **Quick Start Guide:** [`scripts/konflux/QUICKSTART-vulnerability-scanner.md`](konflux/QUICKSTART-vulnerability-scanner.md)
- **QE Scripts:** [`scripts/qe/README.md`](qe/README.md)
- **Pod Compliance:** [`scripts/compliance/README.md`](compliance/README.md)

---

## Contributing

When adding new scripts:

1. Follow bash/Python best practices
2. Include usage documentation in script header
3. Add entry to this README
4. Consider adding a dedicated README for complex scripts
5. Test with error conditions and edge cases
6. Update component-squad.yaml if adding team-specific logic

---

## Support

For issues or questions:
- Check script-specific documentation files
- Review error messages and logs in `logs/` and `data/` directories
- Verify prerequisites and authentication
- Consult team documentation in Confluence/Wiki

---

## License

See repository LICENSE file.
