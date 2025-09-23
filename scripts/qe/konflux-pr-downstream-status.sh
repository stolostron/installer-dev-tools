#!/bin/bash

declare -A repo_commits

# Help function
show_help() {
  cat << EOF
Usage: $0 -a|--application <application> -t|--tag <tag> [PR_URL1] [PR_URL2] ...

This script checks if PRs have made it into the latest downstream build image.

Options:
  -a, --application <app>    Application name (e.g., acm-215, acm-214)
  -t, --tag <tag>           Tag name (e.g., latest-2.15)
  -h, --help                Show this help message

Arguments:
  PR_URL                    One or more GitHub PR URLs to check

Example:
  $0 -a acm-215 -t latest-2.15 https://github.com/stolostron/multiclusterhub-operator/pull/2668
  $0 --application acm-214 --tag latest-2.14 https://github.com/org/repo/pull/123 https://github.com/org/repo/pull/456
EOF
}

# Parse command line arguments
pr_urls=()
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

application_part=$(echo "$application" | cut -d'-' -f1)
version_number=$(echo "$application" | cut -d'-' -f2)
major_version=$(echo "$version_number" | cut -c1)
minor_version=$(echo "$version_number" | cut -c2-)
branch="release-$major_version.$minor_version"
latest_snapshot_url="https://raw.githubusercontent.com/stolostron/$application_part-operator-bundle/refs/heads/$branch/latest-snapshot.yaml"
pr="https://github.com/stolostron/multiclusterhub-operator/pull/2668"
repo=$(dirname $(dirname $pr))
repo_name=$(basename $repo)

gen_config_url="https://raw.githubusercontent.com/stolostron/$application_part-operator-bundle/refs/heads/$branch/config/$application_part-manifest-gen-config.json"

echo "Application: $application_part"
echo "Branch: $branch"
echo "PR: $pr"
echo "Repo: $repo"
catalog="quay.io/acm-d/acm-dev-catalog:$tag"

# opm render $catalog -oyaml > $tag.cs.yaml
csv=$(cat $tag.cs.yaml | yq "select(.schema == \"olm.channel\" and .name == \"$branch\") | .entries[-1].name")
echo "CSV: $csv"

publish_name=$(curl -Ls "$gen_config_url" | yq -p=json ".product-images.image-list[] | select(.konflux-component-name == \"$repo_name\") | .publish-name")
echo "Image Name: $publish_name"

published_image=$(cat $tag.cs.yaml | yq "select(.schema == \"olm.bundle\" and .name == \"$csv\") | .relatedImages[] | select(.image==\"*$publish_name*\") | .image")
echo "Published Image: $published_image"
published_image_sha=$(basename $published_image | cut -d'@' -f2)
echo "Published Image SHA: $published_image_sha"

component="$repo_name-acm-215"

calculated_image="$component@$published_image_sha"
echo "Calculated Image: $calculated_image"

revision_by_sha=$(curl -Ls "$latest_snapshot_url" | yq ".spec.components[] | select(.containerImage == \"*$calculated_image\") | .source.git.revision")
echo "Revision by SHA: $revision_by_sha"

revision_by_repo=$(curl -Ls "$latest_snapshot_url" | yq ".spec.components[] | select(.source.git.url == \"$repo\") | .source.git.revision")
echo "Revision by Repo: $revision_by_repo"


echo "Checking for Github auth token"
authorization=""
if [ -f "authorization.txt" ]; then
	authorization="Authorization: Bearer $(cat "authorization.txt")"
	echo "Authorization found. Applying to github API requests"
fi

function print_pr_testability {
	local pr_url=$1
	local number=$(basename $pr_url)
	local repo=$(basename $(dirname $(dirname $pr_url)))
	local org=$(basename $(dirname $(dirname $(dirname $pr_url))))
    local published_sha=$2

    echo "Testing PR testability of $pr_url"
    echo "Repo: $repo"
    echo "Org: $org"

	local commits="https://api.github.com/repos/$org/$repo/commits"
    echo "Commits url: $commits"
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

	if [ $status == "ahead" ] || [ $status == "identical" ]; then
		echo "🟩 $org/$repo pull $number is in the downstream build"
	elif [ $status == "behind" ]; then
		echo "🟥 $org/$repo pull $number is not in the downstream build"
	elif [ $status == "diverged" ]; then
		echo "🟪 $org/$repo pull $number has diverged from the downstream build"
	else
		echo "Unknown repo status: $status"
	fi
}


print_pr_testability $pr $revision_by_repo
