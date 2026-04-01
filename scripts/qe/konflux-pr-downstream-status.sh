#!/bin/bash

# Set up file descriptor 3 for output messages
exec 3>&1

declare -A repo_commits

# Debug output function
debug_echo() {
  if [ "$debug" = true ]; then
    echo "$@" >&3
  fi
}

# Help function
show_help() {
  cat << EOF
Usage: $0 -a|--application <application> (-t|--tag <tag> | -s|--snapshot <snapshot>) [-b|--branch <branch>] [--skip-opm-render] [--debug] [PR_URL1] [PR_URL2] ...

This script checks if PRs have made it into the latest downstream build image.

Options:
  -a, --application <app>    Application name (e.g., acm-215, acm-214)
  -t, --tag <tag>           Tag name (e.g., latest-2.15) - mutually exclusive with --snapshot
  -s, --snapshot <name>     Snapshot name - mutually exclusive with --tag
  -b, --branch <branch>     Branch name (optional, auto-determined from application if not provided)
  --skip-opm-render         Skip running opm render command
  --debug                   Enable debug output
  -h, --help                Show this help message

Arguments:
  PR_URL                    One or more GitHub PR URLs to check

Examples:
  $0 -a acm-215 -t latest-2.15 https://github.com/stolostron/multiclusterhub-operator/pull/2668
  $0 --application acm-214 --tag latest-2.14 --branch release-2.14 --debug https://github.com/org/repo/pull/123
  $0 -a acm-215 -s my-snapshot https://github.com/stolostron/multiclusterhub-operator/pull/2668
EOF
}

# Parse command line arguments
pr_urls=()
debug=false
skip_opm_render=false
INPUT_TYPE=""
while [[ $# -gt 0 ]]; do
  case $1 in
    -a|--application)
      application="$2"
      shift 2
      ;;
    -t|--tag)
      tag="$2"
      INPUT_TYPE="TAG"
      shift 2
      ;;
    -s|--snapshot)
      snapshot="$2"
      INPUT_TYPE="SNAPSHOT"
      shift 2
      ;;
    -b|--branch)
      branch="$2"
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
    -h|--help)
      show_help
      exit 0
      ;;
    -*)
      echo "Error: Unknown option: $1" >&2
      echo ""
      show_help
      exit 1
      ;;
    *)
      # Collect remaining arguments as PR URLs
      pr_urls+=("$1")
      shift
      ;;
  esac
done

# Check required parameters
if [ -z "$application" ]; then
  echo "Error: Application parameter is required"
  echo ""
  show_help
  exit 1
fi

# Check that either tag or snapshot is provided, but not both
if [ -n "$tag" ] && [ -n "$snapshot" ]; then
  echo "Error: Cannot use both --tag and --snapshot. Please specify only one."
  echo ""
  show_help
  exit 1
fi

if [ -z "$tag" ] && [ -z "$snapshot" ]; then
  echo "Error: Either --tag or --snapshot parameter is required"
  echo ""
  show_help
  exit 1
fi

# Check if at least one PR URL is provided
if [ ${#pr_urls[@]} -eq 0 ]; then
  echo "Error: At least one PR URL must be provided"
  echo ""
  show_help
  exit 1
fi

# Parse application and set up common variables
application_part=$(echo "$application" | cut -d'-' -f1)
version_number=$(echo "$application" | cut -d'-' -f2)
major_version=$(echo "$version_number" | cut -c1)
minor_version=$(echo "$version_number" | cut -c2-)

# Handle different application types
if [ "$application_part" = "mce" ]; then
  snapshot_branch="backplane-$major_version.$minor_version"
else
  snapshot_branch="release-$major_version.$minor_version"
fi

# Determine branch if not provided
if [ -z "$branch" ]; then
  branch=$snapshot_branch
fi

# Set channel based on application type
if [ "$application_part" = "mce" ]; then
  channel="stable-$major_version.$minor_version"
elif [ "$application_part" = "acm" ]; then
  channel="release-$major_version.$minor_version"
fi

# No longer need snapshot URL - using gh api directly

auth_check_failures=0

# Check that we're in the correct OpenShift project (only needed for snapshot mode)
if [ "$INPUT_TYPE" = "SNAPSHOT" ]; then
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

if [ "$INPUT_TYPE" = "TAG" ]; then
  catalog="quay.io/acm-d/$application_part-dev-catalog:$tag"
fi

# Create cache directory if it doesn't exist
mkdir -p cache

if [ "$skip_opm_render" = false ] && [ "$INPUT_TYPE" = "TAG" ]; then
  opm render $catalog -oyaml > cache/$tag.cs.yaml
fi

function get_revision_for_snapshot {
  local snapshot="$1"
  local repo="$2"

  local revision=$(oc get snapshot $snapshot -oyaml | yq ".spec.components[] | select(.source.git.url==\"$repo\") | .source.git.revision")
  echo "$revision"
}

function get_revision_for_pr_with_tag {
  local pr_url="$1"
  local repo=$(echo "$pr_url" | cut -d'/' -f1-5)
  local org=$(echo "$pr_url" | cut -d'/' -f4)
  local repo_name=$(echo "$pr_url" | cut -d'/' -f5)


  debug_echo "Application: $application_part"
  debug_echo "Branch: $branch"
  debug_echo "Channel: $channel"
  debug_echo "PR: $pr_url"
  debug_echo "Repo: $repo"
  debug_echo "Org: $org"
  debug_echo "Repo Name: $repo_name"

  local csv=$(cat cache/$tag.cs.yaml | yq "select(.schema == \"olm.channel\" and .name == \"$channel\") | .entries[-1].name")
  debug_echo "CSV: $csv"

  if [ -z "$csv" ] || [ "$csv" = "null" ]; then
    echo "⚠️  Warning: No CSV found for channel '$channel'. Check if the channel exists or if opm render succeeded." >&2
    echo "CSV_ERROR"
    return 1
  fi

  # Get the image name from prodseccomponent field (format: "pscomponent:bundle/image-name")
  local prodsec=$(gh api repos/stolostron/acm-config/contents/product/component-registry.yaml --jq '.content' | base64 -d | yq ".components[] | select(.repository == \"$repo\") | .prodseccomponent")
  debug_echo "Prodsec Component: $prodsec"

  if [ -z "$prodsec" ] || [ "$prodsec" = "null" ]; then
    echo "⚠️  Error: No prodsec component found for repository '$repo'. Check if the component exists in the component registry." >&2
    echo "COMPONENT_NAME_ERROR"
    return 1
  fi

  # Extract image name from prodseccomponent (everything after the last /)
  local image_name=$(echo "$prodsec" | awk -F'/' '{print $NF}')
  debug_echo "Image Name: $image_name"

  local published_image=$(cat cache/$tag.cs.yaml | yq "select(.schema == \"olm.bundle\" and .name == \"$csv\") | .relatedImages[] | select(.image==\"*$image_name*\") | .image")
  debug_echo "Published Image: $published_image"

  # Transform registry.redhat.io/xxxx/image to quay.io/acm-d/image
  local quay_image=$(echo "$published_image" | sed 's|registry\.redhat\.io/[^/]*/|quay.io/acm-d/|')
  debug_echo "Quay Image: $quay_image"

  # Get revision from image labels using skopeo
  local revision_by_sha=$(skopeo inspect --no-tags --format '{{json .Labels}}' "docker://$quay_image" | jq -r '."vcs-ref"')
  debug_echo "Revision by SHA: $revision_by_sha"

  local revision_by_repo=$(gh api "repos/stolostron/$application_part-operator-bundle/contents/latest-snapshot.yaml?ref=$snapshot_branch" --jq '.content' | base64 -d | yq ".spec.components[] | select(.source.git.url == \"$repo\") | .source.git.revision")
  debug_echo "Revision by Repo: $revision_by_repo"

  # Compare revisions
  if [ "$revision_by_sha" != "$revision_by_repo" ]; then
    echo -e "🛈 latest_snapshot has been updated for $repo, but is not yet in the latest built image:\n🛈 Latest published tag revision: ($revision_by_sha)\n🛈 Bundle repo revision ($revision_by_repo)" >&3
  fi

  # Return the revision
  echo "$revision_by_sha"
}

function get_revision_for_pr_with_snapshot {
  local snapshot="$1"
  local pr_url="$2"
  local repo=$(echo "$pr_url" | cut -d'/' -f1-5)
  local org=$(echo "$pr_url" | cut -d'/' -f4)
  local repo_name=$(echo "$pr_url" | cut -d'/' -f5)

  debug_echo "Application: $application_part"
  debug_echo "Branch: $branch"
  debug_echo "Channel: $channel"
  debug_echo "PR: $pr_url"
  debug_echo "Repo: $repo"
  debug_echo "Org: $org"
  debug_echo "Repo Name: $repo_name"

  revision=$(get_revision_for_snapshot "$snapshot" "$repo")
  echo "$revision"
}

function print_pr_testability {
	local pr_url=$1
	local number=$(basename $pr_url)
	local repo=$(basename $(dirname $(dirname $pr_url)))
	local org=$(basename $(dirname $(dirname $(dirname $pr_url))))
  local published_sha=$2
  local branch=$3

  debug_echo "Testing PR testability of $pr_url"
  debug_echo "Repo: $repo"
  debug_echo "Org: $org"
  debug_echo "Branch: $branch"

	local commits="https://api.github.com/repos/$org/$repo/commits?sha=$branch"
  debug_echo "Commits url: $commits"
	debug_echo $org $repo $number

	# if [[ ! -v repo_commits["$repo"] ]]; then
	# 	# echo "adding commits for $repo"
	# 	repo_commits["$repo"]=$(curl -LsH "Accept: application/vnd.github+json" -H "X-GitHub-Api-Verion: 2022-11-28" -H "$authorization" $commits)
	# fi

	# echo -e "commits: ${repo_commits["$repo"]}"

	debug_echo "attempting to pull sha for $repo"
	# debug_echo ${repo_commits["$repo"]}
	# local pr_sha=$(echo "${repo_commits["$repo"]}" | jq -r ".[]| select(.commit.message | split(\"\\n\")[0] | contains(\"#$number\")) | .sha")
  local pr_sha=$(gh api "repos/$org/$repo/pulls/$number" --jq '.merge_commit_sha')
  # echo -e "pr: $pr_sha\npublished: $published_sha"

	# echo "comparing $org/$repo/pull/$number"
  debug_echo "Published Sha: $published_sha"
  debug_echo "PR Sha: $pr_sha"
    # echo "$compared_shas_url"
	local status=$(gh api "repos/$org/$repo/compare/$pr_sha...$published_sha" --jq '.status' 2>/dev/null || echo "404")

	# echo $status

	# behind
	# identical
	# ahead
	# we only actually care if it's behind or not
  pr_sha=${pr_sha:-"[PR_SHA_NOT_FOUND]"}
  published_sha=${published_sha:-"[PUBLISHED_SHA_NOT_FOUND]"}
	if [ "$status" == "404" ]; then
		echo "🟨 404: no revision path from $pr_sha to $published_sha"
	elif [ $status == "ahead" ] || [ $status == "identical" ]; then
		echo "🟩 $org/$repo pull $number is in the downstream build"
	elif [ $status == "behind" ]; then
		echo "🟥 $org/$repo pull $number is not in the downstream build"
	elif [ $status == "diverged" ]; then
		echo "🟪 $org/$repo pull $number has diverged from the downstream build"
	else
		echo "Unknown repo status: $status"
	fi
}


# Process each PR URL
for pr_url in "${pr_urls[@]}"; do
  debug_echo ""
  debug_echo "Processing PR: $pr_url"

  revision=""
  if [ "$INPUT_TYPE" = "TAG" ]; then
    revision=$(get_revision_for_pr_with_tag "$pr_url")
  else
    revision=$(get_revision_for_pr_with_snapshot "$snapshot" "$pr_url")
  fi
  if [ "$revision" = "CSV_ERROR" ] || [ "$revision" = "COMPONENT_NAME_ERROR" ]; then
    exit 1
  fi
  debug_echo "Discovered Revision: $revision"
  print_pr_testability "$pr_url" "$revision" "$branch"
done
