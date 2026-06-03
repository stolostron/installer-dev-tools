# Konflux Scripts

Tools for managing Konflux component compliance, releases, vulnerability scanning, and snapshot analysis for ACM/MCE.

## Compliance

### `compliance.sh`

Check compliance status for all Konflux components in an application.

- **Inputs:** `<application>` (e.g., `acm-215`). Optional: `--debug`, `--retrigger`, `--squad=<squad>`
- **How it works:** Iterates over all `oc get components` matching the application. For each component, checks: image promotion status (via `skopeo`), hermetic builds (tekton YAML params), enterprise contract (GitHub check-runs API), multiarch support (build-platforms param), and push pipeline status.
- **Output:** CSV file at `data/<application>-compliance.csv` with per-component compliance data. Console output with color-coded status per check.
- **Auth:** Requires `oc` logged into `crt-redhat-acm-tenant`, `authorization.txt` with GitHub token, and `podman login quay.io`.
- **Dependencies:** `oc`, `skopeo`, `yq`, `jq`, `curl`

### `batch-compliance.sh`

Run `compliance.sh` for multiple applications in parallel.

- **Inputs:** One or more application names (e.g., `acm-215 mce-210`). Optional: `--debug`, `--retrigger`, `--squad=<squad>`
- **Output:** Logs in `logs/<application>-log.txt` and `logs/<application>-error.txt`

### `create-compliance-jira-issues.sh`

Create/update JIRA issues for non-compliant Konflux components.

- **Inputs:** One or more compliance CSV files or a directory. Optional: `--dry-run`, `--skip-duplicates`, `--auto-close`
- **How it works:** Parses compliance CSV output from `compliance.sh`, determines which components are non-compliant, creates JIRA bugs with detailed compliance status tables and action items. Can auto-close issues when components become compliant. Maps components to JIRA Component/s field using `component-squad.yaml`.
- **Auth:** Requires `jira-cli` configured (auto-initializes from env vars `JIRA_API_TOKEN`, `JIRA_AUTH_TYPE`).
- **Dependencies:** `jira` (jira-cli), `jq`

### `component-squad.yaml`

YAML config mapping Konflux component names to squad ownership and JIRA component names. Used by `compliance.sh` (squad filtering) and `create-compliance-jira-issues.sh` (JIRA component assignment).

## Releases

### `release-manager.sh`

Create, apply, and monitor ACM/MCE Konflux release YAML files.

- **Subcommands:**
  - `create <ACM|MCE> <version> [rc_count]` — Generate payload, bundle, and catalog release YAML files for prod and RCs
  - `apply <release_file> [--watch]` — Apply a release via `oc create` and optionally monitor the PipelineRun
  - `watch <release_name>` — Monitor an existing release PipelineRun
  - `update-advisory <version> [target] [custom-jql]` — Update payload file with bug fixes and CVEs from JIRA (calls `update-advisory.py`)
- **Dependencies:** `oc`, `jq`, `python3` (for update-advisory)

### `update-advisory.py`

Python script called by `release-manager.sh update-advisory`. Updates release payload YAML with CVE and bug fix data from JIRA queries.

## Snapshot & Diff Tools

### `konflux-snapshot-difftool.sh`

Compare component diffs between two Konflux tags or snapshots.

- **Inputs:** `-v <semantic-version>` (e.g., `acm-2.14.1`), plus exactly two tags (`-t`) and/or snapshots (`-s`)
- **How it works:** Renders both catalog tags via `opm`, maps images to Konflux component names, finds revisions by walking `latest-snapshot.yaml` git history, then generates GitHub compare diffs per component. Also looks up PR info for each commit.
- **Output:** Per-component `.diff` files in `diffs/` directory with repo URL, diff URL, commit list with PR references, and full patch content.
- **Dependencies:** `opm`, `oc`, `yq`, `jq`, `curl`, `base64`

### `analyze-diffs.sh`

Analyze diffs from `konflux-snapshot-difftool.sh` for code freeze policy violations.

- **Inputs:** `--mode <feature-complete|code-lockdown>`. Optional: `--verbose`, `--format <text|json|csv>`
- **How it works:** Reads `.diff` files from `diffs/` directory, classifies each changed file (dependency, test, build, doc, or product code), and flags violations based on the development phase mode.
- **Output:** Per-component violation/warning/clean status with file-level detail.

### `split_snapshot.py`

Split a multi-component Konflux Snapshot YAML into individual per-component snapshot files.

- **Inputs:** `<input_snapshot.yaml> [output_directory]`
- **Output:** One `snapshot-<component>.yaml` file per component.

## Catalog & Build Management

### `rebuild-component.sh`

Trigger a PAC rebuild for one or more Konflux components.

- **Inputs:** Space-separated component names
- **How it works:** Annotates each component with `build.appstudio.openshift.io/request=trigger-pac-build`
- **Dependencies:** `oc`

### `refresh-catalog.sh`

Trigger a catalog rebuild by pushing a timestamp update to the `acm-mce-operator-catalogs` repo.

- **Inputs:** Optional catalog branch name(s) (default: `acm-redhat-operators` and `mce-redhat-operators`)
- **How it works:** Clones `acm-mce-operator-catalogs`, updates `catalog-request.yaml` with current timestamp, commits and pushes a new branch.
- **Dependencies:** `git`, `yq`

### `check-component-promotions.sh`

Check promotion status and build dates for all Konflux components in a release.

- **Inputs:** `<release>` (e.g., `mce-29`)
- **How it works:** Iterates over `oc get components`, inspects each promoted image via `skopeo` to get build dates.
- **Output:** Timestamped log, promotion, and status files.
- **Dependencies:** `oc`, `skopeo`, `jq`

### `get-catalogs-from-release.sh`

Extract catalog index images from a Konflux Release resource.

- **Inputs:** One or more release names
- **How it works:** `oc get release <name>` and extracts `index_image` per OCP version from `.status.artifacts.components`.
- **Dependencies:** `oc`, `yq`

### `get-catalogs-from-fbc-iib-log.sh`

Parse FBC/IIB log files to extract catalog image references.

- **Inputs:** `<logfile>`
- **How it works:** Greps for `Updated fromIndex for next batch:` entries in the log.

### `exception-request.sh`

Generate exception request entries for a Konflux snapshot's container images.

- **Inputs:** `<snapshot-yaml-file>`
- **How it works:** Reads snapshot YAML, iterates over container images, uses `skopeo inspect --raw` to get per-arch manifests, and outputs YAML entries for `schedule.weekday_restriction` exceptions.
- **Dependencies:** `yq`, `skopeo`, `jq`

## Vulnerability Scanning

### `scan-cluster-vulnerabilities.sh`

Scan all container images in an OpenShift cluster using Trivy.

- **Inputs:** Optional: `-n <namespace>`, `-s <severity>`, `-f <format>`, `-i <image-filter>`, `--detailed`
- **How it works:** Discovers all unique images from pods via `oc get pods`, scans each with Trivy, aggregates results.
- **Output:** Summary report (text + JSON) and detailed CVE CSV in `vulnerability-reports/`.
- **Dependencies:** `oc`, `trivy` (auto-installs if missing), `jq`

### `scan-stolostron-vulnerabilities.sh`

Scan all active `stolostron` GitHub repositories for Go dependency vulnerabilities.

- **How it works:** Lists all non-archived repos via `gh`, downloads `go.mod` files, queries the OSV API for each dependency, filters by CVSS >= 4.0.
- **Output:** JSON results file and text summary with per-repo vulnerability details.
- **Dependencies:** `gh`, `jq`, `curl`

### `list-cves-for-version.sh`

List CVEs fixed in a specific ACM/MCE version by querying JIRA.

- **Inputs:** `"<application> <version>"` (e.g., `"acm 2.14.2"`). Optional: `-oyaml`
- **How it works:** Queries JIRA for Weakness/Vulnerability issues with matching fixVersion, cross-references with the manifest gen config to map CVEs to Konflux component names.
- **Output:** YAML mapping CVE IDs to affected components.
- **Dependencies:** `jira` (jira-cli), `jq`, `yq`, `curl`

### `analyze_vulnerabilities.py` / `analyze_vulnerabilities.sh`

Python-based vulnerability analysis tooling. See `README-vulnerability-scanner.md` for details.

## Monitoring

### `konflux-build-monitor-v2.py` / `konflux-build-monitor-v3.py`

Python-based Konflux build monitoring. These are more advanced versions of build monitoring with richer output and tracking.
