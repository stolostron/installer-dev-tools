#!/bin/bash

# Set up file descriptor 3 for output messages
exec 3>&1

# Debug output function
debug_echo() {
  if [ "$debug" = true ]; then
    echo "$@" >&3
  fi
}

mkdir -p ./diffs

# Cache for gen_config to avoid repeated fetches
declare -g gen_config_cache=""

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

function github_api_call() {
  local url="$1"
  local accept_header="${2:-application/vnd.github+json}"

  curl -LsH "Accept: $accept_header" \
    -H "X-GitHub-Api-Version: 2022-11-28" \
    -H "$authorization" \
    "$url"
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

function get_revision_for_image {
  local image="$1"
  local repo_owner="stolostron"
  local repo_name="$application_part-operator-bundle"

  debug_echo "Looking up revision for image: $image"

  # Get commit history for latest-snapshot.yaml
  local commits_url="https://api.github.com/repos/$repo_owner/$repo_name/commits?path=latest-snapshot.yaml&sha=$branch"
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
      echo "$found_revision"
      return
    fi
  done
}

debug=false
skip_opm_render=false
while [[ $# -gt 0 ]]; do
  case $1 in
    -v|--semantic-version)
      version="$2"
      shift 2
      ;;
    -s|--snapshot)
      snapshots+=("$2")
      shift 2
      ;;
    --skip-opm-render)
      skip_opm_render=true
      shift
      ;;
    --debug)
      debug=true
      shift
      ;;
    -b|--branch)
      branch="$2"
      shift 2
      ;;
    -t|--tag)
      tags+=("$2")
      shift 2
      ;;
    -*)
      echo "Error: Unknown option: $1" >&2
      echo ""
      exit 1
      ;;
    *)
      echo "Error: No positional arguments accepted: $1" >&2
      echo ""
      exit 1
      ;;
  esac
done

if (( ( ${#tags[@]} + ${#snapshots[@]} ) != 2 )); then
  echo "Error: Incorrect number of snapshots and tags"
  exit 1
fi

# determine comparison mode
declare -r COMPARE_MODE_TAGS="TAGS"
declare -r COMPARE_MODE_SNAPSHOTS="SNAPSHOTS"
declare -r COMPARE_MODE_MIXED="MIXED"

case ${#tags[@]} in
  0)
  compare_mode=$COMPARE_MODE_SNAPSHOTS
  ;;
  1)
  compare_mode=$COMPARE_MODE_MIXED
  ;;
  *)
  compare_mode=$COMPARE_MODE_TAGS
esac

echo "Compare Mode: $compare_mode"

sorted_tags=($(printf "%s\n" "${tags[@]}" | sort -t '-' -k3))

older_tag=${sorted_tags[0]}
newer_tag=${sorted_tags[1]}

debug_echo "Older Tag: $older_tag"
debug_echo "Newer Tag: $newer_tag"

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

# Determine branch if not provided
if [ -z "$branch" ]; then
  branch=$snapshot_branch
fi

latest_snapshot_url="https://raw.githubusercontent.com/stolostron/$application_part-operator-bundle/refs/heads/$snapshot_branch/latest-snapshot.yaml"

debug_echo "Application Part: $application_part"
debug_echo "Version Number: $version_number"
debug_echo "Major Version: $major_version"
debug_echo "Minor Version: $minor_version"
debug_echo "Patch Version: $patch_version"

if [ "$application_part" = "acm" ]; then
  csv_name="advanced-cluster-management.v$version_number*"
else
  csv_name="multicluster-engine.v$version_number*"
fi

debug_echo "CSV Name: $csv_name"

authorization=""
if [ -f "authorization.txt" ]; then
	authorization="Authorization: Bearer $(cat "authorization.txt")"
	debug_echo "Authorization found. Applying to github API requests"
fi

debug_echo "Collecting catalog contents"
if [ "$skip_opm_render" = false ]; then
    echo "🛈 Rendering $application_part-dev-catalog:$older_tag"
    opm render quay.io/acm-d/$application_part-dev-catalog:$older_tag --migrate -oyaml > older.cs.yaml

    echo "🛈 Rendering $application_part-dev-catalog:$newer_tag"
    opm render quay.io/acm-d/$application_part-dev-catalog:$newer_tag --migrate -oyaml > newer.cs.yaml
fi

image_diffs=$(paste <(bat older.cs.yaml | yq "select(.name==\"$csv_name\") | .relatedImages[].image") <(bat newer.cs.yaml | yq "select(.name==\"$csv_name\") | .relatedImages[].image") | awk '$1 != $2')

if [[ -n $image_diffs ]]; then
  echo "🛈 Component images changed between provided tags:"
  echo "$image_diffs" | awk '$1 !~ /operator-bundle/ {print $1}' | cut -d'/' -f3 | cut -d'@' -f1 | awk '{print "-", $1}'
  echo ""
fi

while IFS= read -r line; do
  parts=($line)
  debug_echo "Comparing ${parts[0]} with ${parts[1]}"

  calculated_image_a=$(calculate_konflux_image ${parts[0]})
  calculated_image_b=$(calculate_konflux_image ${parts[1]})

  debug_echo "Calculated Image A: $calculated_image_a"
  debug_echo "Calculated Image B: $calculated_image_b"

  if [[ -z "$calculated_image_a" || -z "$calculated_image_b" ]]; then continue; fi

  revision_a=$(get_revision_for_image $calculated_image_a)
  revision_b=$(get_revision_for_image $calculated_image_b)
  debug_echo "Revision A: $revision_a"
  debug_echo "Revision B: $revision_b"

  image_name=$(basename ${parts[0]} | cut -d'@' -f1)
  konflux_name=$(get_konflux_component_name "$image_name")
  debug_echo "Konflux Name: $konflux_name"

  git_url=$(curl -Ls "$latest_snapshot_url" | yq ".spec.components[] | select(.source.git.url | contains(\"$konflux_name\")) | .source.git.url")

  debug_echo "Git URL: $git_url"
  org=$(echo "$git_url" | cut -d'/' -f4)
  repo=$(echo "$git_url" | cut -d'/' -f5)

  debug_echo "Org: $org"
  debug_echo "Repo: $repo"

  github_api_call "https://api.github.com/repos/$org/$repo/compare/$revision_a...$revision_b" "application/vnd.github.v3.diff" > "./diffs/$konflux_name-$application.diff"

  echo "🛈 Diff for $konflux_name-$application written to ./diffs/$konflux_name-$application.diff"

done <<< "$image_diffs"