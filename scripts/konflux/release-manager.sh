#!/bin/bash

# ACM/MCE Release Manager Script
# This script manages the creation, application, and monitoring of ACM and MCE releases

set -euo pipefail

#######################################
# CONFIGURATION
#######################################

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default values
REPO_DIR="${ACM_RELEASE_REPO:-acm-release-management}"
NAMESPACE="crt-redhat-acm-tenant"
PIPELINE_NAMESPACE="rhtap-releng-tenant"
AUTHOR="${USER}"

# Release type mappings
declare -A RELEASE_TYPE_MAP=(
    ["payload-rhsa"]="RHSA"
    ["payload-rhba"]="RHBA"
    ["bundle"]="RHBA"
    ["catalog"]="RHEA"
)

#######################################
# HELPER FUNCTIONS
#######################################

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Parse version string (e.g., "2.8.4" or "ACM-2.13.5")
parse_version() {
    local version="$1"
    # Remove ACM- or MCE- prefix if present
    version="${version#ACM-}"
    version="${version#MCE-}"
    echo "$version"
}

# Get short version (e.g., "2.8.4" -> "28")
get_short_version() {
    local version="$1"
    version=$(parse_version "$version")
    local major=$(echo "$version" | cut -d. -f1)
    local minor=$(echo "$version" | cut -d. -f2)
    echo "${major}${minor}"
}

# Get patch number (e.g., "2.8.4" -> "4")
get_patch_number() {
    local version="$1"
    version=$(parse_version "$version")
    echo "$version" | cut -d. -f3
}

# Get product prefix (acm or mce) in lowercase
get_product_prefix() {
    local product="$1"
    echo "${product,,}" # Convert to lowercase
}

# Get product name for catalog release plan
get_catalog_product_name() {
    local product="$1"
    if [[ "$product" == "ACM" ]]; then
        echo "acm-operator"
    else
        echo "mce-operator"
    fi
}

#######################################
# YAML GENERATION FUNCTIONS
#######################################

generate_payload_yaml() {
    local product="$1"      # ACM or MCE
    local version="$2"      # e.g., 2.8.4
    local stage="$3"        # prod or stage
    local rc_num="$4"       # RC number (only for stage)
    local cves="$5"         # CVE list (optional)

    local short_ver=$(get_short_version "$version")
    local patch_num=$(get_patch_number "$version")
    local product_lower=$(get_product_prefix "$product")

    local release_name="${stage}-publish-${product_lower}-${short_ver}"
    local release_plan="${stage}-publish-${product_lower}-${short_ver}"
    local snapshot_name=""  # Empty initially

    local file_suffix="z${patch_num}"
    if [[ "$stage" == "stage" ]]; then
        release_name="${release_name}-z${patch_num}-rc${rc_num}"
        file_suffix="z${patch_num}-rc${rc_num}"
    else
        release_name="${release_name}-z${patch_num}"
    fi

    local filename="${product_lower}-${short_ver}-payload-${stage}-${file_suffix}.yaml"

    # Determine release type
    local release_type="RHSA"  # Default for payloads with CVEs
    if [[ -z "$cves" ]]; then
        release_type="RHBA"
    fi

    cat > "$filename" <<EOF
apiVersion: appstudio.redhat.com/v1alpha1
kind: Release
metadata:
  name: ${release_name}
  namespace: ${NAMESPACE}
  labels:
    release.appstudio.openshift.io/author: "${AUTHOR}"
spec:
  snapshot: ""
  releasePlan: ${release_plan}
  data:
    releaseNotes:
      type: ${release_type}
EOF

    # Add references for ACM
    if [[ "$product" == "ACM" && "$release_type" == "RHSA" ]]; then
        cat >> "$filename" <<EOF
      references:
        - https://access.redhat.com/security/updates/classification/#important
EOF
    fi

    # Add CVEs if provided
    if [[ -n "$cves" ]]; then
        echo "      cves:" >> "$filename"
        # CVEs will be added here from Jira query
    fi

    echo "$filename"
}

generate_bundle_yaml() {
    local product="$1"      # ACM or MCE
    local version="$2"      # e.g., 2.8.4
    local stage="$3"        # prod or stage
    local rc_num="$4"       # RC number (only for stage)

    local short_ver=$(get_short_version "$version")
    local patch_num=$(get_patch_number "$version")
    local product_lower=$(get_product_prefix "$product")

    local release_name="${stage}-publish-bundle-${product_lower}-${short_ver}"
    local release_plan="${stage}-publish-bundle-${product_lower}-${short_ver}"

    local file_suffix="z${patch_num}"
    if [[ "$stage" == "stage" ]]; then
        release_name="${release_name}-z${patch_num}-rc${rc_num}"
        file_suffix="z${patch_num}-rc${rc_num}"
    else
        release_name="${release_name}-z${patch_num}"
    fi

    local filename="${product_lower}-${short_ver}-bundle-${stage}-${file_suffix}.yaml"

    cat > "$filename" <<EOF
apiVersion: appstudio.redhat.com/v1alpha1
kind: Release
metadata:
  name: ${release_name}
  namespace: ${NAMESPACE}
  labels:
    release.appstudio.openshift.io/author: "${AUTHOR}"
spec:
  snapshot: ""
  releasePlan: ${release_plan}
  data:
    releaseNotes:
      type: RHBA
EOF

    echo "$filename"
}

generate_catalog_yaml() {
    local product="$1"      # ACM or MCE
    local version="$2"      # e.g., 2.8.4
    local stage="$3"        # prod or stage
    local rc_num="$4"       # RC number (only for stage)
    local suffix="$5"       # Optional suffix (e.g., "with-ss-10")

    local short_ver=$(get_short_version "$version")
    local patch_num=$(get_patch_number "$version")
    local product_lower=$(get_product_prefix "$product")
    local catalog_product=$(get_catalog_product_name "$product")

    local release_name="${stage}-publish-catalog-${product_lower}-${short_ver}"
    local release_plan="${catalog_product}-release-plan-${stage}"

    local file_suffix="z${patch_num}"
    if [[ "$stage" == "stage" ]]; then
        release_name="${release_name}-z${patch_num}-rc${rc_num}"
        file_suffix="z${patch_num}-rc${rc_num}"
    else
        release_name="${release_name}-z${patch_num}"
    fi

    # Add optional suffix to name
    if [[ -n "$suffix" ]]; then
        release_name="${release_name}-${suffix}"
    fi

    local filename="${product_lower}-${short_ver}-catalog-${stage}-${file_suffix}.yaml"

    cat > "$filename" <<EOF
apiVersion: appstudio.redhat.com/v1alpha1
kind: Release
metadata:
  name: ${release_name}
  namespace: ${NAMESPACE}
  labels:
    release.appstudio.openshift.io/author: "${AUTHOR}"
spec:
  snapshot: ""
  releasePlan: ${release_plan}
  data:
    releaseNotes:
      type: RHEA
      references:
        - https://access.redhat.com/security/updates/classification/#important
EOF

    echo "$filename"
}

#######################################
# DIRECTORY AND FILE CREATION
#######################################

create_release_structure() {
    local product="$1"      # ACM or MCE
    local version="$2"      # e.g., 2.8.4
    local rc_count="${3:-1}"  # Number of RC versions to create (default 1)

    local version_clean=$(parse_version "$version")
    local product_upper="${product^^}"
    local release_dir="${REPO_DIR}/${product_upper}/${product_upper}-${version_clean}"

    log_info "Creating release structure for ${product_upper}-${version_clean}"

    # Create main release directory
    mkdir -p "$release_dir"
    cd "$release_dir"

    # Generate prod release files
    log_info "Generating production release files..."
    local payload_file=$(generate_payload_yaml "$product" "$version_clean" "prod" "" "")
    local bundle_file=$(generate_bundle_yaml "$product" "$version_clean" "prod" "")
    local catalog_file=$(generate_catalog_yaml "$product" "$version_clean" "prod" "" "")

    log_success "Created: $payload_file"
    log_success "Created: $bundle_file"
    log_success "Created: $catalog_file"

    # Generate RC release files
    for ((i=1; i<=rc_count; i++)); do
        local rc_dir="rc${i}"
        mkdir -p "$rc_dir"
        cd "$rc_dir"

        log_info "Generating RC${i} release files..."
        local rc_payload=$(generate_payload_yaml "$product" "$version_clean" "stage" "$i" "")
        local rc_bundle=$(generate_bundle_yaml "$product" "$version_clean" "stage" "$i")
        local rc_catalog=$(generate_catalog_yaml "$product" "$version_clean" "stage" "$i" "")

        log_success "Created: $rc_dir/$rc_payload"
        log_success "Created: $rc_dir/$rc_bundle"
        log_success "Created: $rc_dir/$rc_catalog"

        cd ..
    done

    log_success "Release structure created at: $release_dir"
    cd - > /dev/null
}

#######################################
# RELEASE APPLICATION AND MONITORING
#######################################

apply_release() {
    local release_file="$1"

    if [[ ! -f "$release_file" ]]; then
        log_error "Release file not found: $release_file"
        return 1
    fi

    log_info "Applying release: $release_file"
    oc create -f "$release_file"

    if [[ $? -eq 0 ]]; then
        log_success "Release applied successfully"

        # Extract release name from the file
        local release_name=$(grep "name:" "$release_file" | head -1 | awk '{print $2}')
        echo "$release_name"
    else
        log_error "Failed to apply release"
        return 1
    fi
}

get_pipelinerun_for_release() {
    local release_name="$1"
    local timeout="${2:-300}"  # 5 minutes default timeout
    local elapsed=0
    local interval=5

    log_info "Waiting for PipelineRun to be created for release: $release_name"

    while [[ $elapsed -lt $timeout ]]; do
        # Look for PipelineRun with label matching the release
        local pipelinerun=$(oc get pipelinerun -n "$PIPELINE_NAMESPACE" \
            -l "appstudio.openshift.io/component=$release_name" \
            --sort-by=.metadata.creationTimestamp \
            -o jsonpath='{.items[-1].metadata.name}' 2>/dev/null)

        if [[ -n "$pipelinerun" ]]; then
            echo "$pipelinerun"
            return 0
        fi

        sleep $interval
        elapsed=$((elapsed + interval))
        echo -n "." >&2
    done

    echo "" >&2
    log_error "Timeout waiting for PipelineRun to be created"
    return 1
}

monitor_pipelinerun() {
    local pipelinerun="$1"

    log_info "Monitoring PipelineRun: $pipelinerun"

    local start_time=$(date +%s)
    local status=""
    local reason=""

    while true; do
        # Get PipelineRun status
        local pr_json=$(oc get pipelinerun "$pipelinerun" -n "$PIPELINE_NAMESPACE" -o json 2>/dev/null)

        if [[ -z "$pr_json" ]]; then
            log_error "PipelineRun not found: $pipelinerun"
            return 1
        fi

        status=$(echo "$pr_json" | jq -r '.status.conditions[] | select(.type=="Succeeded") | .status' 2>/dev/null)
        reason=$(echo "$pr_json" | jq -r '.status.conditions[] | select(.type=="Succeeded") | .reason' 2>/dev/null)

        case "$status" in
            "True")
                local end_time=$(date +%s)
                local duration=$((end_time - start_time))
                log_success "PipelineRun completed successfully"
                log_info "Duration: $(format_duration $duration)"
                return 0
                ;;
            "False")
                local end_time=$(date +%s)
                local duration=$((end_time - start_time))
                log_error "PipelineRun failed"
                log_info "Reason: $reason"
                log_info "Duration: $(format_duration $duration)"

                # Get detailed failure information
                show_failure_details "$pipelinerun"
                return 1
                ;;
            "Unknown"|"")
                # Still running
                echo -n "." >&2
                sleep 10
                ;;
        esac
    done
}

show_failure_details() {
    local pipelinerun="$1"

    log_info "Fetching failure details..."

    # Get failed tasks
    local failed_tasks=$(oc get pipelinerun "$pipelinerun" -n "$PIPELINE_NAMESPACE" \
        -o json | jq -r '.status.taskRuns // {} | to_entries[] | select(.value.status.conditions[]? | select(.type=="Succeeded" and .status=="False")) | .key')

    if [[ -n "$failed_tasks" ]]; then
        log_error "Failed tasks:"
        echo "$failed_tasks" | while read -r task_key; do
            local task_name=$(oc get pipelinerun "$pipelinerun" -n "$PIPELINE_NAMESPACE" \
                -o json | jq -r ".status.taskRuns[\"$task_key\"].pipelineTaskName")
            local task_reason=$(oc get pipelinerun "$pipelinerun" -n "$PIPELINE_NAMESPACE" \
                -o json | jq -r ".status.taskRuns[\"$task_key\"].status.conditions[] | select(.type==\"Succeeded\") | .message")

            echo -e "${RED}  - Task: $task_name${NC}"
            echo -e "${RED}    Reason: $task_reason${NC}"
        done
    fi

    # Show logs URL
    log_info "View full logs with: oc logs -n $PIPELINE_NAMESPACE $pipelinerun"
}

format_duration() {
    local duration=$1
    local hours=$((duration / 3600))
    local minutes=$(((duration % 3600) / 60))
    local seconds=$((duration % 60))

    if [[ $hours -gt 0 ]]; then
        echo "${hours}h ${minutes}m ${seconds}s"
    elif [[ $minutes -gt 0 ]]; then
        echo "${minutes}m ${seconds}s"
    else
        echo "${seconds}s"
    fi
}

#######################################
# MAIN COMMANDS
#######################################

cmd_create() {
    local product="$1"
    local version="$2"
    local rc_count="${3:-1}"

    if [[ -z "$product" || -z "$version" ]]; then
        log_error "Usage: $0 create <ACM|MCE> <version> [rc_count]"
        log_error "Example: $0 create MCE 2.8.4 1"
        return 1
    fi

    create_release_structure "$product" "$version" "$rc_count"
}

cmd_apply() {
    local release_file="$1"
    local watch="${2:-false}"

    if [[ -z "$release_file" ]]; then
        log_error "Usage: $0 apply <release_file> [--watch]"
        return 1
    fi

    local release_name=$(apply_release "$release_file")

    if [[ $? -eq 0 && "$watch" == "--watch" ]]; then
        local pipelinerun=$(get_pipelinerun_for_release "$release_name")
        if [[ $? -eq 0 ]]; then
            monitor_pipelinerun "$pipelinerun"
        fi
    fi
}

cmd_watch() {
    local release_name="$1"

    if [[ -z "$release_name" ]]; then
        log_error "Usage: $0 watch <release_name>"
        return 1
    fi

    local pipelinerun=$(get_pipelinerun_for_release "$release_name")
    if [[ $? -eq 0 ]]; then
        monitor_pipelinerun "$pipelinerun"
    fi
}

cmd_update_advisory() {
    local version="$1"
    local target="${2:-prod}"
    local jql="${3:-}"

    if [[ -z "$version" ]]; then
        log_error "Usage: $0 update-advisory <version> [target] [custom-jql]"
        log_error "  target: 'prod' (default), 'rc1', 'rc2', etc."
        log_error ""
        log_error "Examples:"
        log_error "  $0 update-advisory ACM-2.14.1"
        log_error "  $0 update-advisory ACM-2.14.1 prod"
        log_error "  $0 update-advisory MCE-2.8.4 rc1"
        log_error "  $0 update-advisory MCE-2.8.4 rc2"
        return 1
    fi

    # Get the directory where this script is located
    local script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    local updater="${script_dir}/update-advisory.py"

    if [[ ! -f "$updater" ]]; then
        log_error "Advisory updater script not found: $updater"
        return 1
    fi

    log_info "Updating advisory for $version (target: $target)"

    if [[ -n "$jql" ]]; then
        python3 "$updater" "$version" "$target" "$jql"
    else
        python3 "$updater" "$version" "$target"
    fi
}

cmd_help() {
    cat <<EOF
ACM/MCE Release Manager

Usage: $0 <command> [options]

Commands:
  create <ACM|MCE> <version> [rc_count]
      Create release structure with prod and RC files
      Example: $0 create MCE 2.8.4 1
      Example: $0 create ACM 2.13.5 2

  apply <release_file> [--watch]
      Apply a release file and optionally watch the build
      Example: $0 apply mce-28-payload-prod-z4.yaml
      Example: $0 apply mce-28-payload-prod-z4.yaml --watch

  watch <release_name>
      Watch an existing release build
      Example: $0 watch prod-publish-mce-28-z4

  update-advisory <version> [target] [custom-jql]
      Update payload file with bug fixes and CVEs from Jira
      target: 'prod' (default), 'rc1', 'rc2', etc.
      Example: $0 update-advisory ACM-2.14.1
      Example: $0 update-advisory ACM-2.14.1 prod
      Example: $0 update-advisory MCE-2.8.4 rc1
      Example: $0 update-advisory MCE-2.8.4 rc2
      Example: $0 update-advisory "ACM 2.14.1" prod "custom JQL query"

  help
      Show this help message

Environment Variables:
  ACM_RELEASE_REPO    Path to acm-release-management repo (default: ./acm-release-management)
  USER                Your username for the release author field

Examples:
  # Create MCE-2.8.4 with 1 RC
  $0 create MCE 2.8.4 1

  # Create ACM-2.13.5 with 2 RCs
  $0 create ACM 2.13.5 2

  # Apply and watch a release
  $0 apply acm-release-management/ACM/ACM-2.13.5/acm-213-payload-prod-z5.yaml --watch

  # Update advisory data from Jira for prod
  $0 update-advisory ACM-2.14.1 prod

  # Update advisory data for RC1
  $0 update-advisory MCE-2.8.4 rc1
EOF
}

#######################################
# MAIN
#######################################

main() {
    local command="${1:-help}"
    shift || true

    case "$command" in
        create)
            cmd_create "$@"
            ;;
        apply)
            cmd_apply "$@"
            ;;
        watch)
            cmd_watch "$@"
            ;;
        update-advisory)
            cmd_update_advisory "$@"
            ;;
        help|--help|-h)
            cmd_help
            ;;
        *)
            log_error "Unknown command: $command"
            cmd_help
            exit 1
            ;;
    esac
}

main "$@"
