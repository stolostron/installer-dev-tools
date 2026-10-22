# Custom ACM Bundle and Catalog Creation Guide

This guide documents the complete process for creating custom ACM operator bundles and catalog sources for testing operator changes.

## Overview

When developing changes to the multiclusterhub-operator, you need to:
1. Build a custom operator image with your changes
2. Create a custom bundle referencing that operator image
3. Create a custom catalog source containing the bundle
4. Deploy ACM using your custom catalog

## Prerequisites

- Access to a container registry (e.g., quay.io)
- OpenShift cluster with operator-lifecycle-manager
- Podman/Docker for building images
- Pull secret configured for your registry

## Step 1: Prepare the Bundle Structure

### Option A: Clone the ACM Operator Bundle (Recommended)
```bash
git clone https://github.com/stolostron/acm-operator-bundle.git
cd acm-operator-bundle
# Use this structure as your starting point
```

### Option B: Create Custom Bundle Structure
```bash
mkdir custom-acm-bundle
cd custom-acm-bundle
mkdir -p {manifests,metadata,extras}
```

## Step 2: Build Custom Operator Image

1. **Make your code changes** in the multiclusterhub-operator repository

2. **Build and push the operator image**:
```bash
OPERATOR_VERSION=2.15.0-custom-v1 IMG=quay.io/YOUR_USERNAME/multiclusterhub-operator:2.15.0-custom-v1 make podman-build
podman push quay.io/YOUR_USERNAME/multiclusterhub-operator:2.15.0-custom-v1
```

## Step 3: Create Bundle Manifests

### Generate CRDs (if you made API changes)
```bash
make manifests
```

### Key Files to Create/Modify

#### 1. ClusterServiceVersion (CSV)
**File**: `manifests/advanced-cluster-management.v2.15.0-custom.clusterserviceversion.yaml`

**Critical fields to update**:
```yaml
metadata:
  name: advanced-cluster-management.v2.15.0-custom  # Must match bundle name
  annotations:
    olm.skipRange: ">=2.9.0 <2.15.0-custom"  # Update version range
spec:
  version: 2.15.0-custom  # Custom version
  replaces: advanced-cluster-management.v2.14.0  # Previous version
  install:
    spec:
      deployments:
      - name: multiclusterhub-operator
        spec:
          template:
            spec:
              containers:
              - name: multiclusterhub-operator
                image: quay.io/YOUR_USERNAME/multiclusterhub-operator:2.15.0-custom-v1  # Your image
                env:
                - name: OPERATOR_VERSION
                  value: 2.15.0-custom-v1  # Must match image tag
```

**Important**: The CSV name must match exactly across all references.

#### 2. CRD Files
Copy updated CRDs from `config/crd/bases/`:
```bash
cp config/crd/bases/operator.open-cluster-management.io_multiclusterhubs.yaml custom-acm-bundle/manifests/
cp config/crd/bases/operator.open-cluster-management.io_internalhubcomponents.yaml custom-acm-bundle/manifests/
```

#### 3. Bundle Metadata
**File**: `metadata/annotations.yaml`
```yaml
annotations:
  operators.operatorframework.io.bundle.mediatype.v1: registry+v1
  operators.operatorframework.io.bundle.manifests.v1: manifests/
  operators.operatorframework.io.bundle.metadata.v1: metadata/
  operators.operatorframework.io.bundle.package.v1: advanced-cluster-management
  operators.operatorframework.io.bundle.channels.v1: release-2.15
  operators.operatorframework.io.bundle.channel.default.v1: release-2.15
```

## Step 4: Build and Push Bundle

```bash
cd custom-acm-bundle
podman build -t quay.io/YOUR_USERNAME/acm-custom-bundle:2.15.0-custom-v1 .
podman push quay.io/YOUR_USERNAME/acm-custom-bundle:2.15.0-custom-v1
```

## Step 5: Create Catalog Structure

### File-Based Catalog (FBC) Structure
```bash
mkdir -p custom-catalog/advanced-cluster-management
```

#### 1. Catalog Dockerfile
**File**: `custom-catalog/Dockerfile`
```dockerfile
FROM quay.io/operator-framework/opm:latest

# Copy the file-based catalog
COPY advanced-cluster-management /configs/advanced-cluster-management

# Use the serve command to serve the FBC catalog  
ENTRYPOINT ["/bin/opm"]
CMD ["serve", "/configs", "--cache-dir=/tmp", "--cache-enforce-integrity=false"]
```

#### 2. Bundle References
**File**: `custom-catalog/advanced-cluster-management/bundles.yaml`
```yaml
---
schema: olm.bundle
name: advanced-cluster-management.v2.15.0-custom  # Must match CSV name exactly
package: advanced-cluster-management
image: quay.io/YOUR_USERNAME/acm-custom-bundle:2.15.0-custom-v1
properties:
  - type: olm.gvk
    value:
      group: operator.open-cluster-management.io
      kind: MultiClusterHub
      version: v1
  - type: olm.package
    value:
      packageName: advanced-cluster-management
      version: 2.15.0-custom
```

#### 3. Channel Configuration
**File**: `custom-catalog/advanced-cluster-management/channel.yaml`
```yaml
---
schema: olm.channel
package: advanced-cluster-management
name: release-2.15
entries:
  - name: advanced-cluster-management.v2.15.0-custom
    replaces: advanced-cluster-management.v2.14.0
```

#### 4. Package Definition
**File**: `custom-catalog/advanced-cluster-management/package.yaml`
```yaml
---
schema: olm.package
name: advanced-cluster-management
defaultChannel: release-2.15
```

## Step 6: Build and Push Catalog

```bash
cd custom-catalog
podman build -t quay.io/YOUR_USERNAME/acm-custom-catalog:v1.0.0 .
podman push quay.io/YOUR_USERNAME/acm-custom-catalog:v1.0.0
```

## Step 7: Deploy Custom Catalog Source

### Create Pull Secret (if needed)
```bash
kubectl create secret docker-registry multiclusterhub-operator-pull-secret \
  --docker-server=quay.io \
  --docker-username=YOUR_USERNAME \
  --docker-password=YOUR_TOKEN \
  -n openshift-marketplace
```

### Create Catalog Source
**File**: `catalogsource.yaml`
```yaml
apiVersion: operators.coreos.com/v1alpha1
kind: CatalogSource
metadata:
  name: acm-custom-catalog
  namespace: openshift-marketplace
spec:
  sourceType: grpc
  image: quay.io/YOUR_USERNAME/acm-custom-catalog:v1.0.0
  displayName: "Custom ACM Catalog"
  publisher: "Your Name"
  secrets:
  - multiclusterhub-operator-pull-secret
  updateStrategy:
    registryPoll:
      interval: 10m
```

```bash
kubectl apply -f catalogsource.yaml
```

## Step 8: Install ACM from Custom Catalog

### Create Namespace and OperatorGroup
```bash
kubectl create namespace open-cluster-management

kubectl apply -f - << EOF
apiVersion: operators.coreos.com/v1
kind: OperatorGroup
metadata:
  name: open-cluster-management
  namespace: open-cluster-management
spec:
  targetNamespaces:
  - open-cluster-management
EOF
```

### Create Subscription
```bash
kubectl apply -f - << EOF
apiVersion: operators.coreos.com/v1alpha1
kind: Subscription
metadata:
  name: advanced-cluster-management
  namespace: open-cluster-management
spec:
  channel: release-2.15
  name: advanced-cluster-management
  source: acm-custom-catalog
  sourceNamespace: openshift-marketplace
  installPlanApproval: Automatic
  startingCSV: advanced-cluster-management.v2.15.0-custom
EOF
```

### Create MultiClusterHub
```bash
kubectl apply -f - << EOF
apiVersion: operator.open-cluster-management.io/v1
kind: MultiClusterHub
metadata:
  name: multiclusterhub
  namespace: open-cluster-management
spec: {}
EOF
```

## Critical Success Factors

### 1. Naming Consistency
**ALL of these must match exactly**:
- CSV metadata.name
- Bundle name in bundles.yaml
- Channel entries name
- startingCSV in subscription

Example: `advanced-cluster-management.v2.15.0-custom`

### 2. Version Consistency
- Operator image tag: `2.15.0-custom-v1`
- OPERATOR_VERSION env var in CSV: `2.15.0-custom-v1`
- CSV spec.version: `2.15.0-custom`
- Bundle version: `2.15.0-custom`

### 3. Registry Authentication
- Ensure pull secrets are properly configured
- Test image pull access before deployment
- Use `quay.io:443` format in pull secrets for private registries

## Troubleshooting Common Issues

### 1. Subscription Stuck in "UpgradePending"
- Delete and recreate the subscription
- Check that install plan references correct bundle version

### 2. CSV Not Installing
- Verify bundle name matches exactly in all places
- Check catalog source is healthy: `kubectl get catalogsource -n openshift-marketplace`
- Review install plan status: `kubectl get installplan -n NAMESPACE`

### 3. Image Pull Failures
- Verify pull secret exists and is referenced in catalog source
- Test manual image pull: `podman pull quay.io/YOUR_USERNAME/IMAGE:TAG`

### 4. Bundle Not Found
- Check bundle name consistency across files
- Verify catalog build included all necessary files
- Check catalog pod logs: `kubectl logs -n openshift-marketplace CATALOG_POD`

## Updating Your Bundle

When making changes:

1. **Update operator code** and rebuild image with new tag
2. **Update CSV** with new image reference and OPERATOR_VERSION
3. **Rebuild bundle** with new tag
4. **Update bundles.yaml** with new bundle image
5. **Rebuild catalog** with new tag
6. **Update catalog source** to reference new catalog image
7. **Delete and recreate subscription** if needed to pick up changes

## Version Management Strategy

Use a versioning scheme like:
- Operator image: `2.15.0-custom-v1`, `2.15.0-custom-v2`, etc.
- Bundle image: `2.15.0-custom-v1`, `2.15.0-custom-v2`, etc.
- Catalog image: `custom-catalog-v0.0.1`, `custom-catalog-v0.0.2`, etc.
- CSV version: `2.15.0-custom` (stays constant for same feature branch)

This allows iterative testing while maintaining OLM compatibility.

## Testing Workflow

1. **Make code changes**
2. **Build operator image** with incremented tag
3. **Update bundle** to reference new operator image
4. **Build and push bundle**
5. **Update catalog** to reference new bundle
6. **Build and push catalog**
7. **Update catalog source**
8. **Delete subscription and install plan** (if needed)
9. **Recreate subscription**
10. **Monitor CSV installation**
11. **Test your changes**

## Security Considerations

- Use private registries for sensitive code
- Implement proper RBAC for custom operators
- Review all permissions in ClusterRole definitions
- Test in isolated environments before production
- Never commit registry credentials to version control

## Best Practices

- Keep bundle names descriptive and versioned
- Use semantic versioning for images
- Test bundle installation in clean environments
- Document all custom changes in commit messages
- Use automated builds when possible
- Maintain separate branches for different feature sets
- Always test upgrade paths, not just fresh installs

---

This guide captures the complete workflow learned through hands-on experience with the multiclusterhub-operator development process.