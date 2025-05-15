#!/bin/bash

declare -A repo_commits
down_sha=$1
shift

function print_pr_testability {
  local pr_url=$1
  number=$(basename $pr_url)
  repo=$(basename $(dirname $(dirname $pr_url)))
  org=$(basename $(dirname $(dirname $(dirname $pr_url))))

  local commits="https://api.github.com/repos/$org/$repo/commits"
  # echo $org $repo $number

  if [[ ! -v repo_commits["$org/$repo"] ]]; then
    repo_commits["$org/$repo"]=$(curl -LsH "Accept: application/vnd.github+json" -H "X-GitHub-Api-Verion: 2022-11-28" $commits)
  fi

  # echo "attempting to pull sha"
  # echo ${repo_commits["$org/$repo"]}
  local pr_sha=$(echo "${repo_commits["$org/$repo"]}" | jq -r '.[]| select(.commit.message | contains("(#'$number')")) | .sha')

  local published_sha=$(curl -ks $down_sha | grep stolostron/multiclusterhub-operator | awk '{print $1}')

  # echo $pr_sha $published_sha

  local status=$(curl -LsH "Accept: application/vnd.github+json" -H"X-GitHub-Api-Version: 2022-11-28" "https://api.github.com/repos/stolostron/multiclusterhub-operator/compare/$pr_sha...$published_sha" | jq -r '.status')

  # echo $status

  # behind
  # identical
  # ahead
  # we only actually care if it's behind or not

  if [ $status == "behind" ]; then
    echo "❌ $repo pull $number is not in the downstream build"
  else
    echo "✅ $repo pull $number is in the downstream build"
  fi 
}

for pr;
do
  print_pr_testability $pr
done
