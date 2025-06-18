#!/bin/bash

# To prevent rate limiting, consider creating a file called `authorization.txt` and placing a github Personal Access Token inside it
# ghp_<token>

declare -A repo_commits

acm_bb2_id=115756
mce_bb2_id=115757

echo "Grabbing latest ACM snapshot"
latest_acm_snapshot=$(curl -ks "https://gitlab.cee.redhat.com/api/v4/projects/$acm_bb2_id/repository/tree?ref=acm-2.14&path=snapshots&per_page=100" | jq -r '.[-2] | .name')

echo "Grabbing latest MCE Snapshot"
latest_mce_snapshot=$(curl -ks "https://gitlab.cee.redhat.com/api/v4/projects/$mce_bb2_id/repository/tree?ref=mce-2.9&path=snapshots&per_page=100" | jq -r '.[-2] | .name')

echo "Latest ACM snapshot: $latest_acm_snapshot"
echo "Latest MCE snapshot: $latest_mce_snapshot"

echo "Fetching shas for ACM and MCE snapshots"
latest_acm_downsha=$(curl -ks "https://gitlab.cee.redhat.com/acm-cicd/acm-bb2/-/raw/acm-2.14/snapshots/$latest_acm_snapshot/down-sha.log")
latest_mce_downsha=$(curl -ks "https://gitlab.cee.redhat.com/acm-cicd/mce-bb2/-/raw/mce-2.9/snapshots/$latest_mce_snapshot/down-sha.log")

shas="$latest_acm_downsha\n$latest_mce_downsha"
# echo "$shas"
# echo "$latest_acm_snapshot"
# echo "$latest_acm_downsha"

echo "Checking for Github auth token"
authorization=""
if [ -f "authorization.txt" ]; then
	authorization="Authorization: Bearer $(cat "authorization.txt")"
	echo "Authorization found. Applying to github API requests"
fi

function print_pr_testability {
	local pr_url=$1
	number=$(basename $pr_url)
	repo=$(basename $(dirname $(dirname $pr_url)))
	org=$(basename $(dirname $(dirname $(dirname $pr_url))))

	local commits="https://api.github.com/repos/$org/$repo/commits"
	# echo $org $repo $number

	if [[ ! -v repo_commits["$repo"] ]]; then
		# echo "adding commits for $repo"
		repo_commits["$repo"]=$(curl -LsH "Accept: application/vnd.github+json" -H "X-GitHub-Api-Verion: 2022-11-28" -H "$authorization" $commits)
	fi

	# echo -e "commits: ${repo_commits["$repo"]}"

	# echo "attempting to pull sha for $repo"
	# echo ${repo_commits["$repo"]}
	local pr_sha=$(echo "${repo_commits["$repo"]}" | jq -r '.[]| select(.commit.message | contains("#'$number'")) | .sha')

	# echo $pr_sha
	local published_sha=$(echo "$shas" | grep -m 1 $org/$repo | awk '{print $1}')

	# echo -e "pr: $pr_sha\npublished: $published_sha"

	# echo "comparing $org/$repo/pull/$number"
	local status=$(curl -LsH "Accept: application/vnd.github+json" -H"X-GitHub-Api-Version: 2022-11-28" -H "$authorization" "https://api.github.com/repos/$org/$repo/compare/$pr_sha...$published_sha" | jq -r '.status')

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

for pr; do
	print_pr_testability $pr
done
