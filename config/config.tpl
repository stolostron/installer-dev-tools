- repo_name: REPO_NAME
  github_ref: "https://github.com/org/repo.git"
  branch: TARGET_BRANCH
  operators:
    - name: OPERATOR_NAME
      bundlePath: PATH_TO_BUNDLE
      escape-template-variables: []  # Add values if necessary
      imageMappings:
        IMAGE_NAME: IMAGE_KEY  # Replace IMAGE_NAME and IMAGE_KEY with actual values
      exclusions: []  # Update if needed
      inclusions: []  # Update if needed
      skipRBACOverrides: false
      updateChartVersion: false
