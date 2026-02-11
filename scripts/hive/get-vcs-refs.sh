#!/bin/bash
set -euo pipefail

# Get script directory
SCRIPT_DIR="$(dirname "$(realpath "${BASH_SOURCE[0]}")")"

# Parse arguments
OCP_VERSION=${1:-v4.21}
OPERATOR_NAME=${2:-multicluster-engine}

# Cleanup tmp directory on exit
trap 'rm -rf "${SCRIPT_DIR}/tmp"' EXIT

# Check if logged into registry.redhat.io
if ! podman login --get-login registry.redhat.io &>/dev/null; then
    echo "Error: Not logged into registry.redhat.io. Please run: podman login registry.redhat.io" >&2
    exit 1
fi

# Extract catalog data from OLM index image
podman create --replace --name temp-catalog registry.redhat.io/redhat/redhat-operator-index:${OCP_VERSION}
mkdir -p "${SCRIPT_DIR}/tmp"
podman cp temp-catalog:/configs/${OPERATOR_NAME} "${SCRIPT_DIR}/tmp/"
podman rm temp-catalog

# Get the list of versions and images from bundles.yaml
images=$(cat "${SCRIPT_DIR}/tmp/${OPERATOR_NAME}/bundles.json" | jq '[{"version": .name, "image": (.relatedImages[] | select(.name == "openshift_hive") | .image)}]')

echo "---"
# Process each entry
echo "$images" | jq -c '.[]' | while read -r entry; do
    version=$(echo "$entry" | jq -r '.version')
    image=$(echo "$entry" | jq -r '.image')

    # echo "Processing $version..." >&2
    # echo "With image: $image"

    # Get the vcs-ref from the image, with fallback to quay.io
    vcs_ref=$(skopeo inspect --no-tags --format '{{json .Labels}}' "docker://$image" 2>/dev/null | jq -r '."vcs-ref"' || {
        # If it fails, try quay.io/acm-d instead (replace everything before the image name)
        fallback_image=$(echo "$image" | sed 's|.*/\([^/]*\)$|quay.io/acm-d/\1|')
        echo "Falling back to $fallback_image..." >&2
        skopeo inspect --no-tags --format '{{json .Labels}}' "docker://$fallback_image" | jq -r '."vcs-ref"'
    })

    # Output in YAML format
    echo "- version: $version"
    echo "  image: $image"
    echo "  sha: $vcs_ref"
done

echo "---"
