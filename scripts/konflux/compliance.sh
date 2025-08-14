#!/bin/bash

# Script to process each component
# and run 'oc get component <line> -oyaml | yq' on each

set -e


application=$1
branch=$2

> compliant.csv

echo "Checking for Github auth token"
authorization=""
if [ -f "authorization.txt" ]; then
	authorization="Authorization: Bearer $(cat "authorization.txt")"
	echo "Authorization found. Applying to github API requests"
fi

for line in $(oc get components | grep $application | awk '{print $1}'); do
    # Skip empty lines
    if [[ -z "$line" ]]; then
        continue
    fi

    data=""
    
    url=$(oc get component "$line" -oyaml | yq '.spec.source.git.url')
    org="stolostron"
    repo=$(basename $url)

    push="https://raw.githubusercontent.com/$org/$repo/refs/heads/$branch/.tekton/$repo-$application-push.yaml"
    pull="https://raw.githubusercontent.com/$org/$repo/refs/heads/$branch/.tekton/$repo-$application-pull-request.yaml"

    # echo "$repo"
    # echo "Push"
    echo "--- $line $repo : $branch ---"
    yaml=$(curl -Ls $push)
    pull_yaml=$(curl -Ls $push)

    # HERMETIC BUILDS
    hermeticbuilds=true

    buildsourceimage=$(echo "$yaml" | yq '.spec.params | .[] | select(.name=="build-source-image") | .value')
    pull_bsi=$(echo "$pull_yaml" | yq '.spec.params | .[] | select(.name=="build-source-image") | .value')
    if [[ $buildsourceimage != true || $pull_bsi != true ]]; then
        hermeticbuilds=false
    fi

    hermetic=$(echo "$yaml" | yq '.spec.params | .[] | select(.name=="hermetic") | .value')
    pull_hermetic=$(echo "$pull_yaml" | yq '.spec.params | .[] | select(.name=="hermetic") | .value')
    if [[ $hermetic != true  || $pull_hermetic != true ]]; then
        hermeticbuilds=false
    fi

    prefetch=$(echo "$yaml" | yq '.spec.params | .[] | select(.name=="prefetch-input") | .value')
    pull_prefetch=$(echo "$pull_yaml" | yq '.spec.params | .[] | select(.name=="prefetch-input") | .value')
    if [[ $prefetch == "" || $pull_prefetch == "" ]]; then
        hermeticbuilds=false
    fi

    if [[ $hermeticbuilds == true ]]; then
        echo "🟩 $repo hermetic builds: TRUE"
        data="Enabled"
    else
        echo "🟥 $repo hermetic builds: FALSE"
        data="Not Enabled"
    fi

    # enterprise contract
    ec=$(curl -LsH "$authorization" https://api.github.com/repos/$org/$repo/commits/$branch/check-runs | yq -p=json '.check_runs[] | select(.app.name == "Red Hat Konflux") | select(.name == "*enterprise-contract*") | .conclusion ')
    
    if [[ "$ec" == "success" ]]; then
        echo "🟩 $repo Enterprise Contract: SUCCESS"
        data=$(echo "$data,Compliant")
    else
        echo "🟥 $repo Enterprise Contract: FAILURE"
        data=$(echo "$data,Not Compliant")
    fi

    # MULTIARCH SUPPORT
    platforms=$(echo "$yaml" | yq '.spec.params | .[] | select(.name=="build-platforms") | .value | .[]' | wc -l)
    if [[ $platforms != 4 ]]; then
        echo "🟥 $repo Multiarch: FALSE"
        data=$(echo "$data,Not Enabled")
    else
        echo "🟩 $repo Multiarch: TRUE"
        data=$(echo "$data,Enabled")
    fi

    echo ""

    echo "$data" >> compliant.csv
done