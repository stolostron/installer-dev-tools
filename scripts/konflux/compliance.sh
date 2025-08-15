#!/bin/bash

# Script to process each component
# and run 'oc get component <line> -oyaml | yq' on each

set -e

application=$1

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

    promoted=$(oc get component $line -oyaml | yq .status.lastPromotedImage)
    if [[ "$promoted" == "null" || -z "$promoted" ]]; then
        # failed to get image
        # echo "failed to get image"
        buildtime="IMAGE_PULL_FAILURE,Failed"
    elif [[ "$promoted" =~ sha256:[a-f0-9]{64}$ ]]; then
        # found image
        skopeo=$(skopeo inspect "docker://$promoted" 2>/dev/null)
        if [ $? -ne 0 ]; then
            # inspection failed
            buildtime="INSPECTION_FAILURE,Failed"
        else
            buildtime="$(echo "$skopeo" | yq -p=json '.Labels.build-date'),Successful"
        fi
    else
        # invalid or incomplete digest
        buildtime="DIGEST_FAILURE,Failed"
    fi

    data=$buildtime
    
    url=$(oc get component "$line" -oyaml | yq '.spec.source.git.url')
    branch=$(oc get component "$line" -oyaml | yq '.spec.source.git.revision')
    org=$(basename $(dirname $url))
    repo=$(basename $url)

    push="https://raw.githubusercontent.com/$org/$repo/refs/heads/$branch/.tekton/$line-push.yaml"
    pull="https://raw.githubusercontent.com/$org/$repo/refs/heads/$branch/.tekton/$line-pull-request.yaml"

    # echo "$repo"
    # echo "Push"
    echo "--- $line : $org/$repo : $branch ---"
    yaml=$(curl -Ls $push)
    pull_yaml=$(curl -Ls $push)

    # HERMETIC BUILDS
    hermeticbuilds=true

    buildsourceimage=$(echo "$yaml" | yq '.spec.params | .[] | select(.name=="build-source-image") | .value')
    pull_bsi=$(echo "$pull_yaml" | yq '.spec.params | .[] | select(.name=="build-source-image") | .value')
    if [[ !($buildsourceimage == true || $buildsourceimage == "true") || !($pull_bsi == true || $pull_bse == "true") ]]; then
        hermeticbuilds=false
    fi

    hermetic=$(echo "$yaml" | yq '.spec.params | .[] | select(.name=="hermetic") | .value')
    pull_hermetic=$(echo "$pull_yaml" | yq '.spec.params | .[] | select(.name=="hermetic") | .value')
    if [[ $hermetic != true || $hermetic != "true" || $pull_hermetic != true || $pull_hermetic != "true" ]]; then
        hermeticbuilds=false
    fi

    prefetch=$(echo "$yaml" | yq '.spec.params | .[] | select(.name=="prefetch-input") | .value')
    pull_prefetch=$(echo "$pull_yaml" | yq '.spec.params | .[] | select(.name=="prefetch-input") | .value')
    if [[ $prefetch == "" || $pull_prefetch == "" ]]; then
        hermeticbuilds=false
    fi

    if [[ $hermeticbuilds == true ]]; then
        echo "🟩 $repo hermetic builds: TRUE"
        data=$(echo "$data,Enabled")
    else
        echo "🟥 $repo hermetic builds: FALSE"
        data=$(echo "$data,Not Enabled")
    fi

    # enterprise contract
    ec=$(curl -LsH "$authorization" https://api.github.com/repos/$org/$repo/commits/$branch/check-runs | yq -p=json ".check_runs[] | select(.app.name == \"Red Hat Konflux\") | select(.name == \"*enterprise-contract-$application / $line*\") | .conclusion ")

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