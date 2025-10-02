#!/bin/bash
# Set up file descriptor 3 for output messages
exec 3>&1
# Cache for gen_config to avoid repeated fetches
declare -g gen_config_cache=""

snapshot="release-acm-214-czrhh"
tag="2.14.1-DOWNSTREAM-2025-09-29-02-19-47"
version="acm-2.14.1"

echo "Snapshot: $snapshot"
echo "Tag: $tag"
echo "Version: $version"

# acm-2.14.1
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

echo "Application Part: $application_part"
echo "Version Number: $version_number"
echo "Major Version: $major_version"
echo "Minor Version: $minor_version"
echo "Patch Version: $patch_version"

if [ "$application_part" = "acm" ]; then
  csv_name="advanced-cluster-management.v$version_number*"
else
  csv_name="multicluster-engine.v$version_number*"
fi

echo "CSV Name: $csv_name"

authorization=""
if [ -f "authorization.txt" ]; then
	authorization="Authorization: Bearer $(cat "authorization.txt")"
	echo "Authorization found. Applying to github API requests"
fi

tag_images=$(cat older.cs.yaml | yq "select(.name==\"$csv_name\") | .relatedImages[].image")
snapshot_cache=$(oc get snapshot release-acm-214-czrhh -oyaml)
snapshot_images=$(echo "$snapshot_cache" | yq '.spec.components[].containerImage')


debug=false
# Debug output function
debug_echo() {
  if [ "$debug" = true ]; then
    echo "$@" >&3
  fi
}

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
  get_gen_config "$application_part" "$snapshot_branch" | yq -p=json ".product-images.image-list[] | select(.publish-name == \"$publish_name\") | .konflux-component-name"
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

# grab all the tag images (from the csv), and calculate what the konflux image would be
konflux_images_from_csv=$(echo "$tag_images" | while read img; do
    result=$(calculate_konflux_image "$img")
    echo "${result:-__EMPTY__}"
done | awk '$1 != "__EMPTY__"')


# image_diffs has the tag images on the left and the images pulled from the actual snapshot yaml on the right
image_diffs=$(paste <(echo "$konflux_images_from_csv" | sort) <(echo "$snapshot_images" | cut -d'/' -f4 | sort) | awk '$1 != $2')

debug_echo "--- Image Diffs ---"
debug_echo "$image_diffs"
debug_echo ""

# Get revisions from the CSV images
debug_echo "--- Revisions From CSV ---"
revisions_from_csv=$(echo "$image_diffs" | awk '{print $1}' | while read img; do
    result=$(get_revision_for_image "$img")
    echo "${result:-__NOT_FOUND__}"
done)

# Get revisions from the Snapshot images
revisions_from_snapshot=$(echo "$image_diffs" | awk '{print $2}' | while read img; do
    result=$(echo "$snapshot_cache" | yq ".spec.components[] | select(.containerImage | contains(\"$img\")).source.git.revision")
    echo "$result"
done)

# get the URL from the snapshot
url_from_snapshot=$(echo "$image_diffs" | awk '{print $2}' | while read img; do
    result=$(echo "$snapshot_cache" | yq ".spec.components[] | select(.containerImage | contains(\"$img\")).source.git.url")
    echo "$result"
done)

debug_echo "--- Revisions from CSV ---"
debug_echo "$revisions_from_csv"
debug_echo ""

debug_echo "--- Revisions from Snapshot ---"
debug_echo "$revisions_from_snapshot"
debug_echo ""

revision_diffs=$(paste <(echo "$url_from_snapshot") <(echo "$revisions_from_csv") <(echo "$revisions_from_snapshot"))

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

    github_api_call "https://api.github.com/repos/$org/$repo/compare/$base...$head" "application/vnd.github.v3.diff" > "./diffs/$repo-$application.diff"
    echo "🛈 Diff for $repo-$application written to ./diffs/$repo-$application.diff"
done <<< "$revision_diffs"