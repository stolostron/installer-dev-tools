#!/bin/bash
set -euo pipefail

# Color definitions
CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
MAGENTA='\033[0;35m'
BOLD='\033[1m'
RESET='\033[0m'

# Display help message
show_help() {
    cat << EOF
Usage: $(basename "$0") [OPTIONS] [BUNDLE_TAG]

Get VCS refs for Hive images from multicluster-engine operator bundle.

Arguments:
    BUNDLE_TAG      Bundle version tag (default: v2.10)

Options:
    -h, --help      Show this help message
    -oyaml          Output only YAML (suppress all progress messages)

Examples:
    $(basename "$0")            # Use default bundle tag (v2.10) with colored output
    $(basename "$0") v2.11      # Specify bundle tag
    $(basename "$0") -oyaml     # YAML output only, no colors or progress
    $(basename "$0") -oyaml v2.10  # YAML only with specific bundle tag

Requirements:
    - Logged into registry.redhat.io (run: podman login registry.redhat.io)
    - podman, yq, and skopeo must be installed
EOF
    exit 0
}

# Check for help flag
if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    show_help
fi

# Parse arguments
YAML_ONLY=false
BUNDLE_TAG=""

for arg in "$@"; do
    case "$arg" in
        -oyaml)
            YAML_ONLY=true
            ;;
        *)
            BUNDLE_TAG="$arg"
            ;;
    esac
done

# Set default if not provided
BUNDLE_TAG=${BUNDLE_TAG:-v2.10}

# Helper function to print messages only when not in YAML-only mode
log() {
    if [[ "$YAML_ONLY" == "false" ]]; then
        echo -e "$@" >&2
    fi
}

# Create temporary directory
TMP_DIR=$(mktemp -d)

# Cleanup tmp directory on exit
trap 'rm -rf "${TMP_DIR}"' EXIT

# Check if logged into registry.redhat.io
if ! podman login --get-login registry.redhat.io &>/dev/null; then
    log "${RED}❌ Error: Not logged into registry.redhat.io${RESET}"
    log "${YELLOW}💡 Please run: ${CYAN}podman login registry.redhat.io${RESET}"
    exit 1
fi

# Pull the bundle image
log "${CYAN}🔍 Fetching bundle ${BOLD}${BUNDLE_TAG}${RESET}"
BUNDLE_IMAGE="registry.redhat.io/multicluster-engine/mce-operator-bundle:${BUNDLE_TAG}"

podman create --replace --name temp-bundle "${BUNDLE_IMAGE}" >/dev/null 2>&1 || {
    log "${RED}❌ Failed to pull bundle ${BUNDLE_TAG}${RESET}"
    exit 1
}

podman cp temp-bundle:/manifests "${TMP_DIR}/" 2>/dev/null
podman rm temp-bundle >/dev/null
log "${GREEN}✓ Bundle extracted${RESET}"

# Find the CSV file and extract hive image
log "${BLUE}🔎 Parsing ClusterServiceVersion${RESET}"
csv_file=$(find "${TMP_DIR}" -name "*.clusterserviceversion.yaml" -type f)

if [[ ! -f "$csv_file" ]]; then
    log "${RED}❌ No ClusterServiceVersion found in bundle${RESET}"
    exit 1
fi

# Extract the hive image from the CSV
image=$(yq '.spec.relatedImages[] | select(.name == "openshift_hive") | .image' "$csv_file" 2>/dev/null)

if [[ -z "$image" ]]; then
    log "${RED}❌ No hive image found in bundle${RESET}"
    exit 1
fi

log "${GREEN}✓ Found hive image${RESET}"
log "\n${BOLD}${MAGENTA}📦 Hive Image VCS Reference${RESET}\n"

# Get the vcs-ref from the image, with fallback to quay.io
vcs_ref=$(skopeo inspect --no-tags --format '{{json .Labels}}' "docker://$image" 2>/dev/null | jq -r '."vcs-ref"' || {
    # If it fails, try quay.io/acm-d instead (replace everything before the image name)
    fallback_image=$(echo "$image" | sed 's|.*/\([^/]*\)$|quay.io/acm-d/\1|')
    log "${YELLOW}⚠️  Falling back to ${CYAN}$fallback_image${RESET}"
    skopeo inspect --no-tags --format '{{json .Labels}}' "docker://$fallback_image" | jq -r '."vcs-ref"'
})

# Output format
if [[ "$YAML_ONLY" == "true" ]]; then
    # Proper YAML format
    echo "bundle: $BUNDLE_TAG"
    echo "image: $image"
    echo "sha: $vcs_ref"
else
    # Colorful free-form output
    echo -e "${GREEN}bundle: ${BOLD}$BUNDLE_TAG${RESET}"
    echo -e "${CYAN}image: ${RESET}$image"
    echo -e "${MAGENTA}sha: ${RESET}$vcs_ref"
fi

log "\n${GREEN}✨ Done!${RESET}\n"
