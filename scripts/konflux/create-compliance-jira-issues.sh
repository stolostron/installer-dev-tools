#!/usr/bin/env bash

set -euo pipefail

# ==============================================================================
# Script: create-compliance-jira-issues.sh
# Description: Create JIRA issues for non-compliant Konflux components
# ==============================================================================

# ==============================================================================
# CONFIGURATION AND CONSTANTS
# ==============================================================================

# Color codes for output
readonly RED='\033[0;31m'
readonly GREEN='\033[0;32m'
readonly YELLOW='\033[1;33m'
readonly BLUE='\033[0;34m'
readonly NC='\033[0m' # No Color

# Compliance status constants
readonly STATUS_FAILED="Failed"
readonly STATUS_SUCCESSFUL="Successful"
readonly STATUS_NOT_ENABLED="Not Enabled"
readonly STATUS_NOT_COMPLIANT="Not Compliant"
readonly STATUS_PUSH_FAILURE="Push Failure"
readonly STATUS_COMPLIANT="Compliant"
readonly STATUS_ENABLED="Enabled"
readonly STATUS_IMAGE_PULL_FAILURE="IMAGE_PULL_FAILURE"
readonly STATUS_INSPECTION_FAILURE="INSPECTION_FAILURE"
readonly STATUS_DIGEST_FAILURE="DIGEST_FAILURE"

# JIRA field constants
readonly JIRA_ACTIVITY_TYPE="Quality / Stability / Reliability"
readonly JIRA_SEVERITY="Critical"
readonly DEFAULT_LABELS="konflux,compliance,auto-created"
readonly DEFAULT_JIRA_SERVER="https://issues.redhat.com"

# CSV field requirements
readonly MIN_CSV_FIELDS=9

# Image staleness threshold (in seconds)
readonly IMAGE_STALE_THRESHOLD=$((14 * 24 * 60 * 60))  # 2 weeks

# ==============================================================================
# GLOBAL VARIABLES
# ==============================================================================

# Default values (can be overridden by command line)
JIRA_PROJECT="${JIRA_PROJECT:-ACM}"
ISSUE_TYPE="Bug"
PRIORITY="Critical"
COMPONENT=""
LABELS="$DEFAULT_LABELS"
DRY_RUN=false
SKIP_DUPLICATES=false
AUTO_CLOSE=false
OUTPUT_JSON=""
COMPLIANCE_FILE=""
DEBUG=false

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Application name (derived from filename)
APP_NAME=""
AFFECTS_VERSION=""

# For auto-close feature: track compliance status
declare -A COMPLIANCE_STATUS
declare -A COMPLIANCE_DETAILS

# ==============================================================================
# UTILITY FUNCTIONS
# ==============================================================================

# Debug helper function
debug_echo() {
    if [[ "$DEBUG" == true ]]; then
        echo -e "$@" >&2
    fi
}

# Print error message and exit
die() {
    echo -e "${RED}Error: $*${NC}" >&2
    exit 1
}

# Print warning message
warn() {
    echo -e "${YELLOW}Warning: $*${NC}" >&2
}

# Print info message
info() {
    echo -e "${BLUE}$*${NC}" >&2
}

# Print success message
success() {
    echo -e "${GREEN}✓${NC} $*" >&2
}

# ==============================================================================
# JIRA OPERATION HELPER FUNCTIONS
# ==============================================================================

# Get JIRA server URL from configuration
get_jira_server_url() {
    local jira_config="${JIRA_CONFIG_FILE:-$HOME/.config/.jira/.config.yml}"
    local url=""

    if [[ -f "$jira_config" ]]; then
        url=$(grep "^[[:space:]]*server:" "$jira_config" | awk '{print $2}' | tr -d '"' 2>/dev/null || echo "")
    fi

    echo "${url:-$DEFAULT_JIRA_SERVER}"
}

# Add a comment to a JIRA issue
# Args: issue_key, comment_text
# Returns: 0 on success, 1 on failure
jira_add_comment() {
    local issue_key="$1"
    local comment_text="$2"

    if [[ "$DRY_RUN" == true ]]; then
        warn "[DRY RUN] Would add comment to issue $issue_key"
        if [[ "$DEBUG" == true ]]; then
            info "Comment:"
            echo "$comment_text" >&2
        fi
        return 0
    fi

    local comment_file=$(mktemp)
    echo "$comment_text" > "$comment_file"

    debug_echo "${BLUE}Adding comment to $issue_key${NC}"
    debug_echo "$(cat "$comment_file")"

    if jira issue comment add "$issue_key" --template "$comment_file" < /dev/null > /dev/null 2>&1; then
        rm -f "$comment_file"
        return 0
    else
        rm -f "$comment_file"
        echo -e "${RED}✗${NC} Failed to add comment to $issue_key" >&2
        return 1
    fi
}

# Add labels to a JIRA issue (only adds labels that don't already exist)
# Args: issue_key, comma-separated labels
# Returns: 0 on success, 1 on failure, 2 if no new labels to add
jira_add_labels() {
    local issue_key="$1"
    local new_labels="$2"

    if [[ -z "$new_labels" ]]; then
        return 2  # No labels to add
    fi

    if [[ "$DRY_RUN" == true ]]; then
        warn "[DRY RUN] Would add labels to $issue_key: $new_labels"
        return 0
    fi

    # Get current labels from the issue
    local current_labels=$(jira issue view "$issue_key" --plain 2>/dev/null | \
                          grep "^Labels:" | \
                          sed 's/^Labels:[[:space:]]*//' | \
                          tr ',' '\n' | xargs)

    # Build label arguments for labels that don't already exist
    local -a label_args=()
    IFS=',' read -ra NEW_LABELS <<< "$new_labels"
    for new_label in "${NEW_LABELS[@]}"; do
        new_label=$(echo "$new_label" | xargs)
        if [[ -n "$new_label" ]] && ! echo "$current_labels" | grep -qw "$new_label"; then
            label_args+=("--label" "$new_label")
        fi
    done

    # Add new labels if any
    if [[ ${#label_args[@]} -gt 0 ]]; then
        if jira issue edit "$issue_key" "${label_args[@]}" --no-input < /dev/null > /dev/null 2>&1; then
            return 0
        else
            return 1
        fi
    fi

    return 2  # No new labels to add
}

# Transition a JIRA issue to a new status
# Args: issue_key, target_status
# Returns: 0 on success, 1 on failure
jira_transition_issue() {
    local issue_key="$1"
    local target_status="$2"

    if [[ "$DRY_RUN" == true ]]; then
        warn "[DRY RUN] Would transition issue $issue_key to $target_status"
        return 0
    fi

    if jira issue move "$issue_key" "$target_status" < /dev/null > /dev/null 2>&1; then
        return 0
    else
        echo -e "${RED}✗${NC} Failed to transition issue $issue_key to $target_status" >&2
        return 1
    fi
}

# Search for existing JIRA issues
# Args: jql_query
# Returns: List of issue keys (one per line)
jira_search_issues() {
    local jql="$1"

    debug_echo "${BLUE}JQL Query: $jql${NC}"

    jira issue list --jql "$jql" --plain --no-headers --columns KEY 2>/dev/null || echo ""
}

# ==============================================================================
# DATA MODEL FUNCTIONS
# ==============================================================================

# Compliance record structure (passed as a single string)
# Format: component_name,scan_time,promoted_time,promotion_status,hermetic_status,ec_status,multiarch_status,push_status,push_url,ec_url

# Parse a compliance record from CSV line
# Args: CSV line
# Outputs: Sets variables in caller's scope via read
parse_compliance_record() {
    local csv_line="$1"
    # This function is used with 'read' to parse the CSV line
    echo "$csv_line"
}

# Validate CSV line format
# Args: line, line_number
# Returns: 0 if valid, 1 if invalid
validate_csv_line() {
    local line="$1"
    local line_number="$2"

    # Skip empty lines
    if [[ -z "$line" ]]; then
        return 0
    fi

    # Count fields
    local field_count=$(echo "$line" | awk -F',' '{print NF}')

    if [[ "$field_count" -lt "$MIN_CSV_FIELDS" ]]; then
        echo -e "${RED}ERROR:${NC} Invalid CSV format at line $line_number" >&2
        echo -e "${RED}Expected at least $MIN_CSV_FIELDS fields, got $field_count${NC}" >&2
        echo -e "${YELLOW}Line:${NC} $line" >&2
        return 1
    fi

    return 0
}

# ==============================================================================
# COMPLIANCE CHECKING FUNCTIONS
# ==============================================================================

# Check if image build time is stale (>2 weeks)
# Args: promoted_time
# Returns: 0 if stale, 1 if not stale
is_image_stale() {
    local promoted_time="$1"

    # Check if promoted_time is a valid timestamp
    if [[ "$promoted_time" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2} ]]; then
        # Convert promoted_time to epoch seconds (handle both Z suffix and no suffix)
        local promoted_time_clean="${promoted_time%Z}"
        local promoted_epoch=$(date -j -f "%Y-%m-%dT%H:%M:%S" "$promoted_time_clean" "+%s" 2>/dev/null)

        if [[ -n "$promoted_epoch" ]]; then
            local current_epoch=$(date +%s)
            local age_seconds=$((current_epoch - promoted_epoch))

            if [[ $age_seconds -gt $IMAGE_STALE_THRESHOLD ]]; then
                return 0  # true - is stale
            fi
        fi
    fi

    return 1  # false - not stale
}

# Check if a component is non-compliant
# Args: promotion_status, hermetic_status, ec_status, multiarch_status, push_status, promoted_time
# Returns: 0 if non-compliant, 1 if compliant
is_non_compliant() {
    local promotion_status="$1"
    local hermetic_status="$2"
    local ec_status="$3"
    local multiarch_status="$4"
    local push_status="$5"
    local promoted_time="$6"

    # Check for promotion failures
    if [[ "$promotion_status" =~ ($STATUS_FAILED|$STATUS_IMAGE_PULL_FAILURE|$STATUS_INSPECTION_FAILURE|$STATUS_DIGEST_FAILURE) ]]; then
        return 0  # true - is non-compliant
    fi

    # Check if successful promotion but image is stale (>2 weeks)
    if [[ "$promotion_status" == "$STATUS_SUCCESSFUL" ]] && is_image_stale "$promoted_time"; then
        return 0  # true - is non-compliant (stale image)
    fi

    # Check for other failure conditions
    if [[ "$hermetic_status" == "$STATUS_NOT_ENABLED" ]] || \
       [[ "$ec_status" =~ ($STATUS_NOT_COMPLIANT|$STATUS_PUSH_FAILURE) ]] || \
       [[ "$multiarch_status" == "$STATUS_NOT_ENABLED" ]] || \
       [[ "$push_status" == "$STATUS_FAILED" ]]; then
        return 0  # true - is non-compliant
    fi

    return 1  # false - is compliant
}

# Format promotion status with timestamp and staleness check
# Args: promotion_status, promoted_time
# Returns: Formatted status string
format_promotion_status() {
    local promotion_status="$1"
    local promoted_time="$2"

    # If promotion was successful, check if image is stale
    if [[ "$promotion_status" == "$STATUS_SUCCESSFUL" ]]; then
        if is_image_stale "$promoted_time"; then
            echo "Stale($promoted_time)"
        else
            echo "Successful($promoted_time)"
        fi
        return
    fi

    # For all other statuses, return as-is
    echo "$promotion_status"
}

# Determine compliance-specific labels based on failure types
# Args: promotion_status, promoted_time, hermetic_status, ec_status, multiarch_status, push_status
# Returns: Comma-separated label string
get_compliance_labels() {
    local promotion_status="$1"
    local promoted_time="$2"
    local hermetic_status="$3"
    local ec_status="$4"
    local multiarch_status="$5"
    local push_status="$6"

    local specific_labels=""

    # Image promotion failures or stale images
    if [[ "$promotion_status" =~ ($STATUS_FAILED|$STATUS_IMAGE_PULL_FAILURE|$STATUS_INSPECTION_FAILURE|$STATUS_DIGEST_FAILURE) ]]; then
        specific_labels+="image-promotion-failure,"
    elif [[ "$promotion_status" == "$STATUS_SUCCESSFUL" ]] && is_image_stale "$promoted_time"; then
        specific_labels+="image-stale-failure,"
    fi

    # Hermetic builds
    if [[ "$hermetic_status" == "$STATUS_NOT_ENABLED" ]]; then
        specific_labels+="hermetic-builds-failure,"
    fi

    # Enterprise Contract
    if [[ "$ec_status" == "$STATUS_NOT_COMPLIANT" ]]; then
        specific_labels+="enterprise-contract-failure,"
    fi

    # Push failures
    if [[ "$ec_status" == "$STATUS_PUSH_FAILURE" ]] || [[ "$push_status" == "$STATUS_FAILED" ]]; then
        specific_labels+="push-failure,"
    fi

    # Multiarch support
    if [[ "$multiarch_status" == "$STATUS_NOT_ENABLED" ]]; then
        specific_labels+="multiarch-support-failure,"
    fi

    # Remove trailing comma
    specific_labels="${specific_labels%,}"

    echo "$specific_labels"
}

# ==============================================================================
# COMPONENT MAPPING FUNCTIONS
# ==============================================================================

# Get all JIRA component names for a component (handles multi-squad components)
# Args: component_name
# Returns: JIRA component names (one per line)
get_component_squads() {
    local component_name="$1"
    local config_file="$SCRIPT_DIR/component-squad.yaml"

    if [[ ! -f "$config_file" ]]; then
        echo ""
        return
    fi

    # Strip version suffix (e.g., -210, -215, -27, -29) from component name
    local base_component_name=$(echo "$component_name" | sed 's/-[0-9][0-9]*$//')

    # Search through all squads to find which ones contain this component
    local jira_components=$(yq ".squads | to_entries | .[] | select(.value.components[] == \"$component_name\") | .value[\"jira-component\"]" "$config_file" 2>/dev/null)

    if [[ -z "$jira_components" && "$base_component_name" != "$component_name" ]]; then
        jira_components=$(yq ".squads | to_entries | .[] | select(.value.components[] == \"$base_component_name\") | .value[\"jira-component\"]" "$config_file" 2>/dev/null)
    fi

    # Filter out empty/null values
    echo "$jira_components" | grep -v '^$' | grep -v '^null$'
}

# ==============================================================================
# ISSUE DESCRIPTION BUILDERS
# ==============================================================================

# Build compliance status table (common for all JIRA issue operations)
# Args: promotion_status, promoted_time, hermetic_status, ec_status, multiarch_status, push_status
# Returns: JIRA-formatted table
build_compliance_status_table() {
    local promotion_status="$1"
    local promoted_time="$2"
    local hermetic_status="$3"
    local ec_status="$4"
    local multiarch_status="$5"
    local push_status="$6"

    local formatted_promotion_status=$(format_promotion_status "$promotion_status" "$promoted_time")

    local table="||Check||Status||
|Image Promotion|$formatted_promotion_status|
|Hermetic Builds|$hermetic_status|
|Enterprise Contract|$ec_status|
|Multiarch Support|$multiarch_status|
|Push Pipeline|$push_status|"

    echo "$table"
}

# Build action items based on compliance failures
# Args: promotion_status, promoted_time, hermetic_status, ec_status, multiarch_status, push_status
# Returns: JIRA-formatted action items
build_action_items() {
    local promotion_status="$1"
    local promoted_time="$2"
    local hermetic_status="$3"
    local ec_status="$4"
    local multiarch_status="$5"
    local push_status="$6"

    local actions=""

    # Promotion failures or stale images
    if [[ "$promotion_status" =~ ($STATUS_FAILED|$STATUS_IMAGE_PULL_FAILURE|$STATUS_INSPECTION_FAILURE|$STATUS_DIGEST_FAILURE) ]]; then
        actions+="* Fix image promotion issues - component has no valid promoted image
"
    elif [[ "$promotion_status" == "$STATUS_SUCCESSFUL" ]] && is_image_stale "$promoted_time"; then
        actions+="* Rebuild component - image is over 2 weeks old and needs to be updated
"
    fi

    # Hermetic builds
    if [[ "$hermetic_status" == "$STATUS_NOT_ENABLED" ]]; then
        actions+="* Enable hermetic builds:
** Set \`hermetic: true\` in .tekton pipeline YAML
** Set \`build-source-image: true\` in .tekton pipeline YAML
** Add \`prefetch-input\` configuration or vendor dependencies
"
    fi

    # Enterprise Contract
    if [[ "$ec_status" == "$STATUS_NOT_COMPLIANT" ]]; then
        actions+="* Fix Enterprise Contract violations - check Konflux pipeline logs
"
    fi

    if [[ "$ec_status" == "$STATUS_PUSH_FAILURE" ]]; then
        actions+="* Fix pipeline push failures - component build is failing
"
    fi

    # Multiarch support
    if [[ "$multiarch_status" == "$STATUS_NOT_ENABLED" ]]; then
        actions+="* Enable multiarch support:
** Add \`build-platforms\` parameter with 4 platforms: [linux/amd64, linux/arm64, linux/ppc64le, linux/s390x]
"
    fi

    # Push pipeline
    if [[ "$push_status" == "$STATUS_FAILED" ]]; then
        actions+="* Fix push pipeline failures - check the build pipeline run logs for errors
"
    fi

    echo "$actions"
}

# Add pipeline run links to description
# Args: push_pipelinerun_url, ec_pipelinerun_url
# Returns: JIRA-formatted links section
build_pipeline_links() {
    local push_pipelinerun_url="$1"
    local ec_pipelinerun_url="$2"

    local links=""

    # Check if any links are available
    if [[ -n "$push_pipelinerun_url" && "$push_pipelinerun_url" != "N/A" && "$push_pipelinerun_url" != "null" ]] || \
       [[ -n "$ec_pipelinerun_url" && "$ec_pipelinerun_url" != "N/A" && "$ec_pipelinerun_url" != "null" ]]; then
        links="
h3. Pipeline Run Links
"

        if [[ -n "$push_pipelinerun_url" && "$push_pipelinerun_url" != "N/A" && "$push_pipelinerun_url" != "null" ]]; then
            links+="
* [Build Pipeline Run|$push_pipelinerun_url]"
        fi

        if [[ -n "$ec_pipelinerun_url" && "$ec_pipelinerun_url" != "N/A" && "$ec_pipelinerun_url" != "null" ]]; then
            links+="
* [Enterprise Contract Pipeline Run|$ec_pipelinerun_url]"
        fi
    fi

    echo "$links"
}

# Build full issue description for creating new JIRA issue
# Args: component_name, scan_time, promoted_time, promotion_status, hermetic_status,
#       ec_status, multiarch_status, push_status, push_url, ec_url
# Returns: Full JIRA-formatted description
build_issue_description() {
    local component_name="$1"
    local scan_time="$2"
    local promoted_time="$3"
    local promotion_status="$4"
    local hermetic_status="$5"
    local ec_status="$6"
    local multiarch_status="$7"
    local push_status="$8"
    local push_pipelinerun_url="$9"
    local ec_pipelinerun_url="${10}"

    local compliance_table=$(build_compliance_status_table "$promotion_status" "$promoted_time" "$hermetic_status" "$ec_status" "$multiarch_status" "$push_status")
    local action_items=$(build_action_items "$promotion_status" "$promoted_time" "$hermetic_status" "$ec_status" "$multiarch_status" "$push_status")
    local pipeline_links=$(build_pipeline_links "$push_pipelinerun_url" "$ec_pipelinerun_url")

    local description="h2. Component Compliance Failure

*Component:* \`$component_name\`
*Application:* \`$APP_NAME\`
*Scan Time:* $scan_time
*Image Build Time:* $promoted_time

h3. Compliance Status

$compliance_table

h3. Required Actions

$action_items$pipeline_links"

    echo "$description"
}

# Build update comment for existing JIRA issue
# Args: component_name, scan_time, promoted_time, promotion_status, hermetic_status,
#       ec_status, multiarch_status, push_status, push_url, ec_url
# Returns: Full JIRA-formatted comment
build_update_comment() {
    local component_name="$1"
    local scan_time="$2"
    local promoted_time="$3"
    local promotion_status="$4"
    local hermetic_status="$5"
    local ec_status="$6"
    local multiarch_status="$7"
    local push_status="$8"
    local push_pipelinerun_url="$9"
    local ec_pipelinerun_url="${10}"

    local compliance_table=$(build_compliance_status_table "$promotion_status" "$promoted_time" "$hermetic_status" "$ec_status" "$multiarch_status" "$push_status")
    local action_items=$(build_action_items "$promotion_status" "$promoted_time" "$hermetic_status" "$ec_status" "$multiarch_status" "$push_status")
    local pipeline_links=$(build_pipeline_links "$push_pipelinerun_url" "$ec_pipelinerun_url")

    local comment="h2. Updated Compliance Scan Results

Component \`$component_name\` remains non-compliant. Latest scan results below.

h3. Current Compliance Status

$compliance_table

*Scan Time:* $scan_time
*Image Build Time:* $promoted_time

h3. Required Actions

$action_items$pipeline_links"

    echo "$comment"
}

# Build resolution comment for closing JIRA issue
# Args: component_name, scan_time, promoted_time, promotion_status, hermetic_status,
#       ec_status, multiarch_status, push_status, push_url, ec_url
# Returns: Full JIRA-formatted comment
build_resolution_comment() {
    local component_name="$1"
    local scan_time="$2"
    local promoted_time="$3"
    local promotion_status="$4"
    local hermetic_status="$5"
    local ec_status="$6"
    local multiarch_status="$7"
    local push_status="$8"
    local push_pipelinerun_url="$9"
    local ec_pipelinerun_url="${10}"

    local compliance_table=$(build_compliance_status_table "$promotion_status" "$promoted_time" "$hermetic_status" "$ec_status" "$multiarch_status" "$push_status")
    local pipeline_links=$(build_pipeline_links "$push_pipelinerun_url" "$ec_pipelinerun_url")

    local comment="Component \`$component_name\` is now compliant based on the latest compliance scan.

h3. Compliance Status (Latest Scan)

$compliance_table

*Scan Time:* $scan_time
*Image Build Time:* $promoted_time

All compliance checks are now passing. Auto-closing this issue.$pipeline_links"

    echo "$comment"
}

# ==============================================================================
# JIRA ISSUE OPERATIONS
# ==============================================================================

# Build JIRA command arguments for issue creation
# Args: summary, desc_file, all_labels, squad_names
# Sets: Global jira_cmd_args array
build_jira_create_command() {
    local summary="$1"
    local desc_file="$2"
    local all_labels="$3"
    local squad_names="$4"

    jira_cmd_args=(
        "issue" "create"
        "--project" "$JIRA_PROJECT"
        "--type" "$ISSUE_TYPE"
        "--priority" "$PRIORITY"
        "--summary" "$summary"
        "--template" "$desc_file"
        "--custom" "activity-type=$JIRA_ACTIVITY_TYPE"
        "--custom" "severity=$JIRA_SEVERITY"
        "--no-input"
    )

    # Add Affects Version/s if available
    if [[ -n "$AFFECTS_VERSION" ]]; then
        jira_cmd_args+=("--affects-version" "$AFFECTS_VERSION")
    fi

    # Add labels
    if [[ -n "$all_labels" ]]; then
        IFS=',' read -ra LABEL_ARRAY <<< "$all_labels"
        for label in "${LABEL_ARRAY[@]}"; do
            label=$(echo "$label" | xargs)
            if [[ -n "$label" ]]; then
                jira_cmd_args+=("--label" "$label")
            fi
        done
    fi

    # Add component(s)
    if [[ -n "$COMPONENT" ]]; then
        jira_cmd_args+=("--component" "$COMPONENT")
    elif [[ -n "$squad_names" ]]; then
        while IFS= read -r squad_name; do
            if [[ -n "$squad_name" ]]; then
                jira_cmd_args+=("--component" "$squad_name")
            fi
        done <<< "$squad_names"
    fi
}

# Display dry-run information for issue creation
# Args: summary, all_labels, desc_file
display_dry_run_create_info() {
    local summary="$1"
    local all_labels="$2"
    local desc_file="$3"

    warn "[DRY RUN] Would create issue:"
    info "Summary: $summary"
    info "Project: $JIRA_PROJECT"
    info "Type: $ISSUE_TYPE"
    info "Priority: $PRIORITY"
    info "Labels: $all_labels"

    if [[ -n "$AFFECTS_VERSION" ]]; then
        info "Affects Version/s: $AFFECTS_VERSION"
    fi

    # Show component(s) if any
    local components_list=""
    for arg_idx in "${!jira_cmd_args[@]}"; do
        if [[ "${jira_cmd_args[$arg_idx]}" == "--component" ]]; then
            local next_idx=$((arg_idx + 1))
            if [[ -n "$components_list" ]]; then
                components_list+=", "
            fi
            components_list+="${jira_cmd_args[$next_idx]}"
        fi
    done
    if [[ -n "$components_list" ]]; then
        info "Component(s): $components_list"
    fi

    # If debug is enabled, show the full command and description
    if [[ "$DEBUG" == true ]]; then
        echo "" >&2
        info "Command:"
        echo -n "jira" >&2
        for arg in "${jira_cmd_args[@]}"; do
            if [[ "$arg" =~ [[:space:]] ]]; then
                echo -n " \"$arg\"" >&2
            else
                echo -n " $arg" >&2
            fi
        done
        echo "" >&2
        echo "" >&2
        info "Description content:"
        cat "$desc_file" >&2
    fi
    echo "" >&2
}

# Create a new JIRA issue
# Args: component_name, scan_time, promoted_time, promotion_status, hermetic_status,
#       ec_status, multiarch_status, push_status, push_url, ec_url
# Returns: 0 on success, 1 on failure
# Outputs: Issue key to stdout
create_jira_issue() {
    local component_name="$1"
    local scan_time="$2"
    local promoted_time="$3"
    local promotion_status="$4"
    local hermetic_status="$5"
    local ec_status="$6"
    local multiarch_status="$7"
    local push_status="$8"
    local push_pipelinerun_url="$9"
    local ec_pipelinerun_url="${10}"

    # Check for duplicates if requested
    if [[ "$SKIP_DUPLICATES" == true ]]; then
        local jql="project=$JIRA_PROJECT AND summary~\"$component_name\" AND labels=konflux AND labels=compliance AND labels=auto-created AND status NOT IN (Closed,Done,Resolved)"
        local existing_issues=$(jira_search_issues "$jql")

        if [[ -n "$existing_issues" ]]; then
            local existing_key=$(echo "$existing_issues" | head -n 1 | awk '{print $1}' | xargs)
            warn "⊘ Found existing issue $existing_key for $component_name - adding update comment"

            if update_existing_issue "$existing_key" "$component_name" "$scan_time" "$promoted_time" "$promotion_status" "$hermetic_status" "$ec_status" "$multiarch_status" "$push_status" "$push_pipelinerun_url" "$ec_pipelinerun_url"; then
                echo "UPDATED:$existing_key"
                return 0
            else
                echo "FAILED_UPDATE:$existing_key"
                return 1
            fi
        fi
    fi

    # Build issue components
    local description=$(build_issue_description "$component_name" "$scan_time" "$promoted_time" "$promotion_status" "$hermetic_status" "$ec_status" "$multiarch_status" "$push_status" "$push_pipelinerun_url" "$ec_pipelinerun_url")
    local summary="[$APP_NAME] $component_name - Konflux compliance failure"

    local compliance_specific_labels=$(get_compliance_labels "$promotion_status" "$promoted_time" "$hermetic_status" "$ec_status" "$multiarch_status" "$push_status")
    local all_labels="$LABELS"
    if [[ -n "$compliance_specific_labels" ]]; then
        all_labels="$all_labels,$compliance_specific_labels"
    fi

    local squad_names=$(get_component_squads "$component_name")

    # Prepare description file
    local desc_file=$(mktemp)
    echo "$description" > "$desc_file"

    # Build JIRA command
    build_jira_create_command "$summary" "$desc_file" "$all_labels" "$squad_names"

    # Handle dry-run mode
    if [[ "$DRY_RUN" == true ]]; then
        display_dry_run_create_info "$summary" "$all_labels" "$desc_file"
        rm -f "$desc_file"
        echo "DRY-RUN-ISSUE"
        return 0
    fi

    # Execute issue creation
    if [[ "$DEBUG" == true ]]; then
        debug_echo "${BLUE}Executing JIRA create command${NC}"
        debug_echo "Description:"
        debug_echo "$(cat "$desc_file")"
    fi

    local output
    output=$(jira "${jira_cmd_args[@]}" < /dev/null 2>&1)
    local exit_code=$?

    rm -f "$desc_file"

    # Extract issue key from output
    local issue_key=$(echo "$output" | grep -oE '[A-Z]+-[0-9]+' | head -n 1)

    if [[ $exit_code -eq 0 && -n "$issue_key" ]]; then
        local jira_url=$(get_jira_server_url)
        success "Created issue $issue_key for $component_name: $jira_url/browse/$issue_key"
        echo "$issue_key"
        return 0
    else
        echo -e "${RED}✗${NC} Failed to create issue for $component_name: $output" >&2
        return 1
    fi
}

# Update an existing JIRA issue with latest scan results
# Args: issue_key, component_name, scan_time, promoted_time, promotion_status, hermetic_status,
#       ec_status, multiarch_status, push_status, push_url, ec_url
# Returns: 0 on success, 1 on failure
update_existing_issue() {
    local issue_key="$1"
    local component_name="$2"
    local scan_time="$3"
    local promoted_time="$4"
    local promotion_status="$5"
    local hermetic_status="$6"
    local ec_status="$7"
    local multiarch_status="$8"
    local push_status="$9"
    local push_pipelinerun_url="${10}"
    local ec_pipelinerun_url="${11}"

    # Build update comment
    local comment=$(build_update_comment "$component_name" "$scan_time" "$promoted_time" "$promotion_status" "$hermetic_status" "$ec_status" "$multiarch_status" "$push_status" "$push_pipelinerun_url" "$ec_pipelinerun_url")

    # Add comment to issue
    if ! jira_add_comment "$issue_key" "$comment"; then
        return 1
    fi
    # return 0
    # Add compliance-specific labels if any
    local compliance_specific_labels=$(get_compliance_labels "$promotion_status" "$promoted_time" "$hermetic_status" "$ec_status" "$multiarch_status" "$push_status")

    if [[ -n "$compliance_specific_labels" ]]; then
        local label_result
        jira_add_labels "$issue_key" "$compliance_specific_labels"
        label_result=$?

        if [[ $label_result -eq 0 ]]; then
            success "Updated issue $issue_key with latest scan results and added new labels"
        elif [[ $label_result -eq 2 ]]; then
            success "Updated issue $issue_key with latest scan results"
        else
            warn "⚠ Updated issue $issue_key but failed to add labels"
        fi
    else
        success "Updated issue $issue_key with latest scan results"
    fi

    return 0
}

# Close a JIRA issue with resolution comment
# Args: issue_key, component_name, scan_time, promoted_time, promotion_status, hermetic_status,
#       ec_status, multiarch_status, push_status, push_url, ec_url
# Returns: 0 on success, 1 on failure
close_jira_issue() {
    local issue_key="$1"
    local component_name="$2"
    local scan_time="$3"
    local promoted_time="$4"
    local promotion_status="$5"
    local hermetic_status="$6"
    local ec_status="$7"
    local multiarch_status="$8"
    local push_status="$9"
    local push_pipelinerun_url="${10}"
    local ec_pipelinerun_url="${11}"

    # Build resolution comment
    local comment=$(build_resolution_comment "$component_name" "$scan_time" "$promoted_time" "$promotion_status" "$hermetic_status" "$ec_status" "$multiarch_status" "$push_status" "$push_pipelinerun_url" "$ec_pipelinerun_url")

    # Add comment to issue
    if ! jira_add_comment "$issue_key" "$comment"; then
        return 1
    fi

    # Add "auto-closed" label before closing
    if [[ "$DRY_RUN" != true ]]; then
        if jira_add_labels "$issue_key" "auto-closed" >/dev/null 2>&1; then
            debug_echo "Added 'auto-closed' label to $issue_key"
        else
            warn "⚠ Failed to add 'auto-closed' label to $issue_key (continuing with close)"
        fi
    fi

    # Close the issue
    if jira_transition_issue "$issue_key" "Closed"; then
        success "Closed issue $issue_key for component $component_name"
        return 0
    else
        return 1
    fi
}

# ==============================================================================
# AUTO-CLOSE FUNCTIONALITY
# ==============================================================================

# Extract component name from JIRA summary
# Args: summary
# Returns: Component name
extract_component_from_summary() {
    local summary="$1"
    # Extract component name between "] " and " - Konflux"
    echo "$summary" | sed -n 's/.*\] \(.*\) - Konflux.*/\1/p'
}

# Auto-close resolved issues
# Args: project, labels
# Returns: 0 on success
# Sets: AUTO_CLOSED_ISSUES array with closed issue info
auto_close_resolved_issues() {
    local project="$1"
    local labels="$2"

    # Build JQL query
    local label_filters=""
    IFS=',' read -ra LABEL_ARRAY <<< "$labels"
    for label in "${LABEL_ARRAY[@]}"; do
        label=$(echo "$label" | xargs)
        if [[ -n "$label_filters" ]]; then
            label_filters+=" AND "
        fi
        label_filters+="labels=$label"
    done

    local jql="project=$project AND $label_filters AND status NOT IN (Closed,Done,Resolved)"

    # Query JIRA for open issues
    local open_issues=$(jira issue list --jql "$jql" --plain --no-headers --columns KEY,SUMMARY 2>/dev/null || echo "")

    if [[ -z "$open_issues" ]]; then
        info "No open issues found to auto-close"
        return 0
    fi

    local closed_count=0
    local skipped_count=0
    local failed_count=0

    # Array to track closed issues
    declare -g -a AUTO_CLOSED_ISSUES=()

    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    info "Auto-closing resolved issues"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

    while IFS=$'\t' read -r issue_key summary; do
        local component_name=$(extract_component_from_summary "$summary")

        if [[ -z "$component_name" ]]; then
            warn "⊘ Skipping $issue_key - could not extract component name from summary"
            skipped_count=$((skipped_count + 1))
            continue
        fi

        debug_echo "${BLUE}Checking $issue_key: $component_name${NC}"

        # Check if component exists in COMPLIANCE_STATUS map
        if [[ ! -v COMPLIANCE_STATUS["$component_name"] ]]; then
            warn "⊘ Skipping $issue_key - component $component_name not found in compliance CSV"
            skipped_count=$((skipped_count + 1))
            continue
        fi

        # Check if component is now compliant
        if [[ "${COMPLIANCE_STATUS[$component_name]}" == "compliant" ]]; then
            info "Processing: $component_name ($issue_key)"

            # Parse compliance details
            IFS=',' read -r scan_time promoted_time promotion_status hermetic_status ec_status multiarch_status push_status push_pipelinerun_url ec_pipelinerun_url <<< "${COMPLIANCE_DETAILS[$component_name]}"

            if close_jira_issue "$issue_key" "$component_name" "$scan_time" "$promoted_time" "$promotion_status" "$hermetic_status" "$ec_status" "$multiarch_status" "$push_status" "$push_pipelinerun_url" "$ec_pipelinerun_url"; then
                closed_count=$((closed_count + 1))
                AUTO_CLOSED_ISSUES+=("$component_name:$issue_key")
            else
                failed_count=$((failed_count + 1))
            fi
        else
            debug_echo "${YELLOW}⊘${NC} Skipping $issue_key - component $component_name is still non-compliant"
            skipped_count=$((skipped_count + 1))
        fi

    done <<< "$open_issues"

    # Print summary
    echo ""
    info "Auto-close Summary:"
    echo -e "${GREEN}Issues closed:${NC} $closed_count" >&2
    echo -e "${YELLOW}Issues skipped:${NC} $skipped_count" >&2
    echo -e "${RED}Failed:${NC} $failed_count" >&2
    echo ""
}

# ==============================================================================
# INITIALIZATION AND SETUP
# ==============================================================================

# Load environment variables from .env file if it exists
load_environment() {
    if [[ -f "$SCRIPT_DIR/.env" ]]; then
        set -a
        source "$SCRIPT_DIR/.env"
        set +a
    fi
}

# Derive JIRA "Affects Version/s" from APP_NAME
# Format: acm-215 -> "ACM 2.15.0", mce-29 -> "MCE 2.9.0"
get_affects_version() {
    local app_name="$1"

    local product=$(echo "$app_name" | cut -d'-' -f1 | tr '[:lower:]' '[:upper:]')
    local version_num=$(echo "$app_name" | cut -d'-' -f2)

    if [[ ${#version_num} -eq 3 ]]; then
        local major="${version_num:0:1}"
        local minor="${version_num:1:2}"
        echo "${product} ${major}.${minor}.0"
    elif [[ ${#version_num} -eq 2 ]]; then
        local major="${version_num:0:1}"
        local minor="${version_num:1:1}"
        echo "${product} ${major}.${minor}.0"
    else
        echo ""
    fi
}

# Check and initialize JIRA CLI configuration
check_jira_cli() {
    # Check if jira-cli is installed
    if ! command -v jira &> /dev/null; then
        die "jira-cli is required but not installed

Install jira-cli from: https://github.com/ankitpokhrel/jira-cli

macOS (Homebrew):
  brew tap ankitpokhrel/jira-cli
  brew install jira-cli

Linux:
  Download from: https://github.com/ankitpokhrel/jira-cli/releases
  Or use Go: go install github.com/ankitpokhrel/jira-cli/cmd/jira@latest

After installation, the script will configure jira-cli automatically
when you run it with the required environment variables set."
    fi

    # Check if jira-cli is configured
    JIRA_CONFIG_FILE="${JIRA_CONFIG_FILE:-$HOME/.config/.jira/.config.yml}"
    if [[ ! -f "$JIRA_CONFIG_FILE" ]]; then
        warn "JIRA CLI is not configured. Initializing..."

        if [[ -z "$JIRA_API_TOKEN" ]]; then
            die "JIRA_API_TOKEN environment variable is required

Please set the following environment variables:
  export JIRA_API_TOKEN=\"your-personal-access-token\"
  export JIRA_AUTH_TYPE=\"bearer\"

Or run 'jira init' manually to configure interactively."
        fi

        # Set defaults for jira init
        JIRA_SERVER="${JIRA_SERVER:-$DEFAULT_JIRA_SERVER}"
        JIRA_INSTALLATION="${JIRA_INSTALLATION:-Local}"
        JIRA_LOGIN="${JIRA_LOGIN:-${JIRA_USER:-}}"
        JIRA_AUTH_TYPE="${JIRA_AUTH_TYPE:-bearer}"
        JIRA_BOARD="${JIRA_BOARD:-None}"

        info "Initializing jira-cli with:"
        echo "  Server: $JIRA_SERVER" >&2
        echo "  Installation: $JIRA_INSTALLATION" >&2
        echo "  Auth Type: $JIRA_AUTH_TYPE" >&2
        echo "  Project: $JIRA_PROJECT" >&2
        echo "  Board: $JIRA_BOARD" >&2
        echo "" >&2

        if jira init \
            --installation "$JIRA_INSTALLATION" \
            --server "$JIRA_SERVER" \
            --login "$JIRA_LOGIN" \
            --auth-type "$JIRA_AUTH_TYPE" \
            --project "$JIRA_PROJECT" \
            --board "$JIRA_BOARD" \
            --force; then
            success "JIRA CLI initialized successfully"
        else
            die "Failed to initialize JIRA CLI

You can try running 'jira init' manually for interactive setup."
        fi
        echo "" >&2
    fi
}

# Check required dependencies
check_dependencies() {
    if ! command -v jq &> /dev/null; then
        die "jq is required but not installed
Install with: brew install jq (macOS) or apt-get install jq (Linux)"
    fi
}

# ==============================================================================
# HELP AND USAGE
# ==============================================================================

show_help() {
    cat << EOF
Usage: create-compliance-jira-issues.sh [OPTIONS] <compliance-csv-file>

Create JIRA issues for non-compliant components from compliance.sh output

ARGUMENTS:
    <compliance-csv-file>    Path to the compliance CSV file (e.g., data/acm-215-compliance.csv)

OPTIONS:
    --project PROJECT        JIRA project key (default: from JIRA_PROJECT env var or "ACM")
    --issue-type TYPE        JIRA issue type (default: "Bug")
    --priority PRIORITY      JIRA priority (default: "Critical")
    --component COMPONENT    JIRA component field (optional, overrides auto-detection from component-squad.yaml)
    --labels LABELS          Comma-separated labels (default: "konflux,compliance,auto-created")
    --dry-run                Show what would be created without actually creating issues
    --skip-duplicates        Skip creating issues if similar ones already exist
    --auto-close             Auto-close existing issues for components that are now compliant
    --output-json FILE       Save created issues to JSON file
    --debug                  Enable debug output (shows jira-cli command in dry-run mode)
    -h, --help               Show this help message

NOTE:
    The script automatically sets the JIRA Component/s field based on the squad mapping
    in component-squad.yaml. Each component is mapped to its jira-component value (e.g., "Server Foundation",
    "Installer", "GRC", "HyperShift", etc.). You can override this by using the --component option.

ENVIRONMENT VARIABLES:
    Required (for automatic jira-cli initialization):
        JIRA_USER            Your JIRA username/email (e.g., user@redhat.com)
        JIRA_API_TOKEN       Your JIRA Personal Access Token
        JIRA_AUTH_TYPE       Authentication type (set to "bearer" for PAT)

    Optional:
        JIRA_PROJECT         JIRA project key (default: "ACM")
        JIRA_SERVER          JIRA server URL (default: "https://issues.redhat.com")
        JIRA_INSTALLATION    Installation type: "Cloud" or "Local" (default: "Local")

PREREQUISITES:
    This script requires jira-cli (https://github.com/ankitpokhrel/jira-cli)

    Installation:
    # macOS (Homebrew)
    brew tap ankitpokhrel/jira-cli
    brew install jira-cli

    # Linux (download binary from releases)
    # Visit https://github.com/ankitpokhrel/jira-cli/releases
    # Or use Go:
    go install github.com/ankitpokhrel/jira-cli/cmd/jira@latest

    Configuration (Automatic):
    The script will automatically configure jira-cli if not already set up.
    Just set the required environment variables in .env file:

    cp .env.template .env
    # Edit .env and fill in:
    #   JIRA_USER, JIRA_API_TOKEN, JIRA_AUTH_TYPE
    source .env

    Configuration (Manual):
    Alternatively, you can run jira-cli configuration manually:
    jira init

EXAMPLES:
    # First time setup - set environment variables
    cp .env.template .env
    # Edit .env file with your credentials
    source .env

    # Create issues with default settings
    ./create-compliance-jira-issues.sh data/acm-215-compliance.csv

    # Dry run to preview what would be created
    ./create-compliance-jira-issues.sh --dry-run data/acm-215-compliance.csv

    # Create issues with custom labels and priority
    ./create-compliance-jira-issues.sh --labels "konflux,compliance,auto-created" --priority "Critical" data/acm-215-compliance.csv

    # Skip duplicates and save output
    ./create-compliance-jira-issues.sh --skip-duplicates --output-json issues.json data/acm-215-compliance.csv

    # Auto-close resolved issues
    ./create-compliance-jira-issues.sh --auto-close data/acm-215-compliance.csv

CSV FORMAT:
    The compliance CSV file should have the following format (from compliance.sh):
    <component-name>,<scan-time>,<promoted-time>,<promotion-status>,<hermetic-status>,<ec-status>,<multiarch-status>,<push-status>,<push-url>,<ec-url>

    Each line represents one component with its compliance data.

EOF
}

# ==============================================================================
# COMMAND LINE PARSING
# ==============================================================================

parse_arguments() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            --project)
                JIRA_PROJECT="$2"
                shift 2
                ;;
            --issue-type)
                ISSUE_TYPE="$2"
                shift 2
                ;;
            --priority)
                PRIORITY="$2"
                shift 2
                ;;
            --component)
                COMPONENT="$2"
                shift 2
                ;;
            --labels)
                LABELS="$2"
                shift 2
                ;;
            --dry-run)
                DRY_RUN=true
                shift
                ;;
            --skip-duplicates)
                SKIP_DUPLICATES=true
                shift
                ;;
            --auto-close)
                AUTO_CLOSE=true
                shift
                ;;
            --output-json)
                OUTPUT_JSON="$2"
                shift 2
                ;;
            --debug)
                DEBUG=true
                shift
                ;;
            -h|--help)
                show_help
                exit 0
                ;;
            -*)
                echo "Unknown option: $1" >&2
                echo "" >&2
                show_help
                exit 1
                ;;
            *)
                if [[ -z "$COMPLIANCE_FILE" ]]; then
                    COMPLIANCE_FILE="$1"
                else
                    die "Multiple compliance files specified"
                fi
                shift
                ;;
        esac
    done

    # Validate required parameters
    if [[ -z "$COMPLIANCE_FILE" ]]; then
        die "Compliance CSV file is required

$(show_help)"
    fi

    if [[ ! -f "$COMPLIANCE_FILE" ]]; then
        die "Compliance file not found: $COMPLIANCE_FILE"
    fi
}

# ==============================================================================
# MAIN PROCESSING LOOP
# ==============================================================================

process_compliance_csv() {
    local created_count=0
    local updated_count=0
    local skipped_count=0
    local failed_count=0
    local total_count=0

    declare -a created_issues
    declare -a updated_issues
    declare -a created_issues_json

    info "Starting to process CSV file: $COMPLIANCE_FILE"
    info "File exists: $(test -f "$COMPLIANCE_FILE" && echo yes || echo no)"
    info "File content (first 3 lines):"
    head -3 "$COMPLIANCE_FILE" >&2
    echo "" >&2

    while IFS=',' read -r component_name scan_time promoted_time promotion_status hermetic_status ec_status multiarch_status push_status push_pipelinerun_url ec_pipelinerun_url; do
        total_count=$((total_count + 1))

        # Read the original line for validation
        IFS= read -r original_line < <(sed -n "${total_count}p" "$COMPLIANCE_FILE")

        # Validate CSV line format
        if ! validate_csv_line "$original_line" "$total_count"; then
            failed_count=$((failed_count + 1))
            continue
        fi

        debug_echo "${BLUE}DEBUG: Read line $total_count: component=$component_name${NC}"

        # Skip empty lines and header
        if [[ -z "$component_name" || "$component_name" == "Konflux Component" ]]; then
            continue
        fi

        # Track compliance status for auto-close feature
        if is_non_compliant "$promotion_status" "$hermetic_status" "$ec_status" "$multiarch_status" "$push_status" "$promoted_time"; then
            COMPLIANCE_STATUS["$component_name"]="non-compliant"
        else
            COMPLIANCE_STATUS["$component_name"]="compliant"
            COMPLIANCE_DETAILS["$component_name"]="$scan_time,$promoted_time,$promotion_status,$hermetic_status,$ec_status,$multiarch_status,$push_status,$push_pipelinerun_url,$ec_pipelinerun_url"
        fi

        # Check if component is non-compliant
        if is_non_compliant "$promotion_status" "$hermetic_status" "$ec_status" "$multiarch_status" "$push_status" "$promoted_time"; then
            info "Processing: $component_name"

            issue_output=$(create_jira_issue "$component_name" "$scan_time" "$promoted_time" "$promotion_status" "$hermetic_status" "$ec_status" "$multiarch_status" "$push_status" "$push_pipelinerun_url" "$ec_pipelinerun_url")
            create_exit_code=$?

            if [[ $create_exit_code -eq 0 ]]; then
                issue_key=$(echo "$issue_output" | tail -n 1 | xargs)

                # Check if this was an update or a new creation
                if [[ "$issue_key" == UPDATED:* ]]; then
                    updated_count=$((updated_count + 1))
                    actual_key="${issue_key#UPDATED:}"
                    updated_issues+=("$component_name:$actual_key")
                    if [[ -n "$OUTPUT_JSON" ]]; then
                        created_issues_json+=("{\"component\": \"$component_name\", \"status\": \"updated\", \"issue_key\": \"$actual_key\"}")
                    fi
                else
                    created_count=$((created_count + 1))
                    created_issues+=("$component_name:$issue_key")
                    if [[ -n "$OUTPUT_JSON" ]]; then
                        created_issues_json+=("{\"component\": \"$component_name\", \"status\": \"created\", \"issue_key\": \"$issue_key\"}")
                    fi
                fi
            else
                failed_count=$((failed_count + 1))
            fi
        else
            success "$component_name is compliant - skipping"
            skipped_count=$((skipped_count + 1))
        fi

    done < <(cat "$COMPLIANCE_FILE")

    # Auto-close resolved issues if requested
    if [[ "$AUTO_CLOSE" == true ]]; then
        auto_close_resolved_issues "$JIRA_PROJECT" "$LABELS"
    fi

    # Save output JSON if requested
    if [[ -n "$OUTPUT_JSON" && "${created_count}" -gt 0 ]]; then
        printf "[%s]\n" "$(IFS=,; echo "${created_issues_json[*]}")" | jq '.' > "$OUTPUT_JSON"
        success "Saved created issues to $OUTPUT_JSON"
    fi

    # Print summary
    echo ""
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    info "Summary"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo "Total components processed: $total_count" >&2
    echo -e "${GREEN}Compliant (skipped):${NC} $skipped_count" >&2
    echo -e "${GREEN}Issues created:${NC} $created_count" >&2
    echo -e "${YELLOW}Issues updated:${NC} $updated_count" >&2
    echo -e "${RED}Failed:${NC} $failed_count" >&2

    # Print list of created issues with URLs
    if [[ "${created_count}" -gt 0 ]]; then
        echo ""
        info "Created Issues:"
        local jira_url=$(get_jira_server_url)
        for issue_info in "${created_issues[@]}"; do
            local comp_name="${issue_info%%:*}"
            local issue_key="${issue_info##*:}"
            issue_key=$(echo "$issue_key" | xargs)
            echo "  • $comp_name: $jira_url/browse/$issue_key" >&2
        done
    fi

    # Print list of updated issues with URLs
    if [[ "${updated_count}" -gt 0 ]]; then
        echo ""
        info "Updated Issues:"
        local jira_url=$(get_jira_server_url)
        for issue_info in "${updated_issues[@]}"; do
            local comp_name="${issue_info%%:*}"
            local issue_key="${issue_info##*:}"
            issue_key=$(echo "$issue_key" | xargs)
            echo "  • $comp_name: $jira_url/browse/$issue_key" >&2
        done
    fi

    # Print list of auto-closed issues with URLs
    if [[ -n "${AUTO_CLOSED_ISSUES+x}" && "${#AUTO_CLOSED_ISSUES[@]}" -gt 0 ]]; then
        echo ""
        info "Auto-Closed Issues:"
        local jira_url=$(get_jira_server_url)
        for issue_info in "${AUTO_CLOSED_ISSUES[@]}"; do
            local comp_name="${issue_info%%:*}"
            local issue_key="${issue_info##*:}"
            issue_key=$(echo "$issue_key" | xargs)
            echo "  • $comp_name: $jira_url/browse/$issue_key" >&2
        done
    fi

    if [[ "$DRY_RUN" == true ]]; then
        echo ""
        warn "This was a dry run. No issues were actually created."
        echo "Remove --dry-run flag to create issues." >&2
    fi
}

# ==============================================================================
# MAIN ENTRY POINT
# ==============================================================================

main() {
    # Load environment
    load_environment

    # Parse command line arguments
    parse_arguments "$@"

    # Extract application name from filename
    APP_NAME=$(basename "$COMPLIANCE_FILE" | sed 's/-compliance\.csv$//' | grep -oE '(acm|mce)-[0-9]+$' || basename "$COMPLIANCE_FILE" | sed 's/-compliance\.csv$//')

    # Get affects version
    AFFECTS_VERSION=$(get_affects_version "$APP_NAME")

    # Check dependencies
    check_dependencies
    check_jira_cli

    # Print header
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    info "Konflux Compliance JIRA Issue Creator"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    info "Project: $JIRA_PROJECT"
    info "Application: $APP_NAME"
    if [[ -n "$AFFECTS_VERSION" ]]; then
        info "Affects Version: $AFFECTS_VERSION"
    fi
    info "JIRA Auth Type: ${JIRA_AUTH_TYPE:-not set}"
    echo ""

    # Process CSV file
    process_compliance_csv
}

# Run main function
main "$@"
