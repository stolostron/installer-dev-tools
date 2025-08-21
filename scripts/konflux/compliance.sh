#!/usr/bin/env bash

exec 3>&1

application=$1

# check for debug flag for testing
for arg in "$@"; do
    case $arg in
        --debug=*)
          debug="${arg#*=}"
          ;;
        --debug)
          debug=true
          ;;
    esac
done

compliancefile="data/$application-compliance.csv"
> $compliancefile

echo "Checking for Github auth token"
authorization=""
if [ -f "authorization.txt" ]; then
	authorization="Authorization: Bearer $(cat "authorization.txt")"
	echo "Authorization found. Applying to github API requests"
fi

if [[ "$OS" == "Darwin" && "$ARCH" == "arm64" ]]; then
    echo "Detected macOS ARM64. Adding skopeo platform override."
    skopeo_mac_args="--override-arch amd64 --override-os linux"
fi

# Function to check promoted image and get build time
check_promoted() {
    local line="$1"
    local skopeo_mac_args="$2"
    
    promoted=$(oc get component $line -oyaml | yq ".status.lastPromotedImage")
    if [[ "$promoted" == "null" || -z "$promoted" ]]; then
        # failed to get image
        # echo "failed to get image"
        buildtime="IMAGE_PULL_FAILURE,Failed"
    elif [[ "$promoted" =~ sha256:[a-f0-9]{64}$ ]]; then
        # found image
        skopeo=$(skopeo $skopeo_mac_args inspect "docker://$promoted" 2>/dev/null)
        if [ $? -ne 0 ]; then
            # inspection failed
            buildtime="INSPECTION_FAILURE,Failed"
        else
            buildtime="$(echo "$skopeo" | yq -p=json ".Labels.build-date"),Successful"
        fi
    else
        # invalid or incomplete digest
        buildtime="DIGEST_FAILURE,Failed"
    fi
    
    echo "$buildtime"
}

# Function to check hermetic builds
check_hermetic_builds() {
    local yaml="$1"
    local pull_yaml="$2"
    local authorization="$3"
    local org="$4"
    local repo="$5"
    local yaml_base="$6"
    local value="$7"
    
    hermeticbuilds=true
    pathinrepo=$(echo "$yaml" | yq "$yaml_base.pipelineRef.params | .[] | select(.name==\"pathInRepo\")")
    pullpathinrepo=$(echo "$pull_yaml" | yq "$yaml_base.pipelineRef.params | .[] | select(.name==\"pathInRepo\")")

    if [[ -z "$pathinrepo" || -z "$pullpathinrepo" ]]; then
        buildsourceimage=$(echo "$yaml" | yq "$yaml_base.params | .[] | select(.name==\"build-source-image\") | $value")
        pull_bsi=$(echo "$pull_yaml" | yq "$yaml_base.params | .[] | select(.name==\"build-source-image\") | $value")
        if [[ !($buildsourceimage == true || $buildsourceimage == "true") || !($pull_bsi == true || $pull_bse == "true") ]]; then
            hermeticbuilds=false
        fi

        hermetic=$(echo "$yaml" | yq "$yaml_base.params | .[] | select(.name==\"hermetic\") | $value")
        pull_hermetic=$(echo "$pull_yaml" | yq "$yaml_base.params | .[] | select(.name==\"hermetic\") | $value")
        if [[ $hermetic != true || $hermetic != "true" || $pull_hermetic != true || $pull_hermetic != "true" ]]; then
            hermeticbuilds=false
        fi
    fi

    vendor=$(curl -LsH "$authorization" -w "%{http_code}" "https://api.github.com/repos/$org/$repo/contents/vendor")
    vendor="${vendor: -3}"
    prefetch=$(echo "$yaml" | yq "$yaml_base.params | .[] | select(.name==\"prefetch-input\") | $value")
    pull_prefetch=$(echo "$pull_yaml" | yq "$yaml_base.params | .[] | select(.name==\"prefetch-input\") | $value")
    # echo "$prefetch $pull_prefetch"
    # echo -e "Prefetch: $prefetch\nPullPrefetch: $pull_prefetch\nVendor: $vendor"
    if [[ ($prefetch == "" || $pull_prefetch == "") && $vendor != "200" ]]; then
        # echo "prefetch failure"
        hermeticbuilds=false
    fi

    if [[ $hermeticbuilds == true ]]; then
        echo "🟩 $repo hermetic builds: TRUE" >&3
        echo "Enabled"
    else
        echo -e "🟥 $repo hermetic builds: FALSE\nbuild-source-image: $buildsourceimage\npull_hermetic: $pull_hermetic\npush_hermetic: $hermetic\npull_prefetch: $pull_prefetch\npush_prefetch: $prefetch\nvendor: $vendor" >&3
        echo "Not Enabled"
    fi
}

# Function to check enterprise contract
check_enterprise_contract() {
    local application="$1"
    local line="$2"
    local authorization="$3"
    local org="$4"
    local repo="$5"
    local branch="$6"
    
    ecname="enterprise-contract-$application / $line"
    
    # Try check-suites first (more reliable for Konflux)
    suite_id=$(curl -LsH "$authorization" "https://api.github.com/repos/$org/$repo/commits/$branch/check-suites" | yq -p=json ".check_suites[] | select(.app.name == \"Red Hat Konflux\") | .id" | head -1)

    if [[ -n "$suite_id" ]]; then
        # Use suite method for Konflux
        ec=$(curl -LsH "$authorization" "https://api.github.com/repos/$org/$repo/check-suites/$suite_id/check-runs" | yq -p=json ".check_runs[] | select(.name==\"*enterprise-contract*$line\") | .conclusion")
    else
        # Fallback to original method
        ec=$(curl -LsH "$authorization" "https://api.github.com/repos/$org/$repo/commits/$branch/check-runs" | yq -p=json ".check_runs[] | select(.app.name == \"Red Hat Konflux\") | select(.name==\"*enterprise-contract*$line\") | .conclusion")
    fi

    if [[ -n "$ec" ]] && ! echo "$ec" | grep -v "^success$" > /dev/null; then
        echo "🟩 $repo $ecname: SUCCESS" >&3
        echo "Compliant"
    else
        echo "🟥 $repo $ecname: FAILURE (ec was: \"$ec\")" >&3
        echo "Not Compliant"
    fi
}

# Function to check multiarch support
check_multiarch_support() {
    local yaml="$1"
    local repo="$2"
    local yaml_base="$3"
    local value="$4"
    
    platforms=$(echo "$yaml" | yq "$yaml_base.params | .[] | select(.name==\"build-platforms\") | $value | .[]" | wc -l | tr -d ' \t\n')
    if  [[ $platforms != 4 ]]; then
        echo "🟥 $repo Multiarch: FALSE" >&3
        echo "Not Enabled"
    else
        echo "🟩 $repo Multiarch: TRUE" >&3
        echo "Enabled"
    fi
}

if [[ -n "$debug" ]]; then
    components=$debug
else
    components=$(oc get components | grep $application | awk '{print $1}')
fi

for line in $components; do
    # Skip empty lines
    if [[ -z "$line" ]]; then
        continue
    fi

    data=$(check_promoted "$line" "$skopeo_mac_args")
    
    url=$(oc get component "$line" -oyaml | yq ".spec.source.git.url")
    branch=$(oc get component "$line" -oyaml | yq ".spec.source.git.revision")
    org=$(basename $(dirname $url))
    repo=$(basename $url)

    push="https://raw.githubusercontent.com/$org/$repo/refs/heads/$branch/.tekton/$line-push.yaml"
    pull="https://raw.githubusercontent.com/$org/$repo/refs/heads/$branch/.tekton/$line-pull-request.yaml"

    [[ -n "$debug" ]] && echo -e "[debug] Push: $push\n[debug] Pull: $pull" # debug

    echo "--- $line : $org/$repo : $branch ---"
    yaml=$(curl -Ls $push)
    pull_yaml=$(curl -Ls $push)

    hermetic_result=$(check_hermetic_builds "$yaml" "$pull_yaml" "$authorization" "$org" "$repo" ".spec" ".value")
    if [[ "$hermetic_result" == "Not Enabled" ]]; then
        hermetic_result=$(check_hermetic_builds "$yaml" "$pull_yaml" "$authorization" "$org" "$repo" ".spec.pipelineSpec" ".default")
    fi
    data="$data,$hermetic_result"

    data="$data,$(check_enterprise_contract "$application" "$line" "$authorization" "$org" "$repo" "$branch")"

    multiarch_result=$(check_multiarch_support "$yaml" "$repo" ".spec" ".value")
    if [[ "$multiarch_result" == "Not Enabled" ]]; then
        multiarch_result=$(check_multiarch_support "$yaml" "$repo" ".spec.pipelineSpec" ".default")
    fi
    data="$data,$multiarch_result"

    echo ""

    echo "$data" >> $compliancefile
done