# Architecture: installer-dev-tools

## Overview

`installer-dev-tools` is the developer toolkit for the ACM/MCE installer
team within the `stolostron` organization. It is **not a shipped product**
— it is a collection of scripts, CLIs, and templates that support the
development, build, compliance, release, and testing lifecycle of the ACM
and MCE operators. It serves as a hub for:

- **Bundle generation** — converting operator OLM bundles/CSVs into the
  Helm charts that `multiclusterhub-operator` (ACM) and `backplane-operator`
  (MCE) embed and deploy.
- **Konflux build monitoring & compliance** — validating image promotion,
  hermetic builds, Enterprise Contract compliance, and multi-arch support.
- **Release management** — versioning checks, component onboarding, release
  automation.
- **Quality engineering** — build notifications and PR status tracking.
- **Pod security compliance**, **cloud infrastructure** (Azure AKS
  provisioning for testing), and **Jira integration** (PR-to-Jira progress
  summaries).

### Role in the ecosystem

The **bundle-generation tooling is consumed by the operator repositories**:
`multiclusterhub-operator` and `backplane-operator` invoke these scripts
(via their own `hack/bundle-automation/generate-shell.py`) to transform
component OLM bundles/CSVs into the Helm charts embedded under
`pkg/templates/charts/{toggle,always}/`. Several scripts here (`validate_csv.py`,
`chart-templates/`) are deliberately **not present in this repo** — they are
expected to exist in the consuming operator repo at execution time.

## Repository Structure

| Path | Purpose |
|------|---------|
| `README.md`, `AGENTS.md`, `CLAUDE.md` | Documentation and AI-agent context. |
| `CONTRIBUTING.md`, `SECURITY.md`, `OWNERS` | Governance. |
| `config/` | Config templates (`config.tpl`, `charts-config.tpl`) + `image-sync.yaml`. |
| `custom-bundle-generation/` | Guides for building custom bundles/catalogs. |
| `jira-pr-cli/` | Standalone, pip-installable Python CLI (`jira-pr-summary`). |
| `scripts/bundle-generation/` | **Core**: OLM bundle → Helm chart conversion (Python). |
| `scripts/konflux/` | Konflux compliance, releases, snapshot diffing, vulnerability scanning, catalog operations. |
| `scripts/qe/` | QE build notifications and PR downstream status. |
| `scripts/compliance/` | Pod security linting/enforcement. |
| `scripts/release/` | Version validation, component onboarding, image aliases. |
| `scripts/aks/` | Azure AKS cluster create/delete for testing. |
| `scripts/cluster-controls/` | `just`-based ACM/MCE install and cluster management. |
| `scripts/custom-catalog/` | `just`-based end-to-end operator/bundle/catalog builder. |
| `scripts/utils/` | Shared Python helpers. |

## Core Components

### Bundle generation (`scripts/bundle-generation/`)

- **`generate-charts.py`** — the main chart generator. Clones component
  repos, runs `helm template`, then post-processes the output: rewrites
  image references to `{{ .Values.global.imageOverrides.<key> }}`, injects
  Helm flow-control for node selectors/tolerations/proxy settings, wraps
  NetworkPolicies in conditionals, and applies version-gated feature
  toggles based on the target ACM/MCE release.
- **`bundles-to-charts.py`** — a sibling generator that builds charts
  directly from the CSV (`ClusterServiceVersion`) rather than a
  pre-existing Helm chart.
- **`move-charts.py`** — copies pre-existing Helm charts into the
  `charts/{toggle,always}/<name>` layout expected by the operator repos.
- **`generate-sha-commits.py`** — syncs pinned component SHAs against a
  pipeline repo's manifest.
- **`validate-image-keys.py`** — CI validator ensuring every required
  `imageOverrides` key has a corresponding digest in the bundle's
  `extras/<version>.json`.

### Konflux tooling (`scripts/konflux/`)

Compliance checking (image promotion, hermetic builds, Enterprise Contract,
multi-arch), release management (advisory creation, RHSA/RHBA/RHEA
mapping), snapshot/diff tooling for code-freeze policy enforcement,
vulnerability scanning (Trivy, OSV API), and build monitoring/notification
scripts.

### `just`-based cluster/catalog tooling

- **`scripts/custom-catalog/justfile`** — a large end-to-end pipeline
  (`e2e-catalog`, `bundle-build`, `catalog-build`) that builds a custom
  operator image, bundle image, and catalog image and pushes them to a
  personal quay.io namespace for testing. This is the concrete integration
  point that invokes an operator repo's
  `hack/bundle-automation/generate-shell.py --update-charts`.
- **`scripts/cluster-controls/`** — installs ACM/MCE onto a cluster and
  applies a custom `CatalogSource`.

### `jira-pr-cli/`

A standalone, pip-installable Python package (`jira-pr-summary`) that
generates AI (local Ollama) or template-based PR→Jira summaries, with
caching, backport detection, and QE test-case generation.

## Data / Control Flow

```
config.yaml (from config.tpl / charts-config.tpl)
  → generate-charts.py / bundles-to-charts.py
    → git clone each component repo @ branch
    → helm template  OR  read CSV install.spec
    → post-process: image overrides, namespace templating, flow control,
      security contexts, NetworkPolicy wrapping
    → output to <destination>/charts/{toggle|always}/<name>/ + crds/<name>/
```

In practice, this flow is invoked from the operator repos (via their own
`hack/bundle-automation/generate-shell.py`), or directly by developers via
the `just`-based tooling in `scripts/custom-catalog/`.

**Compliance flow (Konflux):** queries Konflux components in the
`crt-redhat-acm-tenant` tenant, checks image promotion/hermeticity/
Enterprise Contract/multi-arch status per component, and writes results to
CSV and (optionally) Jira issues via `component-squad.yaml` mapping.

## Build, Test & Release

- **No repo-level Makefile, Dockerfile, or dependency manifest** at the top
  level — this is a script collection, not a compiled artifact.
- **No `.tekton/` directory** — Tekton/Konflux pipelines live in the
  operator/component repos; this repo only reads/monitors them.
- **CI (`.github/workflows/`)**: Pylint on changed Python files, ShellCheck
  + `shfmt` on changed shell scripts, a scheduled image-mirroring workflow
  (`sync-images.yml`), and a stale-issue/PR closer.
- **Packaging**: `jira-pr-cli/setup.py` is the only formally packaged
  component (`pip install -e .`); bundle-generation scripts depend on
  `GitPython`, `PyYAML`, `coloredlogs`, `packaging`, and the external `helm`
  CLI (installed by the consuming repo, not vendored here).

## Dependencies & Integrations

- **`multiclusterhub-operator`** (ACM) and **`backplane-operator`** (MCE) —
  consume the chart-generation tooling.
- **`acm-operator-bundle`**, **`mce-operator-bundle`** — source CSVs and
  `extras/*.json` image-key data used for validation.
- **`acm-mce-operator-catalogs`** — catalog refresh target.
- **Platforms/services**: Konflux, OpenShift/Kubernetes, OLM, Azure AKS,
  quay.io (including `quay.io/acm-d`), JIRA, GitHub, Ollama (local AI).
- **External CLI tools**: `oc`, `yq`, `jq`, `skopeo`, `podman`, `helm`,
  `opm`, `operator-sdk`, `git`, `gh`, `az`, `trivy`, `jira-cli`,
  `shellcheck`, `shfmt`, `pylint`.

## Conventions & Patterns

- **Category-based layout** under `scripts/<category>/`, with per-directory
  `README.md`s and, for complex features, dedicated
  `README`/`QUICKSTART`/`CHANGELOG` docs.
- **Version-gated feature enablement**: a recurring `is_version_compatible()`
  helper (duplicated across the chart generators) changes behavior based on
  the target ACM/MCE release derived from environment variables or branch
  name.
- **Image override convention**: every container image must map to
  `{{ .Values.global.imageOverrides.<key> }}`; scripts fail hard on
  unmapped images.
- **Namespace convention**: hardcoded namespaces are rewritten to
  `{{ default "<ns>" .Values.global.namespace }}` during chart generation.
- **Dry-run-by-default**: automation that mutates configuration defaults to
  reporting-only, requiring an explicit flag to apply changes.
- **License**: Apache 2.0; DCO sign-off required on all commits.
