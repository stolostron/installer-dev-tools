# ACM/MCE Custom Catalog Builder

This directory contains a `justfile` for building custom ACM (`multiclusterhub-operator`)
or MCE (`backplane-operator`) operator images, bundles, and catalogs for testing and
development.

## Prerequisites

- [just](https://github.com/casey/just) command runner
- `git`
- `podman` logged into quay.io: `podman login quay.io`
- `operator-sdk` CLI tool
- `opm` (Operator Package Manager) CLI tool
- `yq` YAML processor
- `python3` (used to create a `.venv` for chart-regeneration recipes)
- SSH access to `github.com/stolostron` repos (default clone protocol), or pass
  `--use-https` to clone over HTTPS instead

## Quick Start

Show built-in help and usage examples:

```bash
just help
```

List all available recipes with descriptions:

```bash
just --list
```

### End-to-End Workflow (Recommended)

Build operator, bundle, and catalog in one command:

```bash
just e2e-catalog --username <USERNAME> --bundle-branch <BUNDLE_BRANCH> \
  --base-catalog-tag <BASE_CATALOG_TAG> --image-tag <IMAGE_TAG>
```

**Example (MCH/ACM, default mode):**
```bash
just e2e-catalog --username myuser --bundle-branch release-2.16 \
  --base-catalog-tag latest-2.16 --image-tag my-test-v1
```

This will:
1. Clone/update the operator repo and build+push the operator image to
   `quay.io/<USERNAME>/multiclusterhub-operator:<IMAGE_TAG>`
2. Build and push the bundle image to
   `quay.io/<USERNAME>/acm-operator-bundle:<IMAGE_TAG>`
3. Build and push the catalog image to
   `quay.io/<USERNAME>/acm-dev-catalog:<IMAGE_TAG>`

**Example (MCE mode with a custom fork):**
```bash
just e2e-catalog --mode MCE --operator-repo git@github.com:user/backplane-operator.git \
  --operator-branch my-branch --username myuser --bundle-branch backplane-2.17 \
  --base-catalog-tag latest-2.17 --image-tag mytag
```

**Example (HTTPS instead of SSH for git clones):**
```bash
just e2e-catalog --use-https --username myuser --bundle-branch release-2.16 \
  --base-catalog-tag latest-2.16 --image-tag mytag
```

## Modes: MCH vs MCE

Most recipes accept `--mode MCH` (default) or `--mode MCE`, which selects the operator,
bundle, and catalog defaults:

| Mode | Operator dir | Default operator repo | Default bundle repo | Default catalog base | Channel prefix |
|------|--------------|------------------------|----------------------|-----------------------|-----------------|
| `MCH` (default) | `multiclusterhub-operator/` | `stolostron/multiclusterhub-operator` | `stolostron/acm-operator-bundle` | `quay.io/acm-d/acm-dev-catalog` | `release-<X.Y>` |
| `MCE` | `backplane-operator/` | `stolostron/backplane-operator` | `stolostron/mce-operator-bundle` | `quay.io/acm-d/mce-dev-catalog` | `stable-<X.Y>` |

Default repo URLs use SSH (`git@github.com:...`); pass `--use-https` to use
`https://github.com/...` instead, or override entirely with `--operator-repo`,
`--bundle-repo`, and/or `--catalog-base`.

Run `just info [--mode MCE] [...]` to print the resolved repo/catalog values for a given
set of flags without building anything.

## Recipe Reference

### Main workflow recipes

| Recipe | Purpose | Key flags |
|---|---|---|
| `e2e-catalog` | Build + push operator, bundle, and catalog images end-to-end | `--username`, `--bundle-branch`, `--base-catalog-tag`, `--image-tag`, `--operator-branch`, `--mode`, `--operator-repo`, `--bundle-repo`, `--catalog-base`, `--use-https`, `--additional-images` |
| `dev-branch-e2e` | Same as `e2e-catalog`, but first regenerates Helm charts in the operator repo with per-component branch/fork overrides | all `e2e-catalog` flags, plus `--component-branches`, `--component-forks`, `--org`, `--repo`, `--branch`, `--pipeline-repo`, `--pipeline-branch` |
| `info` | Print resolved operator/bundle/catalog repo values for the given mode/overrides (no side effects) | `--mode`, `--operator-repo`, `--bundle-repo`, `--catalog-base`, `--use-https` |
| `clone-operator` | Clone the operator repo (or update it if already cloned) | `--branch`, `--mode`, `--operator-repo`, `--use-https` |
| `cleanup-operator` | Remove the cloned operator directory | `--mode` |

### Operator image

| Recipe | Purpose | Key flags |
|---|---|---|
| `operator-build` | Clone/update operator repo, then build the operator image | `--img`, `--branch`, `--mode`, `--operator-repo`, `--use-https` |
| `operator-push` | Push a built operator image | `--img` |
| `operator-build-and-push` | `operator-build` + `operator-push` | same as `operator-build` |

### Bundle image

| Recipe | Purpose | Key flags |
|---|---|---|
| `bundle-build` | Clone the bundle repo, patch the CSV's operator image (and optionally related/operand images), set display name, validate, and build the bundle image | `--operator-image`, `--bundle-image`, `--branch` (default `release-2.16`), `--display-name`, `--mode`, `--bundle-repo`, `--use-https`, `--additional-images` |
| `bundle-push` | Push a built bundle image (requires quay.io login) | `--bundle-image` |
| `bundle-build-and-push` | `bundle-build` + `bundle-push`, with a mode-based default display name | same as `bundle-build` |

### Catalog image

| Recipe | Purpose | Key flags |
|---|---|---|
| `catalog-build` | Pull the base catalog, replace the last bundle in the release/stable channel with the new one (updating all channels that reference it), validate, and build the catalog image | `--base-catalog-tag`, `--bundle-img`, `--catalog-img`, `--mode`, `--catalog-base` |
| `catalog-push` | Push a built catalog image (requires quay.io login) | `--catalog-img` |
| `catalog-build-and-push` | `catalog-build` + `catalog-push` | same as `catalog-build` |

### Chart automation

| Recipe | Purpose | Key flags |
|---|---|---|
| `regenerate-charts` | Regenerate Helm charts via the bundle automation script, with optional per-component branch/fork overrides | `--org`, `--repo`, `--branch`, `--pipeline-repo`, `--pipeline-branch`, `--component-branches`, `--component-forks` |
| `copy-charts` | Copy existing Helm charts into `pkg/templates/` | `--org`, `--repo`, `--branch` |

## Common Flags

| Flag | Applies to | Default | Description |
|---|---|---|---|
| `--mode` | most recipes | `MCH` | `MCH` (ACM) or `MCE` |
| `--username` | `e2e-catalog`, `dev-branch-e2e` | — | Your quay.io username; used to build image names |
| `--bundle-branch` | `e2e-catalog`, `dev-branch-e2e` | — | Bundle repo git branch (e.g. `release-2.16`) |
| `--base-catalog-tag` | `e2e-catalog`, `dev-branch-e2e`, `catalog-build*` | — | Base catalog image tag (e.g. `latest-2.16`) |
| `--image-tag` | `e2e-catalog`, `dev-branch-e2e` | — | Tag applied to all built images |
| `--operator-branch` | `e2e-catalog`, `dev-branch-e2e`, `clone-operator`, `operator-build*` | `main` | Operator repo git branch |
| `--operator-repo` | most recipes | mode default | Custom operator fork/repo URL |
| `--bundle-repo` | bundle/e2e recipes | mode default | Custom bundle fork/repo URL |
| `--catalog-base` | catalog/e2e recipes | mode default | Custom base catalog image (without tag) |
| `--use-https` | most recipes | `false` (SSH) | Clone repos over HTTPS instead of SSH |
| `--display-name` | `bundle-build*` | `Custom Catalog` / mode-based | CSV display name |
| `--additional-images` | bundle/e2e recipes | — | Comma-separated `name=image` overrides for related/operand images in the CSV |
| `--component-branches` | `dev-branch-e2e`, `regenerate-charts` | — | Space-separated `component:branch` overrides |
| `--component-forks` | `dev-branch-e2e`, `regenerate-charts` | — | Space-separated `component:git_url` overrides |

## Common Workflows

### Testing Code Changes

After making changes to the operator (the repo is cloned automatically if it doesn't
already exist locally):

```bash
just e2e-catalog --username <your-username> --bundle-branch release-2.16 \
  --base-catalog-tag latest-2.16 --image-tag bugfix-v1
```

This builds everything with your changes and pushes to your quay.io repositories.

### Using a Different ACM/MCE Version

```bash
just e2e-catalog --username <username> --bundle-branch release-2.15 \
  --base-catalog-tag latest-2.15 --image-tag <tag>
```

### MCE Instead of ACM

```bash
just e2e-catalog --mode MCE --username <username> --bundle-branch backplane-2.17 \
  --base-catalog-tag latest-2.17 --image-tag <tag>
```

### Dev Workflow with Component Overrides

Regenerate charts against branches/forks of specific components before building the
full e2e catalog:

```bash
just dev-branch-e2e --username myuser --bundle-branch release-2.16 \
  --base-catalog-tag latest-2.16 --image-tag dev-v1 \
  --component-branches "search-operator:my-branch observability:feature-x"
```

### Iterating on Changes

When testing multiple iterations of a fix, increment your tag:

```bash
just e2e-catalog --username myuser --bundle-branch release-2.16 --base-catalog-tag latest-2.16 --image-tag bugfix-v1
# Test, make changes, rebuild
just e2e-catalog --username myuser --bundle-branch release-2.16 --base-catalog-tag latest-2.16 --image-tag bugfix-v2
```

### Cleaning Up

```bash
just cleanup-operator --mode MCH
```

## Notes

- All recipes automatically validate bundles and catalogs before building images
- The `bundle-build` recipe clones the upstream bundle repository and modifies the CSV
- The `catalog-build` recipe pulls the base catalog from `quay.io/acm-d` and replaces the
  last bundle in the target channel, updating **all** channels that reference it
- Images are automatically tagged with `:443` port for quay.io compatibility
- The cloned operator directory (`multiclusterhub-operator/` or `backplane-operator/`) is
  reused and updated (`git fetch` + `checkout` + `pull`) on subsequent runs rather than
  re-cloned

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

**Git clone fails (permission denied):**

Default repo URLs use SSH. Either ensure your SSH key is registered with GitHub, or
pass `--use-https` to clone over HTTPS instead.

**Images not public:**

Make sure your quay.io pull-secret is set up to be able to pull from quay.io:443. See [../cluster-controls/README.md](../cluster-controls/README.md) and look for `just apply-pull-secret`
