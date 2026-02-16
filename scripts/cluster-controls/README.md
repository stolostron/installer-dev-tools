# Cluster Controls

This directory contains utilities for managing OpenShift clusters with ACM (Advanced Cluster Management) and MCE (MultiCluster Engine) installations.

## Prerequisites

- `just` - Command runner (alternative to make)
- `oc` - OpenShift CLI
- `yq` - YAML processor
- `jq` - JSON processor (for pull secret management)
- `podman` - Container runtime (for registry authentication)

## Kubeconfig Management

All recipes use standard `oc` commands without forcing a specific kubeconfig location. This gives you full control:

```bash
# Use the default ~/.kube/config
just open-console

# Use a local kubeconfig for this session
export KUBECONFIG=./kubeconfig
just install-acm

# Or per-command
KUBECONFIG=./kubeconfig just apply-pull-secret
```

## Available Commands

The justfile is organized into modular files for better maintainability:
- **cluster.just** - Cluster utilities
- **acm.just** - ACM/MCE installation and management

### Viewing Commands

- `just -l` or `just --list` - List all available recipes with descriptions
- `just --choose` - Interactive menu to select and run recipes

### Cluster Utilities (cluster.just)

- `just open-console` - Open the OpenShift web console in your browser

### ACM/MCE Installation (acm.just)

- `just apply-pull-secret` - Apply pull secret for registry access (uses your podman credentials)
- `just install-acm [VERSION]` - Install ACM (default: release-2.16)
  - Creates namespace, operator group, and subscription
  - Applies MultiClusterHub configuration
- `just apply-custom-cs` - Apply both custom catalog sources (ACM + MCE)
- `just apply-custom-acm-cs [IMAGE]` - Apply custom ACM catalog source
- `just apply-custom-mce-cs [IMAGE]` - Apply custom MCE catalog source

### MCE Component Management (acm.just)

- `just toggle-mce-component <COMPONENT> <STATE>` - Enable/disable MCE components
  - Example: `just toggle-mce-component cluster-manager true`

## Directory Structure

```
cluster-controls/
├── justfile                 # Main justfile (imports module files)
├── cluster.just            # Cluster utilities
├── acm.just                # ACM/MCE installation and management
├── test-crd-missing.sh     # Script to test for missing CRDs
└── yamls/                  # Kubernetes manifests
    ├── acm-namespace.yaml
    ├── acm-og.yaml
    ├── acm-subscription.yaml
    ├── mch.yaml
    ├── variable-acm-cs.yaml
    └── variable-mce-cs.yaml
```

## Configuration

Default versions and images are defined in **acm.just**:

- `acm-image`: ACM catalog image (default: acm-d/acm-dev-catalog:latest-2.16)
- `mce-image`: MCE catalog image (default: acm-d/mce-dev-catalog:latest-2.11)
- `acm-version`: ACM release channel (default: release-2.16)

## Example Workflow

```bash
# Login to your cluster (using oc directly)
oc login https://api.cluster.example.com:6443 --token=sha256~...

# Optional: Use a local kubeconfig
export KUBECONFIG=./kubeconfig

# Install pull secret (requires podman login quay.io first)
just apply-pull-secret

# Install ACM with default version
just install-acm

# Or install a specific version
just install-acm release-2.15

# Apply custom catalog sources if needed
just apply-custom-cs

# Open the web console
just open-console
```
