# Configuration template for bundles-to-charts.py (config.yaml)
#
# Each top-level entry describes a component repository whose OLM bundle
# is converted into a Helm chart.  The file is a YAML list; add one entry
# per component.
#
# See also: charts-config.tpl (for generate-charts.py / move-charts.py).

- repo_name: REPO_NAME                       # Unique identifier for the component
  github_ref: "https://github.com/org/repo.git"  # Git clone URL
  branch: TARGET_BRANCH                      # Branch to clone

  # --- Optional repo-level keys (used by gen_command flow) ---
  # gen_command: "./hack/generate-bundle.sh"  # Shell command to generate the bundle
  # git_remote: "https://github.com/org/repo.git"  # Remote for SHA lookup (defaults to github_ref)
  # sha: "abc123..."                          # Pinned commit SHA (overrides git_remote lookup)

  operators:
    - name: OPERATOR_NAME                    # Operator name (used as chart directory name)
      bundlePath: PATH_TO_BUNDLE             # Relative path to the OLM bundle inside the cloned repo

      # --- Optional: OLM channel selection ---
      # channel: "stable"                    # OLM channel to select when multiple exist
      # bundles-directory: "bundles/"        # Directory containing versioned bundles

      # --- Image mapping ---
      imageMappings:
        IMAGE_NAME: IMAGE_KEY               # Maps container image repo name → imageOverrides key
      # envImageMappings:                    # Maps env var name → imageOverrides key for non-_IMAGE vars
      #   DATABASE_IMAGE_PG15: postgresql_15

      # --- Filtering ---
      exclusions: []                         # Glob patterns of resources to exclude
      inclusions: []                         # Glob patterns to force-include (overrides exclusions)
      escape-template-variables: []          # Strings to escape so Helm does not interpret them

      # --- Behaviour flags ---
      skipRBACOverrides: false               # If true, skip RBAC-related Helm flow control
      # updateChartVersion: false            # (Unused by bundles-to-charts.py — see charts-config.tpl)

      # --- Webhook & file preservation ---
      # webhook_paths:                       # Relative paths to webhook manifests to inline
      #   - "config/webhook/manifests.yaml"
      # preserve_files:                      # Files to keep when regenerating the chart directory
      #   - "values.yaml"

      # --- Security ---
      # security-context-constraints: []     # SCC names to inject into the chart
