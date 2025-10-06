#!/bin/bash
# Set up file descriptor 3 for output messages
exec 3>&1
# Cache for gen_config to avoid repeated fetches
declare gen_config_cache=""

# Get script directory
SCRIPT_DIR="$(cd "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
mkdir -p -- "$SCRIPT_DIR/diffs"
mkdir -p -- "$SCRIPT_DIR/cache"

# Debug output function
debug_echo() {
  if [ "$debug" = true ]; then
    echo "$@" >&3
  fi
}

# Help function
show_help() {
  local script_name=$(basename "$0")
  cat << EOF
Usage: $script_name -v|--semantic-version VERSION [OPTIONS] INPUTS

Compare Konflux component diffs between two tags or snapshots.

Required Arguments:
  -v, --semantic-version VERSION    Semantic version (e.g., acm-2.14.1)

Input Arguments (exactly 2 required):
  -t, --tag TAG                     Tag name (e.g., 2.14.1-DOWNSTREAM-2025-09-29-02-19-47)
  -s, --snapshot SNAPSHOT           Snapshot name (e.g., release-acm-214-czrhh)

  Valid combinations:
    - Two tags:              -t TAG1 -t TAG2
    - Two snapshots:         -s SNAPSHOT1 -s SNAPSHOT2
    - One tag + snapshot:    -t TAG -s SNAPSHOT

Optional Arguments:
  --force-opm-render                Force re-rendering of catalog YAML files (default: use cached)
  --debug                           Enable debug output
  -h, --help                        Show this help message

Examples:
  # Compare two tags
  $script_name -v acm-2.14.1 -t 2.14.1-DOWNSTREAM-2025-09-29-02-19-47 -t 2.14.1-DOWNSTREAM-2025-10-01-02-19-43

  # Compare two snapshots
  $script_name -v acm-2.14.1 -s release-acm-214-n7bvs -s release-acm-214-9q65c

  # Compare tag with snapshot
  $script_name -v acm-2.14.1 -t 2.14.1-DOWNSTREAM-2025-09-29-02-19-47 -s release-acm-214-n7bvs

  # Force re-render cached files
  $script_name -v acm-2.14.1 -t TAG1 -t TAG2 --force-opm-render

EOF
}

# Initialize arrays and variables
tags=()
snapshots=()
version=""
debug=false
force_opm_render=false

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -v|--semantic-version)
            version="$2"
            shift 2
            ;;
        -t|--tag)
            tags+=("$2")
            shift 2
            ;;
        -s|--snapshot)
            snapshots+=("$2")
            shift 2
            ;;
        --debug)
            debug=true
            shift
            ;;
        --force-opm-render)
            force_opm_render=true
            shift
            ;;
        -h|--help)
            show_help
            exit 0
            ;;
        *)
            echo "Error: Unknown option: $1"
            echo ""
            show_help
            exit 1
            ;;
    esac
done

auth_check_failures=0

authorization=""
if [ -f "$SCRIPT_DIR/authorization.txt" ]; then
	authorization="Authorization: Bearer $(cat "$SCRIPT_DIR/authorization.txt")"
	echo "🛈 Authorization found. Applying to github API requests"
else
    echo "Error: authorization.txt not found"
    echo "Please create $SCRIPT_DIR/authorization.txt with your GitHub token"
    echo "github.com > settings > developer settings > personal access tokens > fine-grained personal access tokens"
    ((auth_check_failures++))
fi

# Check that we're in the correct OpenShift project
echo "Checking OpenShift project..."
oc_project_output=$(oc project 2>&1)
if [[ ! "$oc_project_output" == *"Using project \"crt-redhat-acm-tenant\""* ]]; then
    echo "Error: Not in the correct OpenShift project."
    echo "Expected: Using project \"crt-redhat-acm-tenant\""
    echo "Got: $oc_project_output"
    ((auth_check_failures++))
else
    echo "Verified: Correct OpenShift project selected (crt-redhat-acm-tenant)"
fi

# Check that we're logged into quay.io
echo "Checking quay.io login..."
if ! podman login --get-login quay.io &>/dev/null; then
    echo "Error: Not logged into quay.io"
    echo "Please run: podman login quay.io"
    ((auth_check_failures++))
else
    echo "Verified: Logged into quay.io"
fi

# Exit if any auth checks failed
if [ $auth_check_failures -ne 0 ]; then
    exit 1
fi

# Validate inputs
if [ -z "$version" ]; then
    echo "Error: --semantic-version is required"
    echo ""
    show_help
    exit 1
fi

# Validate tag/snapshot combinations
total_inputs=$((${#tags[@]} + ${#snapshots[@]}))
if [ $total_inputs -ne 2 ]; then
    echo "Error: Exactly 2 inputs required (tags and/or snapshots combined)"
    echo ""
    show_help
    exit 1
fi

# Valid combinations: 2 tags, 2 snapshots, or 1 tag + 1 snapshot
if [ ${#tags[@]} -eq 2 ] && [ ${#snapshots[@]} -eq 0 ]; then
    # Two tags
    tag_a="${tags[0]}"
    tag_b="${tags[1]}"
elif [ ${#tags[@]} -eq 0 ] && [ ${#snapshots[@]} -eq 2 ]; then
    # Two snapshots
    snapshot_a="${snapshots[0]}"
    snapshot_b="${snapshots[1]}"
elif [ ${#tags[@]} -eq 1 ] && [ ${#snapshots[@]} -eq 1 ]; then
    # One tag and one snapshot
    tag_a="${tags[0]}"
    snapshot_b="${snapshots[0]}"
else
    echo "Error: Invalid combination. Must be either: 2 tags, 2 snapshots, or 1 tag + 1 snapshot"
    echo ""
    show_help
    exit 1
fi

debug_echo "Tag A: $tag_a"
debug_echo "Tag B: $tag_b"
debug_echo "Snapshot A: $snapshot_a"
debug_echo "Snapshot B: $snapshot_b"
debug_echo "Version: $version"
application_part=$(echo "$version" | cut -d'-' -f1)
version_number=$(echo "$version" | cut -d'-' -f2)
major_version=$(echo "$version_number" | cut -d'.' -f1)
minor_version=$(echo "$version_number" | cut -d'.' -f2)
patch_version=$(echo "$version_number" | cut -d'.' -f3)
application="$application_part-$major_version$minor_version"

# Handle different application types
if [ "$application_part" = "acm" ]; then
  snapshot_branch="release-$major_version.$minor_version"
else
  snapshot_branch="backplane-$major_version.$minor_version"
fi

latest_snapshot_url="https://raw.githubusercontent.com/stolostron/$application_part-operator-bundle/refs/heads/$snapshot_branch/latest-snapshot.yaml"

debug_echo "Application Part: $application_part"
debug_echo "Version Number: $version_number"
debug_echo "Major Version: $major_version"
debug_echo "Minor Version: $minor_version"
debug_echo "Patch Version: $patch_version"

if [ "$application_part" = "acm" ]; then
  csv_name="advanced-cluster-management.v$version_number"
else
  csv_name="multicluster-engine.v$version_number"
fi

debug_echo "CSV Name: $csv_name"

# Load images based on input type
if [ -n "$tag_a" ]; then
    tag_a_file="$SCRIPT_DIR/cache/${tag_a}.cs.yaml"
    if [ "$force_opm_render" = true ] || [ ! -f "$tag_a_file" ] || [ ! -s "$tag_a_file" ]; then
        echo "🛈 Rendering $application_part-dev-catalog:$tag_a"
        opm render quay.io/acm-d/$application_part-dev-catalog:$tag_a --migrate -oyaml > "$tag_a_file"
    else
        echo "🛈 Using cached $tag_a_file"
    fi
    tag_a_images=$(cat "$tag_a_file" | yq "select(.name | contains(\"$csv_name\")) | .relatedImages[].image")
fi

if [ -n "$tag_b" ]; then
    tag_b_file="$SCRIPT_DIR/cache/${tag_b}.cs.yaml"
    if [ "$force_opm_render" = true ] || [ ! -f "$tag_b_file" ] || [ ! -s "$tag_b_file" ]; then
        echo "🛈 Rendering $application_part-dev-catalog:$tag_b"
        opm render quay.io/acm-d/$application_part-dev-catalog:$tag_b --migrate -oyaml > "$tag_b_file"
    else
        echo "🛈 Using cached $tag_b_file"
    fi
    tag_b_images=$(cat "$tag_b_file" | yq "select(.name | contains(\"$csv_name\")) | .relatedImages[].image")
fi

if [ -n "$snapshot_a" ]; then
    snapshot_a_cache=$(oc get snapshot "$snapshot_a" -oyaml)
    snapshot_a_images=$(echo "$snapshot_a_cache" | yq '.spec.components[].containerImage')
fi

if [ -n "$snapshot_b" ]; then
    snapshot_b_cache=$(oc get snapshot "$snapshot_b" -oyaml)
    snapshot_b_images=$(echo "$snapshot_b_cache" | yq '.spec.components[].containerImage')
fi

latest_snapshot_cache=$(curl -Ls "$latest_snapshot_url")

function github_api_call() {
  local url="$1"
  local accept_header="${2:-application/vnd.github+json}"

  curl -LsH "Accept: $accept_header" \
    -H "X-GitHub-Api-Version: 2022-11-28" \
    -H "$authorization" \
    "$url"
}

function get_gen_config() {
  local application_part="$1"
  local snapshot_branch="$2"

  if [[ -z "$gen_config_cache" ]]; then
    gen_config_cache=$(curl -Ls "https://raw.githubusercontent.com/stolostron/$application_part-operator-bundle/refs/heads/$snapshot_branch/config/$application_part-manifest-gen-config.json")
  fi
  echo "$gen_config_cache"
}

function get_konflux_component_name() {
  local publish_name="$1"
  get_gen_config "$application_part" "$snapshot_branch" | yq ".product-images.image-list[] | select(.publish-name == \"$publish_name\") | .konflux-component-name"
}

function get_revision_for_image {
  local image="$1"
  local repo_owner="stolostron"
  local repo_name="$application_part-operator-bundle"

  debug_echo "Looking up revision for image: $image"

  # Get commit history for latest-snapshot.yaml
  local commits_url="https://api.github.com/repos/$repo_owner/$repo_name/commits?path=latest-snapshot.yaml&sha=$snapshot_branch"
  local commits=$(github_api_call "$commits_url")

  # Check each commit until we find the image
  echo "$commits" | jq -r '.[].sha' | while read commit_sha; do
    debug_echo "Checking commit: $commit_sha"

    # Get file content at this commit
    local file_url="https://api.github.com/repos/$repo_owner/$repo_name/contents/latest-snapshot.yaml?ref=$commit_sha"
    local file_content=$(github_api_call "$file_url" | jq -r '.content' | base64 -d)

    # Check if image exists in this version
    local found_revision=$(echo "$file_content" | yq ".spec.components[] | select(.containerImage | contains(\"$image\")) | .source.git.revision")

    if [ -n "$found_revision" ] && [ "$found_revision" != "null" ]; then
        debug_echo "Found Revision: $found_revision"
        echo "$found_revision"
        return
    fi
  done
}

function calculate_konflux_image() {
  local image=$(basename $1 | cut -d'@' -f1)
  local sha=$(basename $1 | cut -d'@' -f2)

  local konflux_name=$(get_konflux_component_name "$image")

  if [[ -z $konflux_name ]]; then return; fi
  debug_echo "Image: $image"
  debug_echo "Konflux Image: $konflux_name"
  debug_echo "SHA: $sha"

  local c_image="$konflux_name-$application@$sha"

  debug_echo "Calculated Image: $c_image"

  echo "$c_image"
}

# Prepare images for comparison based on input type
if [ -n "$tag_a" ] && [ -n "$tag_b" ]; then
    # Two tags: convert both to konflux images
    images_a=$(echo "$tag_a_images" | while read img; do
        result=$(calculate_konflux_image "$img")
        echo "${result:-__EMPTY__}"
    done | awk '$1 != "__EMPTY__"')

    images_b=$(echo "$tag_b_images" | while read img; do
        result=$(calculate_konflux_image "$img")
        echo "${result:-__EMPTY__}"
    done | awk '$1 != "__EMPTY__"')

elif [ -n "$snapshot_a" ] && [ -n "$snapshot_b" ]; then
    # Two snapshots: extract images directly
    images_a=$(echo "$snapshot_a_images" | cut -d'/' -f4)
    images_b=$(echo "$snapshot_b_images" | cut -d'/' -f4)

elif [ -n "$tag_a" ] && [ -n "$snapshot_b" ]; then
    # One tag and one snapshot: convert tag to konflux, extract snapshot
    images_a=$(echo "$tag_a_images" | while read img; do
        result=$(calculate_konflux_image "$img")
        echo "${result:-__EMPTY__}"
    done | awk '$1 != "__EMPTY__"')

    images_b=$(echo "$snapshot_b_images" | cut -d'/' -f4)
fi

# Compare images
image_diffs=$(paste <(echo "$images_a" | sort) <(echo "$images_b" | sort) | awk '$1 != $2')

debug_echo "--- Image Diffs ---"
debug_echo "$image_diffs"
debug_echo ""

# Get revisions and URLs based on input type
if [ -n "$tag_a" ] && [ -n "$tag_b" ]; then
    # Two tags: lookup revisions from git history
    debug_echo "--- Revisions From Tag A ---"
    revisions_a=$(echo "$image_diffs" | awk '{print $1}' | while read img; do
        result=$(get_revision_for_image "$img")
        echo "${result:-__NOT_FOUND__}"
    done)

    debug_echo "--- Revisions From Tag B ---"
    revisions_b=$(echo "$image_diffs" | awk '{print $2}' | while read img; do
        result=$(get_revision_for_image "$img")
        echo "${result:-__NOT_FOUND__}"
    done)

    urls=$(echo "$image_diffs" | awk '{print $2}' | while read img; do
        img_name=$(echo "$img" | cut -d'@' -f1)
        result=$(echo "$latest_snapshot_cache" | yq ".spec.components[] | select(.containerImage | contains(\"$img_name\")).source.git.url")
        echo "$result"
    done)

elif [ -n "$snapshot_a" ] && [ -n "$snapshot_b" ]; then
    # Two snapshots: extract revisions directly from snapshot yaml
    debug_echo "--- Revisions From Snapshot A ---"
    revisions_a=$(echo "$image_diffs" | awk '{print $1}' | while read img; do
        img_name=$(echo "$img" | cut -d'@' -f1)
        result=$(echo "$snapshot_a_cache" | yq ".spec.components[] | select(.containerImage | contains(\"$img_name\")).source.git.revision")
        echo "$result"
    done)

    debug_echo "--- Revisions From Snapshot B ---"
    revisions_b=$(echo "$image_diffs" | awk '{print $2}' | while read img; do
        img_name=$(echo "$img" | cut -d'@' -f1)
        result=$(echo "$snapshot_b_cache" | yq ".spec.components[] | select(.containerImage | contains(\"$img_name\")).source.git.revision")
        echo "$result"
    done)

    urls=$(echo "$image_diffs" | awk '{print $2}' | while read img; do
        img_name=$(echo "$img" | cut -d'@' -f1)
        result=$(echo "$snapshot_b_cache" | yq ".spec.components[] | select(.containerImage | contains(\"$img_name\")).source.git.url")
        echo "$result"
    done)

elif [ -n "$tag_a" ] && [ -n "$snapshot_b" ]; then
    # One tag and one snapshot: lookup tag revision, extract snapshot revision
    debug_echo "--- Revisions From Tag A ---"
    revisions_a=$(echo "$image_diffs" | awk '{print $1}' | while read img; do
        result=$(get_revision_for_image "$img")
        echo "${result:-__NOT_FOUND__}"
    done)

    debug_echo "--- Revisions From Snapshot B ---"
    revisions_b=$(echo "$image_diffs" | awk '{print $2}' | while read img; do
        img_name=$(echo "$img" | cut -d'@' -f1)
        result=$(echo "$snapshot_b_cache" | yq ".spec.components[] | select(.containerImage | contains(\"$img_name\")).source.git.revision")
        echo "$result"
    done)

    urls=$(echo "$image_diffs" | awk '{print $2}' | while read img; do
        img_name=$(echo "$img" | cut -d'@' -f1)
        result=$(echo "$snapshot_b_cache" | yq ".spec.components[] | select(.containerImage | contains(\"$img_name\")).source.git.url")
        echo "$result"
    done)
fi

debug_echo "--- Revisions A ---"
debug_echo "$revisions_a"
debug_echo ""

debug_echo "--- Revisions B ---"
debug_echo "$revisions_b"
debug_echo ""

revision_diffs=$(paste <(echo "$urls") <(echo "$revisions_a") <(echo "$revisions_b"))

debug_echo "--- Revision Diffs ---"
debug_echo "$revision_diffs"
debug_echo ""

while read -r url revision_a revision_b; do
    org=$(echo "$url" | cut -d'/' -f4)
    repo=$(echo "$url" | cut -d'/' -f5)

    # Check which revision is ahead
    compare_json=$(github_api_call "https://api.github.com/repos/$org/$repo/compare/$revision_a...$revision_b")
    
    status=$(echo "$compare_json" | jq -r '.status')

    if [[ "$status" == "ahead" ]]; then
        base="$revision_a"
        head="$revision_b"
    elif [[ "$status" == "behind" ]]; then
        base="$revision_b"
        head="$revision_a"
    elif [[ "$status" == "identical" ]]; then
        echo "⚠ Revisions for $repo-$application are identical, even though image SHAs were not"
        continue
    else
        echo "⚠ Could not determine relationship between revisions for $repo-$application (status: $status)"
        continue
    fi

    echo "Repo: $url" > "$SCRIPT_DIR/diffs/$repo-$application.diff"
    echo "Diff: https://github.com/$org/$repo/compare/$base..$head" >> "$SCRIPT_DIR/diffs/$repo-$application.diff"
    echo "Base Commit: $base" >> "$SCRIPT_DIR/diffs/$repo-$application.diff"
    echo "New Commits:" >> "$SCRIPT_DIR/diffs/$repo-$application.diff"
    echo "$compare_json" | yq '.commits[] | .sha' | awk '{print "+", $1}' >> "$SCRIPT_DIR/diffs/$repo-$application.diff"
    echo "" >> "$SCRIPT_DIR/diffs/$repo-$application.diff"

    github_api_call "https://api.github.com/repos/$org/$repo/compare/$base...$head" "application/vnd.github.v3.diff" >> "$SCRIPT_DIR/diffs/$repo-$application.diff"

    echo "┌─── $org/$repo"
    echo "├── https://github.com/$org/$repo/compare/$base..$head"
    echo "└── Diff for $repo-$application written to $SCRIPT_DIR/diffs/$repo-$application.diff"
    # echo "🛈 Diff for $repo-$application written to $SCRIPT_DIR/diffs/$repo-$application.diff"
done <<< "$revision_diffs"