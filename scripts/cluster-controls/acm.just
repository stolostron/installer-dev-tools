acm-image := "acm-d/acm-dev-catalog:latest-2.16"
mce-image := "acm-d/mce-dev-catalog:latest-2.11"

acm-version := "release-2.16"

# Apply custom ACM catalog source with specified image
apply-custom-acm-cs IMAGE=acm-image:
    cat ./yamls/variable-acm-cs.yaml | yq '.spec.image = "quay.io:443/{{IMAGE}}"' | oc apply -f -

# Apply custom MCE catalog source with specified image
apply-custom-mce-cs IMAGE=mce-image:
    cat ./yamls/variable-mce-cs.yaml | yq '.spec.image = "quay.io:443/{{IMAGE}}"' | oc apply -f -

# Apply both custom ACM and MCE catalog sources
apply-custom-cs: apply-custom-acm-cs apply-custom-mce-cs

# Install ACM with specified version (default: release-2.16)
install-acm VERSION=acm-version:
    oc apply -f ./yamls/acm-namespace.yaml
    oc apply -f ./yamls/acm-og.yaml
    cat ./yamls/acm-subscription.yaml | yq '.spec.channel = "{{VERSION}}"' | oc apply -f -
    @echo "Sleeping for 30 seconds to wait for operator to spin up"
    sleep 30
    oc apply -f ./yamls/mch.yaml

# Enable or disable an MCE component (e.g., toggle-mce-component cluster-manager true)
toggle-mce-component COMPONENT STATE:
	oc patch mce multiclusterengine --type merge -p '{"spec":{"overrides":{"components":[{"name":"{{COMPONENT}}","enabled":{{STATE}}}]}}}'

# Apply pull secret for registry access
apply-pull-secret:
    #!/usr/bin/env bash
    set -euo pipefail

    # Try to find podman/docker auth file in standard locations
    AUTH_FILE=""
    if [[ -f "${XDG_RUNTIME_DIR}/containers/auth.json" ]]; then
        AUTH_FILE="${XDG_RUNTIME_DIR}/containers/auth.json"
    elif [[ -f "$HOME/.config/containers/auth.json" ]]; then
        AUTH_FILE="$HOME/.config/containers/auth.json"
    elif [[ -f "$HOME/.docker/config.json" ]]; then
        AUTH_FILE="$HOME/.docker/config.json"
    fi

    if [[ -z "$AUTH_FILE" ]]; then
        echo "Error: No podman/docker auth file found. Please login first with: podman login quay.io"
        exit 1
    fi

    # Extract quay.io auth token from podman auth file
    QUAY_AUTH=$(jq -r '.auths["quay.io"].auth // .auths["quay.io:443"].auth // empty' "$AUTH_FILE")

    if [[ -z "$QUAY_AUTH" ]]; then
        echo "Error: No quay.io credentials found in $AUTH_FILE"
        echo "Please login first with: podman login quay.io"
        exit 1
    fi

    # Decode to get username:password format for oc registry login
    QUAY_CREDS=$(echo "$QUAY_AUTH" | base64 -d)

    oc get secret/pull-secret -n openshift-config --template='{{{{index .data ".dockerconfigjson" | base64decode}}' >pull_secret.yaml
    oc registry login --registry="quay.io:443" --auth-basic="$QUAY_CREDS" --to=pull_secret.yaml
    oc set data secret/pull-secret -n openshift-config --from-file=.dockerconfigjson=pull_secret.yaml
    rm pull_secret.yaml

    echo "Pull secret updated successfully with quay.io credentials"
