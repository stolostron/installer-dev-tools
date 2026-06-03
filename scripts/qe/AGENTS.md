# QE Scripts

Tools for checking whether PRs have landed in downstream builds and monitoring Konflux build status.

## Scripts

### `konflux-pr-downstream-status.sh`

Check if GitHub PRs are included in a downstream Konflux build. Accepts either a catalog tag or a Konflux snapshot as input.

- **Inputs:** `-a <application>` (e.g., `acm-215`), `-t <tag>` or `-s <snapshot>`, one or more PR URLs
- **How it works:** Renders the catalog via `opm`, looks up the component image from `acm-config/component-registry.yaml`, inspects the image via `skopeo` to get the `vcs-ref` label, then compares the PR's merge commit SHA against the published SHA using the GitHub compare API.
- **Output:** Color-coded status per PR — 🟩 in build, 🟥 not in build, 🟪 diverged, 🟨 error
- **Auth:** Uses `gh` CLI for GitHub API (no manual token needed). Requires `podman login quay.io`. Snapshot mode requires `oc` logged into `crt-redhat-acm-tenant`.
- **Dependencies:** `opm`, `skopeo`, `yq`, `jq`, `gh`, `podman`

### `konflux-build-notification.sh`

Monitor for new ACM/MCE Konflux builds and report what changed.

- **Inputs:** None (runs standalone)
- **How it works:** Uses `skopeo` to check latest catalog tags on `quay.io/acm-d/`, compares against locally recorded tags in `latest-acm.txt`/`latest-mce.txt`, then pulls both catalogs and diffs the image summaries.
- **Output:** Lists all images and SHAs in the current build, plus a diff showing what changed since the last build.
- **Dependencies:** `skopeo` (recommended), `podman`, `yq`

### `konflux-build-status.sh`

Extract image information from a specific catalog build.

- **Inputs:** `<catalog-image>` `<tag>` (e.g., `acm-dev-catalog latest-2.14`)
- **How it works:** Pulls the catalog image via `podman`, extracts `bundles.yaml`, and parses out all related images with their SHAs.
- **Output:** Files in `./tmp/` — `*-bundles.yaml`, `*-repos.txt`, `*-summary.txt`
- **Dependencies:** `podman`, `yq`

### `pr-downstream-status.sh` (Legacy — CPaaS)

Legacy version of the PR checker that uses CPaaS/GitLab `down-sha.log` files instead of Konflux. Only works with the old CPaaS build system.

- **Auth:** Requires `authorization.txt` with a GitHub token.

### `pr-downstream-status.py` (Legacy — CPaaS)

Python version of the CPaaS PR checker. Has a stub `Konflux` class but it is not fully implemented. Use `konflux-pr-downstream-status.sh` instead.

- **Dependencies:** `requests`, `pyyaml` (see `requirements.txt`)
