#!/usr/bin/env bash

exec 3>&1

show_help() {
    cat << EOF
Usage: compliance.sh [OPTIONS] <application>

Check compliance status for Konflux components

ARGUMENTS:
    <application>    The application name to check (e.g., acm-215)

OPTIONS:
    --debug=<component>   Run against a specific Konflux component only
    --debug               Enable debug logging output
    -h, --help            Show this help message

EXAMPLES:
    compliance.sh acm-215
    compliance.sh --debug=my-component acm-215
    compliance.sh --debug acm-215
EOF
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --debug=*)
            debug="${1#*=}"
            shift
            ;;
        --debug)
            debug=true
            shift
            ;;
        -h|--help)
            show_help=true
            shift
            ;;
        -*)
            echo "Unknown option $1"
            exit 1
            ;;
        *)
            if [[ -z "$application" ]]; then
                application=$1
            else
                echo "Multiple applications specified: $application and $1"
                exit 1
            fi
            shift
            ;;
    esac
done

# Check for help flag or no arguments
if [[ "$show_help" == "true" ]] || [[ -z "$application" ]]; then
    show_help
    exit 0
fi

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
    
    hermeticbuilds=true
    
    # Check pathInRepo (first .spec, then fallback to .spec.pipelineSpec)
    pathinrepo=$(echo "$yaml" | yq ".spec.pipelineRef.params | .[] | select(.name==\"pathInRepo\")")
    [[ -n "$debug" ]] && echo "[debug] pathInRepo (push): using .spec = $pathinrepo" >&3
    if [[ -z "$pathinrepo" ]]; then
        pathinrepo=$(echo "$yaml" | yq ".spec.pipelineSpec.pipelineRef.params | .[] | select(.name==\"pathInRepo\")")
        [[ -n "$debug" ]] && echo "[debug] pathInRepo (push): using .spec.pipelineSpec fallback = $pathinrepo" >&3
    fi
    
    pullpathinrepo=$(echo "$pull_yaml" | yq ".spec.pipelineRef.params | .[] | select(.name==\"pathInRepo\")")
    [[ -n "$debug" ]] && echo "[debug] pathInRepo (pull): using .spec = $pullpathinrepo" >&3
    if [[ -z "$pullpathinrepo" ]]; then
        pullpathinrepo=$(echo "$pull_yaml" | yq ".spec.pipelineSpec.pipelineRef.params | .[] | select(.name==\"pathInRepo\")")
        [[ -n "$debug" ]] && echo "[debug] pathInRepo (pull): using .spec.pipelineSpec fallback = $pullpathinrepo" >&3
    fi

    if [[ -z "$pathinrepo" || -z "$pullpathinrepo" ]]; then
        # Check build-source-image (first .spec.params.value, then fallback to .spec.pipelineSpec.params.default)
        buildsourceimage=$(echo "$yaml" | yq ".spec.params | .[] | select(.name==\"build-source-image\") | .value")
        [[ -n "$debug" ]] && echo "[debug] build-source-image (push): using .spec.params.value = $buildsourceimage" >&3
        if [[ -z "$buildsourceimage" ]]; then
            buildsourceimage=$(echo "$yaml" | yq ".spec.pipelineSpec.params | .[] | select(.name==\"build-source-image\") | .default")
            [[ -n "$debug" ]] && echo "[debug] build-source-image (push): using .spec.pipelineSpec.params.default = $buildsourceimage" >&3
        fi
        
        pull_bsi=$(echo "$pull_yaml" | yq ".spec.params | .[] | select(.name==\"build-source-image\") | .value")
        [[ -n "$debug" ]] && echo "[debug] build-source-image (pull): using .spec.params.value = $pull_bsi" >&3
        if [[ -z "$pull_bsi" ]]; then
            pull_bsi=$(echo "$pull_yaml" | yq ".spec.pipelineSpec.params | .[] | select(.name==\"build-source-image\") | .default")
            [[ -n "$debug" ]] && echo "[debug] build-source-image (pull): using .spec.pipelineSpec.params.default = $pull_bsi" >&3
        fi
        
        if [[ !($buildsourceimage == true || $buildsourceimage == "true") || !($pull_bsi == true || $pull_bse == "true") ]]; then
            hermeticbuilds=false
        fi

        # Check hermetic (first .spec.params.value, then fallback to .spec.pipelineSpec.params.default)
        hermetic=$(echo "$yaml" | yq ".spec.params | .[] | select(.name==\"hermetic\") | .value")
        [[ -n "$debug" ]] && echo "[debug] hermetic (push): using .spec.params.value = $hermetic" >&3
        if [[ -z "$hermetic" ]]; then
            hermetic=$(echo "$yaml" | yq ".spec.pipelineSpec.params | .[] | select(.name==\"hermetic\") | .default")
            [[ -n "$debug" ]] && echo "[debug] hermetic (push): using .spec.pipelineSpec.params.default = $hermetic" >&3
        fi
        
        pull_hermetic=$(echo "$pull_yaml" | yq ".spec.params | .[] | select(.name==\"hermetic\") | .value")
        [[ -n "$debug" ]] && echo "[debug] hermetic (pull): using .spec.params.value = $pull_hermetic" >&3
        if [[ -z "$pull_hermetic" ]]; then
            pull_hermetic=$(echo "$pull_yaml" | yq ".spec.pipelineSpec.params | .[] | select(.name==\"hermetic\") | .default")
            [[ -n "$debug" ]] && echo "[debug] hermetic (pull): using .spec.pipelineSpec.params.default = $pull_hermetic" >&3
        fi
        
        if [[ $hermetic != true || $hermetic != "true" || $pull_hermetic != true || $pull_hermetic != "true" ]]; then
            hermeticbuilds=false
        fi
    fi

    vendor=$(curl -LsH "$authorization" -w "%{http_code}" "https://api.github.com/repos/$org/$repo/contents/vendor")
    vendor="${vendor: -3}"
    
    # Check prefetch-input (first .spec.params.value, then fallback to .spec.pipelineSpec.params.default)
    prefetch=$(echo "$yaml" | yq ".spec.params | .[] | select(.name==\"prefetch-input\") | .value")
    [[ -n "$debug" ]] && echo "[debug] prefetch-input (push): using .spec.params.value = $prefetch" >&3
    if [[ -z "$prefetch" ]]; then
        prefetch=$(echo "$yaml" | yq ".spec.pipelineSpec.params | .[] | select(.name==\"prefetch-input\") | .default")
        [[ -n "$debug" ]] && echo "[debug] prefetch-input (push): using .spec.pipelineSpec.params.default = $prefetch" >&3
    fi
    
    pull_prefetch=$(echo "$pull_yaml" | yq ".spec.params | .[] | select(.name==\"prefetch-input\") | .value")
    [[ -n "$debug" ]] && echo "[debug] prefetch-input (pull): using .spec.params.value = $pull_prefetch" >&3
    if [[ -z "$pull_prefetch" ]]; then
        pull_prefetch=$(echo "$pull_yaml" | yq ".spec.pipelineSpec.params | .[] | select(.name==\"prefetch-input\") | .default")
        [[ -n "$debug" ]] && echo "[debug] prefetch-input (pull): using .spec.pipelineSpec.params.default = $pull_prefetch" >&3
    fi
    
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
        echo "🟥 $repo hermetic builds: FALSE" >&3
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
    
    # Check build-platforms (first .spec.params.value, then fallback to .spec.pipelineSpec.params.default)
    platforms_value=$(echo "$yaml" | yq ".spec.params | .[] | select(.name==\"build-platforms\") | .value | .[]")
    if [[ -z "$platforms_value" ]]; then
        platforms_value=$(echo "$yaml" | yq ".spec.pipelineSpec.params | .[] | select(.name==\"build-platforms\") | .default | .[]")
    fi
    
    platforms=$(echo "$platforms_value" | wc -l | tr -d ' \t\n')
    if  [[ $platforms != 4 ]]; then
        echo "🟥 $repo Multiarch: FALSE" >&3
        echo "Not Enabled"
    else
        echo "🟩 $repo Multiarch: TRUE" >&3
        echo "Enabled"
    fi
}

if [[ -n "$debug" && "$debug" != "true" ]]; then
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

    data="$data,$(check_hermetic_builds "$yaml" "$pull_yaml" "$authorization" "$org" "$repo")"

    data="$data,$(check_enterprise_contract "$application" "$line" "$authorization" "$org" "$repo" "$branch")"

    data="$data,$(check_multiarch_support "$yaml" "$repo")"

    echo ""

    echo "$data" >> $compliancefile
done