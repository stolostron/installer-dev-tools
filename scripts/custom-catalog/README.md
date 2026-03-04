# ACM Custom Catalog Builder

This directory contains a `justfile` for building custom ACM operator images, bundles, and catalogs for testing and development.

## Prerequisites

- [just](https://github.com/casey/just) command runner
- `podman` logged into quay.io: `podman login quay.io`
- `operator-sdk` CLI tool
- `opm` (Operator Package Manager) CLI tool
- `yq` YAML processor

## Quick Start

List available recipes:

```bash
just -l
```

### End-to-End Workflow (Recommended)

Build operator, bundle, and catalog in one command:

```bash
just e2e-catalog <USERNAME> <VERSION> <UPSTREAM_TAG> <TAG>
```

**Example:**
```bash
just e2e-catalog myusername release-2.16 latest-2.16 my-test-v1
```

This will:
1. Build and push operator image to `quay.io/<USERNAME>/multiclusterhub-operator:<TAG>`
2. Build and push bundle image to `quay.io/<USERNAME>/acm-operator-bundle:<TAG>`
3. Build and push catalog image to `quay.io/<USERNAME>/acm-dev-catalog:<TAG>`

**Parameters:**
- `USERNAME`: Your quay.io username
- `VERSION`: Bundle branch to use (e.g., `release-2.16`, `release-2.15`)
- `UPSTREAM_TAG`: Base catalog tag to build on (e.g., `latest-2.16`, `latest-2.15`)
- `TAG`: Custom tag for all your images (e.g., `my-feature-v1`)

## Individual Recipes

### Operator Image

Build operator image:
```bash
just operator-build quay.io/<username>/multiclusterhub-operator:<tag>
```

Push operator image:
```bash
just operator-push quay.io/<username>/multiclusterhub-operator:<tag>
```

Build and push operator image:
```bash
just operator-build-and-push quay.io/<username>/multiclusterhub-operator:<tag>
```

### Bundle Image

Build bundle image:
```bash
just bundle-build <OPERATOR_IMAGE> <BUNDLE_IMAGE> [BRANCH] [DISPLAY_NAME]
```

**Example:**
```bash
just bundle-build \
  quay.io/myuser/multiclusterhub-operator:v1 \
  quay.io/myuser/acm-operator-bundle:v1 \
  release-2.16 \
  "My Custom ACM"
```

Build and push bundle image:
```bash
just bundle-build-and-push <OPERATOR_IMAGE> <BUNDLE_IMAGE> [BRANCH] [DISPLAY_NAME]
```

### Catalog Image

Build catalog image:
```bash
just catalog-build <VERSION> <BUNDLE_IMG> <CATALOG_IMG>
```

**Example:**
```bash
just catalog-build \
  latest-2.16 \
  quay.io/myuser/acm-operator-bundle:v1 \
  quay.io/myuser/acm-dev-catalog:v1
```

Build and push catalog image:
```bash
just catalog-build-and-push <VERSION> <BUNDLE_IMG> <CATALOG_IMG>
```

## Common Workflows

### Testing Code Changes

After making changes to the multiclusterhub-operator:

```bash
# From the multiclusterhub-operator directory
cd /path/to/multiclusterhub-operator

# Run the e2e workflow
just e2e-catalog <your-username> release-2.16 latest-2.16 bugfix-v1
```

This builds everything with your changes and pushes to your quay.io repositories.

### Using a Different ACM Version

To build against ACM 2.15 instead of 2.16:

```bash
just e2e-catalog <username> release-2.15 latest-2.15 <tag>
```

### Iterating on Changes

When testing multiple iterations of a fix, increment your tag:

```bash
just e2e-catalog myuser release-2.16 latest-2.16 bugfix-v1
# Test, make changes, rebuild
just e2e-catalog myuser release-2.16 latest-2.16 bugfix-v2
# Test, make changes, rebuild
just e2e-catalog myuser release-2.16 latest-2.16 bugfix-v3
```

## Notes

- All recipes automatically validate bundles and catalogs before building images
- The `bundle-build` recipe clones the upstream bundle repository and modifies the CSV
- The `catalog-build` recipe pulls the base catalog from `quay.io/acm-d` and adds your bundle
- Images are automatically tagged with `:443` port for quay.io compatibility

## Troubleshooting

**Not logged into quay.io:**
```bash
podman login quay.io
```

**Missing tools:**
```bash
# Install just
brew install just # or use your package manager
# See: https://github.com/casey/just?tab=readme-ov-file#packages

# Install operator-sdk
# See: https://sdk.operatorframework.io/docs/installation/

# Install opm
# See: https://docs.openshift.com/container-platform/latest/cli_reference/opm/cli-opm-install.html

# Install yq
# See: https://github.com/mikefarah/yq
```

**Images not public:**

Make sure your quay.io pull-secret is set up to be able to pull from quay.io:443. See [../cluster-controls/README.md](../cluster-controls/README.md) and look for `just apply-pull-secret`
