- repo_name: REPO_NAME
  github_ref: "https://github.com/org/repo.git"
  branch: TARGET_BRANCH
  charts:
    - name: OPERATOR_NAME
      chart-path: PATH_TO_CHART
      always-or-toggle: "toggle"
      imageMappings:
        IMAGE_NAME: IMAGE_KEY  # Replace IMAGE_NAME and IMAGE_KEY with actual values
      inclusions: []  # Update if needed
      skipRBACOverrides: false
      updateChartVersion: false
      escape-template-variables: []  # Add values if necessary
