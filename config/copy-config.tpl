# Configuration template for move-charts.py (copy-config.yaml)
#
# Unlike config.yaml and charts-config.yaml, copy-config.yaml is a
# **root-level YAML list** — there is no top-level `components:` wrapper.
# Each entry describes a component whose pre-existing Helm chart is copied
# into the operator repo layout without post-processing.
#
# move-charts.py also accepts a dict with a `components:` key (same as
# charts-config.yaml), but the canonical form for copy-config.yaml is a
# plain list.
#
# See also: charts-config.tpl (for generate-charts.py),
#           config.tpl (for bundles-to-charts.py).

- repo_name: REPO_NAME                       # Unique identifier for the component
  github_ref: "https://github.com/org/repo.git"  # Git clone URL
  branch: TARGET_BRANCH                      # Branch to clone

  charts:
    - name: CHART_NAME                       # Chart name (used as chart directory name)
      chart-path: PATH_TO_CHART              # Relative path to the Helm chart in the cloned repo
      always-or-toggle: "toggle"             # "always" or "toggle" — chart placement category

      # --- Image mapping ---
      imageMappings:
        IMAGE_NAME: IMAGE_KEY               # Maps container image repo name → imageOverrides key

      # --- CRD path (optional) ---
      # crd-path: "config/crd/bases"         # Custom CRD path relative to repo root (default: <chart-path>/crds)

      # --- Filtering ---
      # inclusions: []                       # Glob patterns to force-include
      # escape-template-variables: []        # Strings to escape so Helm does not interpret them

      # --- Behaviour flags ---
      # skipRBACOverrides: false             # If true, skip RBAC-related Helm flow control
      # updateChartVersion: false            # If true, bump Chart.yaml version from branch
