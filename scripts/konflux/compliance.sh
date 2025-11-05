#!/usr/bin/env bash

exec 3>&1

# Debug output function
debug_echo() {
  if [ "$debug" = true ]; then
    echo "$@" >&3
  fi
}

show_help() {
    cat << EOF
Usage: compliance.sh [OPTIONS] <application>

Check compliance status for Konflux components

ARGUMENTS:
    <application>    The application name to check (e.g., acm-215)

OPTIONS:
    --debug=<component>   Run against a specific Konflux component only
    --debug               Enable debug logging output
    --retrigger           Retrigger failed components automatically
    --squad=<squad>       Run against components owned by a specific squad
    -h, --help            Show this help message

EXAMPLES:
    compliance.sh acm-215
    compliance.sh --debug=my-component acm-215
    compliance.sh --debug acm-215
    compliance.sh --retrigger acm-215
    compliance.sh --squad=policy acm-215
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
        --retrigger)
            retrigger=true
            shift
            ;;
        --squad=*)
            squad="${1#*=}"
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

# Check that we're in the correct OpenShift project
echo "Checking OpenShift project..."
oc_project_output=$(oc project 2>&1)
if [[ ! "$oc_project_output" == *"Using project \"crt-redhat-acm-tenant\""* ]]; then
    echo "Error: Not in the correct OpenShift project."
    echo "Expected: Using project \"crt-redhat-acm-tenant\""
    echo "Got: $oc_project_output"
    exit 1
fi
echo "Verified: In correct OpenShift project (crt-redhat-acm-tenant)"

mkdir -p data
compliancefile="data/$application-compliance.csv"
> $compliancefile

# Write CSV header
echo "Konflux Component,Promoted Time,Promoted Status,Hermetic Builds,Enterprise Contract,Multiarch Support,Push Status,Push PipelineRun URL,EC PipelineRun URL" > $compliancefile

# Function to get components for a specific squad from YAML config
get_squad_components() {
    local squad_key="$1"
    # Get the directory where this script is located
    local script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    local config_file="$script_dir/component-squad.yaml"

    if [[ ! -f "$config_file" ]]; then
        echo "Error: $config_file not found"
        exit 1
    fi

    debug_echo "[debug] Squad Key: $squad_key"

    # Parse the YAML file and extract component names for the specified squad
    local components=$(yq ".squads.\"${squad_key}\".components[]" "$config_file" 2>/dev/null)

    if [[ -z "$components" ]]; then
        echo "Error: No components found for squad '$squad_key' in $config_file" >&3
        echo "" >&3
        echo "Available squads:" >&3
        echo $(yq '.squads | to_entries | .[] | .key + " (" + .value.name + ")"' "$config_file") >&3
        echo "INVALID_SQUAD"
        exit 1
    fi

    debug_echo "[debug] Components"
    debug_echo "$components"
    echo "$components"
}

echo "Checking for Github auth token"
authorization=""
if [ -f "authorization.txt" ]; then
	authorization="Authorization: Bearer $(cat "authorization.txt")"
	echo "Authorization found. Applying to github API requests"
fi

# Detect macOS ARM64 for skopeo platform override
detected_os=$(uname -s)
detected_arch=$(uname -m)
if [[ "$detected_os" == "Darwin" && "$detected_arch" == "arm64" ]]; then
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
            buildtime="$(echo "$skopeo" | yq -p=json ".Labels.build-date" | sed 's/Z$//'),Successful"
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
    debug_echo "[debug] pathInRepo (push): using .spec = $pathinrepo"
    if [[ -z "$pathinrepo" ]]; then
        pathinrepo=$(echo "$yaml" | yq ".spec.pipelineSpec.pipelineRef.params | .[] | select(.name==\"pathInRepo\")")
        debug_echo "[debug] pathInRepo (push): using .spec.pipelineSpec fallback = $pathinrepo"
    fi
    
    pullpathinrepo=$(echo "$pull_yaml" | yq ".spec.pipelineRef.params | .[] | select(.name==\"pathInRepo\")")
    debug_echo "[debug] pathInRepo (pull): using .spec = $pullpathinrepo"
    if [[ -z "$pullpathinrepo" ]]; then
        pullpathinrepo=$(echo "$pull_yaml" | yq ".spec.pipelineSpec.pipelineRef.params | .[] | select(.name==\"pathInRepo\")")
        debug_echo "[debug] pathInRepo (pull): using .spec.pipelineSpec fallback = $pullpathinrepo"
    fi

    if [[ -z "$pathinrepo" || -z "$pullpathinrepo" ]]; then
        # Check build-source-image (first .spec.params.value, then fallback to .spec.pipelineSpec.params.default)
        buildsourceimage=$(echo "$yaml" | yq ".spec.params | .[] | select(.name==\"build-source-image\") | .value")
        debug_echo "[debug] build-source-image (push): using .spec.params.value = $buildsourceimage"
        if [[ -z "$buildsourceimage" ]]; then
            buildsourceimage=$(echo "$yaml" | yq ".spec.pipelineSpec.params | .[] | select(.name==\"build-source-image\") | .default")
            debug_echo "[debug] build-source-image (push): using .spec.pipelineSpec.params.default = $buildsourceimage"
        fi
        
        pull_bsi=$(echo "$pull_yaml" | yq ".spec.params | .[] | select(.name==\"build-source-image\") | .value")
        debug_echo "[debug] build-source-image (pull): using .spec.params.value = $pull_bsi"
        if [[ -z "$pull_bsi" ]]; then
            pull_bsi=$(echo "$pull_yaml" | yq ".spec.pipelineSpec.params | .[] | select(.name==\"build-source-image\") | .default")
            debug_echo "[debug] build-source-image (pull): using .spec.pipelineSpec.params.default = $pull_bsi"
        fi
        
        if [[ !($buildsourceimage == true || $buildsourceimage == "true") || !($pull_bsi == true || $pull_bse == "true") ]]; then
            hermeticbuilds=false
        fi

        # Check hermetic (first .spec.params.value, then fallback to .spec.pipelineSpec.params.default)
        hermetic=$(echo "$yaml" | yq ".spec.params | .[] | select(.name==\"hermetic\") | .value")
        debug_echo "[debug] hermetic (push): using .spec.params.value = $hermetic"
        if [[ -z "$hermetic" ]]; then
            hermetic=$(echo "$yaml" | yq ".spec.pipelineSpec.params | .[] | select(.name==\"hermetic\") | .default")
            debug_echo "[debug] hermetic (push): using .spec.pipelineSpec.params.default = $hermetic"
        fi
        
        pull_hermetic=$(echo "$pull_yaml" | yq ".spec.params | .[] | select(.name==\"hermetic\") | .value")
        debug_echo "[debug] hermetic (pull): using .spec.params.value = $pull_hermetic"
        if [[ -z "$pull_hermetic" ]]; then
            pull_hermetic=$(echo "$pull_yaml" | yq ".spec.pipelineSpec.params | .[] | select(.name==\"hermetic\") | .default")
            debug_echo "[debug] hermetic (pull): using .spec.pipelineSpec.params.default = $pull_hermetic"
        fi
        
        if [[ $hermetic != true || $hermetic != "true" || $pull_hermetic != true || $pull_hermetic != "true" ]]; then
            hermeticbuilds=false
        fi
    fi

    vendor=$(curl -LsH "$authorization" -w "%{http_code}" "https://api.github.com/repos/$org/$repo/contents/vendor")
    vendor="${vendor: -3}"
    
    # Check prefetch-input (first .spec.params.value, then fallback to .spec.pipelineSpec.params.default)
    prefetch=$(echo "$yaml" | yq ".spec.params | .[] | select(.name==\"prefetch-input\") | .value")
    debug_echo "[debug] prefetch-input (push): using .spec.params.value = $prefetch"
    if [[ -z "$prefetch" ]]; then
        prefetch=$(echo "$yaml" | yq ".spec.pipelineSpec.params | .[] | select(.name==\"prefetch-input\") | .default")
        debug_echo "[debug] prefetch-input (push): using .spec.pipelineSpec.params.default = $prefetch"
    fi
    
    pull_prefetch=$(echo "$pull_yaml" | yq ".spec.params | .[] | select(.name==\"prefetch-input\") | .value")
    debug_echo "[debug] prefetch-input (pull): using .spec.params.value = $pull_prefetch"
    if [[ -z "$pull_prefetch" ]]; then
        pull_prefetch=$(echo "$pull_yaml" | yq ".spec.pipelineSpec.params | .[] | select(.name==\"prefetch-input\") | .default")
        debug_echo "[debug] prefetch-input (pull): using .spec.pipelineSpec.params.default = $pull_prefetch"
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
        check_run_data=$(curl -LsH "$authorization" "https://api.github.com/repos/$org/$repo/check-suites/$suite_id/check-runs" | yq -p=json ".check_runs[] | select(.name==\"*enterprise-contract*$line\")")
        debug_echo "[debug] EC check_run_data: $check_run_data"
        ec=$(echo "$check_run_data" | yq ".conclusion")
        # Extract PipelineRun URL from output.text (embedded in HTML link)
        output_text=$(echo "$check_run_data" | yq ".output.text")
        ec_url=$(echo "$output_text" | sed -n 's/.*href="\(https:\/\/konflux-ui[^"]*pipelinerun\/[^"]*\)".*/\1/p' | head -1)
        debug_echo "[debug] EC ec=$ec, ec_url=$ec_url"
    else
        # Fallback to original method
        check_run_data=$(curl -LsH "$authorization" "https://api.github.com/repos/$org/$repo/commits/$branch/check-runs" | yq -p=json ".check_runs[] | select(.app.name == \"Red Hat Konflux\") | select(.name==\"*enterprise-contract*$line\")")
        debug_echo "[debug] EC check_run_data (fallback): $check_run_data"
        ec=$(echo "$check_run_data" | yq ".conclusion")
        # Extract PipelineRun URL from output.text (embedded in HTML link)
        output_text=$(echo "$check_run_data" | yq ".output.text")
        ec_url=$(echo "$output_text" | sed -n 's/.*href="\(https:\/\/konflux-ui[^"]*pipelinerun\/[^"]*\)".*/\1/p' | head -1)
        debug_echo "[debug] EC ec=$ec, ec_url=$ec_url"
    fi

    if [[ -n "$ec" ]] && ! echo "$ec" | grep -v "^success$" > /dev/null; then
        echo "🟩 $repo $ecname: SUCCESS" >&3
        echo "Compliant|$ec_url"
    else
        echo "🟥 $repo $ecname: FAILURE (ec was: \"$ec\")" >&3
        if [[ -z "$ec" ]]; then
            echo "EC_BLANK|$ec_url"
        elif [[ "$ec" == "cancelled" ]]; then
            echo "EC_CANCELED|$ec_url"
        else
            echo "Not Compliant|$ec_url"
        fi
    fi
}

# Function to check component on-push task run
check_component_on_push() {
    local line="$1"
    local authorization="$2"
    local org="$3"
    local repo="$4"
    local branch="$5"

    pushname="Red Hat Konflux / $line-on-push"

    # Try check-suites first (more reliable for Konflux)
    suite_id=$(curl -LsH "$authorization" "https://api.github.com/repos/$org/$repo/commits/$branch/check-suites" | yq -p=json ".check_suites[] | select(.app.name == \"Red Hat Konflux\") | .id" | head -1)

    if [[ -n "$suite_id" ]]; then
        # Use suite method for Konflux
        check_run_data=$(curl -LsH "$authorization" "https://api.github.com/repos/$org/$repo/check-suites/$suite_id/check-runs" | yq -p=json ".check_runs[] | select(.name==\"Red Hat Konflux / $line-on-push\")")
        debug_echo "[debug] Push check_run_data: $check_run_data"
        push_status=$(echo "$check_run_data" | yq ".conclusion")
        push_url=$(echo "$check_run_data" | yq ".details_url")
        debug_echo "[debug] Push push_status=$push_status, push_url=$push_url"
    else
        # Fallback to original method
        check_run_data=$(curl -LsH "$authorization" "https://api.github.com/repos/$org/$repo/commits/$branch/check-runs" | yq -p=json ".check_runs[] | select(.app.name == \"Red Hat Konflux\") | select(.name==\"Red Hat Konflux / $line-on-push\")")
        debug_echo "[debug] Push check_run_data (fallback): $check_run_data"
        push_status=$(echo "$check_run_data" | yq ".conclusion")
        push_url=$(echo "$check_run_data" | yq ".details_url")
        debug_echo "[debug] Push push_status=$push_status, push_url=$push_url"
    fi

    if [[ -n "$push_status" ]] && ! echo "$push_status" | grep -v "^success$" > /dev/null; then
        echo "🟩 $repo $pushname: SUCCESS" >&3
        echo "Successful|$push_url"
    else
        echo "🟥 $repo $pushname: FAILURE (status was: \"$push_status\")" >&3
        echo "Failed|$push_url"
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

# Function to check if component is a bundle operator
check_bundle_operator() {
    local component="$1"
    
    # Check if component starts with "mce-operator-bundle" or "acm-operator-bundle"
    if [[ "$component" == mce-operator-bundle* || "$component" == acm-operator-bundle* ]]; then
        echo "🟡 $component Bundle Operator: TRUE" >&3
        echo "🟡 $component Hermetic: Not Applicable" >&3
        echo "🟡 $component Multiarch: Not Applicable" >&3
        echo "BUNDLE_OPERATOR"
    else
        echo "REGULAR_COMPONENT"
    fi
}

if [[ -n "$debug" && "$debug" != "true" ]]; then
    components=$debug
elif [[ -n "$squad" ]]; then
    # Get components for the specified squad
    squad_components=$(get_squad_components "$squad")
    if [[ "$squad_components" == "INVALID_SQUAD" ]]; then
        exit 1
    fi
    # Filter by application
    components=$(oc get components | grep $application | awk '{print $1}' | grep -F -f <(echo "$squad_components"))
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

    debug_echo "[debug] Push: $push\n[debug] Pull: $pull" # debug

    echo "--- $line : $org/$repo : $branch ---"
    yaml=$(curl -Ls -w "%{http_code}" $push)
    http_code_push="${yaml: -3}"
    yaml="${yaml%???}"
    [[ -n "$debug" && "$http_code_push" == "404" ]] && echo -e "[debug] \033[31m404 error\033[0m fetching push YAML from $push" >&3
    
    pull_yaml=$(curl -Ls -w "%{http_code}" $pull)
    http_code_pull="${pull_yaml: -3}"
    pull_yaml="${pull_yaml%???}"
    [[ -n "$debug" && "$http_code_pull" == "404" ]] && echo -e "[debug] \033[31m404 error\033[0m fetching pull YAML from $pull" >&3

    # Check if component is a bundle operator
    bundle_result=$(check_bundle_operator "$line")
    
    # Check hermetic builds (skip for bundle operators)
    if [[ "$bundle_result" == "BUNDLE_OPERATOR" ]]; then
        data="$data,Not Applicable"
    else
        data="$data,$(check_hermetic_builds "$yaml" "$pull_yaml" "$authorization" "$org" "$repo")"
    fi

    # Check enterprise contract
    ec_result=$(check_enterprise_contract "$application" "$line" "$authorization" "$org" "$repo" "$branch")
    # Extract EC status and URL (format: "Status|URL")
    ec_status="${ec_result%%|*}"
    ec_url="${ec_result##*|}"

    # Always check on-push to get the push URL
    push_result=$(check_component_on_push "$line" "$authorization" "$org" "$repo" "$branch")
    # Extract push status and URL (format: "Status|URL")
    push_status="${push_result%%|*}"
    push_url="${push_result##*|}"

    # If EC was blank or canceled, check on-push status to determine final EC result
    if [[ "$ec_status" == "EC_BLANK" || "$ec_status" == "EC_CANCELED" ]]; then
        if [[ "$push_status" == "Successful" ]]; then
            ec_status="Not Compliant"
        else
            ec_status="Push Failure"
        fi
    fi

    data="$data,$ec_status"

    # Check multiarch support (skip for bundle operators)
    if [[ "$bundle_result" == "BUNDLE_OPERATOR" ]]; then
        data="$data,Not Applicable"
    else
        data="$data,$(check_multiarch_support "$yaml" "$repo")"
    fi

    # Append Push Status and PipelineRun URLs
    data="$data,$push_status,$push_url,$ec_url"

    echo ""

    echo "$line,$data" >> $compliancefile

    # Retrigger component if build failed and --retrigger flag is set
    if [[ "$retrigger" == "true" ]]; then
        # Check if component has any failures (Push Failure or actual Failed status, but not Successful)
        if echo "$data" | grep -qE "(^|,)(Failed|Push Failure|IMAGE_PULL_FAILURE|INSPECTION_FAILURE|DIGEST_FAILURE|Not Enabled|Not Compliant)(,|$)"; then
            echo "🔄 Retriggering component: $line" >&3
            kubectl annotate components/$line build.appstudio.openshift.io/request=trigger-pac-build --overwrite
            if [ $? -eq 0 ]; then
                echo "✅ Successfully triggered rebuild for $line" >&3
            else
                echo "❌ Failed to trigger rebuild for $line" >&3
            fi
        fi
    fi
done
