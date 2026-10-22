# Configuration template for generate-charts.py / move-charts.py (charts-config.yaml)
#
# Each top-level entry describes a component repository whose pre-existing
# Helm chart is post-processed and copied into the operator repo layout.
# The file is a YAML list; add one entry per component.
#
# See also: config.tpl (for bundles-to-charts.py).

- repo_name: REPO_NAME                       # Unique identifier for the component
  github_ref: "https://github.com/org/repo.git"  # Git clone URL
  branch: TARGET_BRANCH                      # Branch to clone

  charts:
    - name: OPERATOR_NAME                    # Chart name (used as chart directory name)
      chart-path: PATH_TO_CHART              # Relative path to the Helm chart in the cloned repo
      always-or-toggle: "toggle"             # "always" or "toggle" — chart placement category

      # --- Image mapping ---
      imageMappings:
        IMAGE_NAME: IMAGE_KEY               # Maps container image repo name → imageOverrides key
      # envImageMappings:                    # Maps env var name → imageOverrides key for non-_IMAGE vars
      #   DATABASE_IMAGE_PG15: postgresql_15

      # --- Filtering ---
      inclusions: []                         # Glob patterns to force-include
      escape-template-variables: []          # Strings to escape so Helm does not interpret them

      # --- Behaviour flags ---
      skipRBACOverrides: false               # If true, skip RBAC-related Helm flow control
      updateChartVersion: false              # If true, bump Chart.yaml version from branch

      # --- Security ---
      # security-context-constraints: []     # SCC names to inject into the chart

      # --- OperatorPolicy subscription templating ---
      # Subscription fields of any OperatorPolicy embedded in this chart's
      # AddOnTemplate that should be templated into .Values.global.<key> even
      # when the upstream chart does not set them.  Fields the upstream chart
      # does set are always templated; list here only fields it omits, such as
      # 'source', 'sourceNamespace', or 'startingCSV'.  Each is seeded with an
      # empty default ("inherit the cluster default").  The values key is
      # derived from the OperatorPolicy metadata.name — no extra mapping needed.
      operatorPolicySubscriptionFields: []
