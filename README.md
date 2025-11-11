# installer-dev-tools

Developer toolkit for Red Hat Advanced Cluster Management (ACM) and Multicluster Engine (MCE) operators. This repository provides automation scripts, compliance checkers, build monitors, and development utilities for the stolostron project team.

## Overview

This toolkit serves as a centralized hub for:
- **Konflux Build Monitoring & Compliance** - Monitor CI/CD builds and validate compliance across multiple dimensions
- **Release Management** - Version management, component onboarding, and release automation
- **Bundle Generation** - Generate Helm charts and operator bundles from OLM manifests
- **Quality Engineering** - Build notifications and PR status tracking
- **Pod Security Compliance** - Validate and enforce OpenShift pod security standards
- **Cloud Infrastructure** - Azure AKS cluster provisioning for testing

## Quick Start

### Prerequisites

**Required Tools:**
- `kubectl` or `oc` (OpenShift CLI)
- `yq` (YAML processor)
- `jq` (JSON processor)
- `skopeo` (container image inspection)
- Python 3.6+

**Optional Tools (for specific scripts):**
- `operator-sdk` (for AKS OLM setup)
- `az` (Azure CLI for AKS provisioning)
- `podman` (for bundle generation)

**Authentication:**
- GitHub token in `authorization.txt` (for Konflux scripts)
- OpenShift login (`oc login` or KUBECONFIG)
- Quay registry pull secrets (see [pull-secret-propagation-guide.md](pull-secret-propagation-guide.md))

### Installation

```bash
# Clone the repository
git clone https://github.com/stolostron/installer-dev-tools.git
cd installer-dev-tools

# Install Python dependencies
pip install -r scripts/qe/requirements.txt

# Verify you're logged into OpenShift
oc whoami
```

## Script Categories

### Konflux Scripts (`/scripts/konflux/`)

Monitor and validate Konflux-based CI/CD builds for ACM and MCE operators.

**Key Scripts:**

| Script | Description |
|--------|-------------|
| `compliance.sh` | Validate component compliance (image promotion, hermetic builds, EC, multiarch) |
| `batch-compliance.sh` | Run compliance checks in parallel for multiple applications |
| `konflux-build-monitor-v2.py` | Comprehensive build monitoring (apps, snapshots, releases, Quay status) |
| `analyze-diffs.sh` | Enforce development phase policies (feature-complete, code-lockdown) |
| `konflux-snapshot-difftool.sh` | Generate git diffs between Konflux snapshots |
| `check-component-promotions.sh` | Monitor component promotion status |

**Example Usage:**

```bash
cd scripts/konflux

# Check compliance for ACM 2.15
./compliance.sh acm-215

# Check compliance filtered by squad
./compliance.sh --squad=grc acm-215

# Run batch compliance checks
./batch-compliance.sh acm-215 mce-29

# Monitor builds for multiple releases
python3 konflux-build-monitor-v2.py --apps release-acm-216,release-mce-211 --verbose

# Analyze snapshot diffs for code freeze compliance
./konflux-snapshot-difftool.sh -v acm-2.15.0 -s snapshot1 -s snapshot2
./analyze-diffs.sh --mode code-lockdown --format json
```

### QE Scripts (`/scripts/qe/`)

Quality engineering tools for build notifications and PR tracking.

**Key Scripts:**

| Script | Description |
|--------|-------------|
| `konflux-build-notification.sh` | Monitor and notify about new Konflux builds |
| `konflux-build-status.sh` | Check current build status |
| `pr-downstream-status.py` | Track downstream PR merge status |

**Example Usage:**

```bash
cd scripts/qe

# Check for new builds and generate diff reports
./konflux-build-notification.sh

# Check PR downstream status
python3 pr-downstream-status.py
```

### Compliance Scripts (`/scripts/compliance/`)

Validate and enforce OpenShift pod security standards for ACM/MCE installations.

**Key Scripts:**

| Script | Description |
|--------|-------------|
| `pod-linter.sh` | Scan pods for SCC usage and security context violations |
| `pod-enforce.sh` | Automatically remediate security violations |

**Example Usage:**

```bash
cd scripts/compliance

# Scan all ACM/MCE pods for security violations
./pod-linter.sh

# Automatically patch deployments to enforce security
./pod-enforce.sh
```

### Bundle Generation Scripts (`/scripts/bundle-generation/`)

Generate Helm charts and operator bundles from OLM manifests for custom testing.

**Key Scripts:**

| Script | Description |
|--------|-------------|
| `generate-charts.py` | Convert OLM bundles to Helm charts |
| `bundles-to-charts.py` | Bundle to chart conversion utility |
| `move-charts.py` | Move generated charts to target locations |

**Documentation:**
- [Custom Bundle Guide](custom-bundle-generation/CUSTOM_BUNDLE_GUIDE.md) - Build custom operator bundles from scratch
- [Cloned Bundle Guide](custom-bundle-generation/CLONED_BUNDLE_GUIDE.md) - Streamlined workflow using existing bundles

### Release Scripts (`/scripts/release/`)

Release management, versioning, and component onboarding.

**Key Scripts:**

| Script | Description |
|--------|-------------|
| `onboard-new-components.py` | Interactive wizard for onboarding new components |
| `release-version.sh` | Validate operator versions match resource annotations |
| `refresh-image-aliases.py` | Update image alias configurations |

**Example Usage:**

```bash
cd scripts/release

# Onboard a new component
python3 onboard-new-components.py

# Validate deployment versions
./release-version.sh
```

### AKS Scripts (`/scripts/aks/`)

Azure Kubernetes Service cluster provisioning for testing.

**Key Scripts:**

| Script | Description |
|--------|-------------|
| `create-aks.sh` | Create AKS cluster with OLM installed |
| `delete-aks.sh` | Delete AKS cluster and resources |

**Example Usage:**

```bash
cd scripts/aks

# Create AKS cluster
./create-aks.sh eastus my-test-cluster my-resource-group

# Delete when done
./delete-aks.sh my-resource-group
```

### Tools & Utils

- `/scripts/tools/` - Utility scripts (image validation, etc.)
- `/scripts/utils/` - Common helper functions shared across scripts

## Key Features

- **Squad-Based Filtering**: Filter compliance checks by team ownership
- **Multi-Architecture Support**: Validate builds for amd64, arm64, ppc64le, s390x
- **Parallel Processing**: Run batch checks concurrently for faster results
- **Multiple Output Formats**: Text, JSON, CSV for different use cases
- **Development Phase Awareness**: Code freeze policy enforcement
- **Comprehensive Monitoring**: Full-stack visibility from builds to deployments

## Configuration

Configuration templates are available in `/config/`:
- `config.tpl` - OLM operator configuration template
- `charts-config.tpl` - Helm chart configuration template

## Documentation

- [CONTRIBUTING.md](CONTRIBUTING.md) - Contribution guidelines and DCO requirements
- [pull-secret-propagation-guide.md](pull-secret-propagation-guide.md) - Configure private registry access
- [SECURITY.md](SECURITY.md) - Security vulnerability reporting
- [custom-bundle-generation/](custom-bundle-generation/) - Custom bundle creation guides

## Common Workflows

### Monitor Konflux Builds

```bash
# Check compliance for a release
cd scripts/konflux
./compliance.sh acm-215

# Monitor for new builds
cd ../qe
./konflux-build-notification.sh
```

### Validate Pod Security

```bash
cd scripts/compliance
./pod-linter.sh
# Review lint.yaml output
./pod-enforce.sh  # Apply fixes
```

### Create Custom Operator Bundle

```bash
# Build custom operator image
IMG=quay.io/user/operator:tag make podman-build
podman push quay.io/user/operator:tag

# Follow the custom bundle guide
# See: custom-bundle-generation/CUSTOM_BUNDLE_GUIDE.md
```

### Enforce Code Freeze

```bash
cd scripts/konflux
./konflux-snapshot-difftool.sh -v acm-2.15.0 -s baseline -s current
./analyze-diffs.sh --mode code-lockdown --format csv
```

## Technology Stack

**Platforms:**
- Konflux (Red Hat CI/CD)
- OpenShift/Kubernetes
- Azure AKS
- Quay.io Registry

**Languages:**
- Bash
- Python 3.6+
- YAML/JSON

**Tools:**
- kubectl/oc, yq, jq
- skopeo, podman
- operator-sdk
- Azure CLI

## Contributing

We welcome contributions! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for:
- DCO sign-off requirements
- Pull request guidelines
- Pre-submission checks
- Issue management

## License

This project is licensed under the Apache License 2.0. See [LICENSE](LICENSE) for details.

## Support

For questions or issues:
1. Check existing [Issues](https://github.com/stolostron/installer-dev-tools/issues)
2. Review documentation in `/docs` and `/custom-bundle-generation`
3. Submit a new issue with detailed information

## Repository Information

**Organization**: [stolostron](https://github.com/stolostron)
**Maintainers**: See [OWNERS](OWNERS)
**Security**: See [SECURITY.md](SECURITY.md)
