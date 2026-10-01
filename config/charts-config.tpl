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
      # Subscription fields of any OperatorPolicy embedded in this chart's
      # AddOnTemplate that should be templated into .Values.global.<key> even
      # when the upstream chart does not set them. Fields the upstream chart
      # does set are always templated; these are for fields it omits, such as
      # 'source', 'sourceNamespace' or 'startingCSV'. Each one is seeded with
      # an empty default, which the OperatorPolicy controller reads as
      # "inherit the default" from the Subscription it finds on the cluster.
      # The values key is derived from the OperatorPolicy name, so a new
      # component needs no mapping here.
      operatorPolicySubscriptionFields: []
