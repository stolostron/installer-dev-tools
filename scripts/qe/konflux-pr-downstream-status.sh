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
Usage: $0 -a|--application <application> -t|--tag <tag> [-b|--branch <branch>] [--skip-opm-render] [--debug] [PR_URL1] [PR_URL2] ...

This script checks if PRs have made it into the latest downstream build image.

Options:
  -a, --application <app>    Application name (e.g., acm-215, acm-214)
  -t, --tag <tag>           Tag name (e.g., latest-2.15)
  -b, --branch <branch>     Branch name (optional, auto-determined from application if not provided)
  --skip-opm-render         Skip running opm render command
  --debug                   Enable debug output
  -h, --help                Show this help message

Arguments:
  PR_URL                    One or more GitHub PR URLs to check

Example:
  $0 -a acm-215 -t latest-2.15 https://github.com/stolostron/multiclusterhub-operator/pull/2668
  $0 --application acm-214 --tag latest-2.14 --branch release-2.14 --debug https://github.com/org/repo/pull/123
EOF
}

# Parse command line arguments
pr_urls=()
debug=false
skip_opm_render=false
while [[ $# -gt 0 ]]; do
  case $1 in
    -a|--application)
      application="$2"
      shift 2
      ;;
    -t|--tag)
      tag="$2"
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
if [ -z "$application" ] || [ -z "$tag" ]; then
  echo "Error: Both application and tag parameters are required"
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

# Determine branch if not provided
if [ -z "$branch" ]; then
  # Handle different application types
  if [ "$application_part" = "mce" ]; then
    branch="backplane-$major_version.$minor_version"
  else
    branch="release-$major_version.$minor_version"
  fi
fi

# Set channel based on application type
if [ "$application_part" = "mce" ]; then
  channel="stable-$major_version.$minor_version"
else
  channel="$branch"
fi

latest_snapshot_url="https://raw.githubusercontent.com/stolostron/$application_part-operator-bundle/refs/heads/$branch/latest-snapshot.yaml"
gen_config_url="https://raw.githubusercontent.com/stolostron/$application_part-operator-bundle/refs/heads/$branch/config/$application_part-manifest-gen-config.json"

debug_echo "Checking for Github auth token"
authorization=""
if [ -f "authorization.txt" ]; then
	authorization="Authorization: Bearer $(cat "authorization.txt")"
	debug_echo "Authorization found. Applying to github API requests"
fi

catalog="quay.io/acm-d/$application_part-dev-catalog:$tag"

if [ "$skip_opm_render" = false ]; then
  opm render $catalog -oyaml > $tag.cs.yaml
fi

function get_revision_for_pr {
  local pr_url="$1"
  local repo=$(dirname $(dirname $pr_url))
  local repo_name=$(basename $repo)

  debug_echo "Application: $application_part"
  debug_echo "Branch: $branch"
  debug_echo "Channel: $channel"
  debug_echo "PR: $pr_url"
  debug_echo "Repo: $repo"

  local csv=$(cat $tag.cs.yaml | yq "select(.schema == \"olm.channel\" and .name == \"$channel\") | .entries[-1].name")
  debug_echo "CSV: $csv"

  local publish_name=$(curl -Ls "$gen_config_url" | yq -p=json ".product-images.image-list[] | select(.konflux-component-name == \"$repo_name\") | .publish-name")
  debug_echo "Image Name: $publish_name"

  local published_image=$(cat $tag.cs.yaml | yq "select(.schema == \"olm.bundle\" and .name == \"$csv\") | .relatedImages[] | select(.image==\"*$publish_name*\") | .image")
  debug_echo "Published Image: $published_image"
  local published_image_sha=$(basename $published_image | cut -d'@' -f2)
  debug_echo "Published Image SHA: $published_image_sha"

  local component="$repo_name-$application"

  local calculated_image="$component@$published_image_sha"
  debug_echo "Calculated Image: $calculated_image"

  local revision_by_sha=$(curl -Ls "$latest_snapshot_url" | yq ".spec.components[] | select(.containerImage == \"*$calculated_image\") | .source.git.revision")
  debug_echo "Revision by SHA: $revision_by_sha"

  local revision_by_repo=$(curl -Ls "$latest_snapshot_url" | yq ".spec.components[] | select(.source.git.url == \"$repo\") | .source.git.revision")
  debug_echo "Revision by Repo: $revision_by_repo"

  # Compare revisions
  if [ "$revision_by_sha" != "$revision_by_repo" ]; then
    echo "🟪 Revision mismatch for $repo: SHA revision ($revision_by_sha) != Repo revision ($revision_by_repo)" >&3
    echo "REVISION_MISMATCH"
    return
  fi

  # Return the revision
  echo "$revision_by_repo"
}

function print_pr_testability {
	local pr_url=$1
	local number=$(basename $pr_url)
	local repo=$(basename $(dirname $(dirname $pr_url)))
	local org=$(basename $(dirname $(dirname $(dirname $pr_url))))
    local published_sha=$2

    debug_echo "Testing PR testability of $pr_url"
    debug_echo "Repo: $repo"
    debug_echo "Org: $org"

	local commits="https://api.github.com/repos/$org/$repo/commits"
    debug_echo "Commits url: $commits"
	# echo $org $repo $number

	if [[ ! -v repo_commits["$repo"] ]]; then
		# echo "adding commits for $repo"
		repo_commits["$repo"]=$(curl -LsH "Accept: application/vnd.github+json" -H "X-GitHub-Api-Verion: 2022-11-28" -H "$authorization" $commits)
	fi

	# echo -e "commits: ${repo_commits["$repo"]}"

	# echo "attempting to pull sha for $repo"
	# echo ${repo_commits["$repo"]}
	local pr_sha=$(echo "${repo_commits["$repo"]}" | jq -r '.[]| select(.commit.message | contains("#'$number'")) | .sha')

	# echo -e "pr: $pr_sha\npublished: $published_sha"

	# echo "comparing $org/$repo/pull/$number"
    compared_shas_url="https://api.github.com/repos/$org/$repo/compare/$pr_sha...$published_sha"
    # echo "$compared_shas_url"
	local status=$(curl -LsH "Accept: application/vnd.github+json" -H"X-GitHub-Api-Version: 2022-11-28" -H "$authorization" $compared_shas_url | jq -r '.status')

	# echo $status

	# behind
	# identical
	# ahead
	# we only actually care if it's behind or not

	if [ "$status" == "404" ]; then
		echo "🟨 $org/$repo pull $number has not been merged into the specified branch yet"
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

  revision=$(get_revision_for_pr "$pr_url")
  if [ "$revision" != "REVISION_MISMATCH" ]; then
    print_pr_testability "$pr_url" "$revision"
  fi
done
