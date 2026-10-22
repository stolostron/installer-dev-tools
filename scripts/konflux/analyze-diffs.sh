#!/bin/bash

# Script to analyze git diffs from konflux-snapshot-difftool.sh
# Alerts on commits that violate code freeze policies

set -euo pipefail

# Get script directory
SCRIPT_DIR="$(cd "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DIFFS_DIR="${SCRIPT_DIR}/diffs"

# Color codes for output
RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default values
MODE="feature-complete"
VERBOSE=false
SHOW_ALLOWED=false
OUTPUT_FORMAT="text"

# Help function
show_help() {
  local script_name=$(basename "$0")
  cat << EOF
Usage: $script_name [OPTIONS]

Analyze git diffs created by konflux-snapshot-difftool.sh to identify
commits that violate development phase policies.

Options:
  -m, --mode MODE              Development phase mode (default: feature-complete)
                               Valid values:
                                 - feature-complete: Allow bug fixes, reject features
                                 - code-lockdown: Reject all code changes except
                                   dependencies, tests, and build files
  -v, --verbose                Show detailed analysis of each file change
  -a, --show-allowed           Show allowed changes in addition to violations
  -f, --format FORMAT          Output format: text, json, csv (default: text)
  -d, --diffs-dir DIR          Directory containing diff files (default: ./diffs)
  -h, --help                   Show this help message

Examples:
  # Analyze diffs in feature-complete mode
  $script_name --mode feature-complete

  # Analyze diffs in code-lockdown mode with verbose output
  $script_name --mode code-lockdown --verbose

  # Generate JSON report
  $script_name --mode code-lockdown --format json > report.json

  # Show all changes including allowed ones
  $script_name --show-allowed

EOF
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -m|--mode)
            MODE="$2"
            shift 2
            ;;
        -v|--verbose)
            VERBOSE=true
            shift
            ;;
        -a|--show-allowed)
            SHOW_ALLOWED=true
            shift
            ;;
        -f|--format)
            OUTPUT_FORMAT="$2"
            shift 2
            ;;
        -d|--diffs-dir)
            DIFFS_DIR="$2"
            shift 2
            ;;
        -h|--help)
            show_help
            exit 0
            ;;
        *)
            echo "Error: Unknown option: $1"
            echo ""
            show_help
            exit 1
            ;;
    esac
done

# Validate mode
if [[ "$MODE" != "feature-complete" && "$MODE" != "code-lockdown" ]]; then
    echo "Error: Invalid mode '$MODE'"
    echo "Valid modes: feature-complete, code-lockdown"
    exit 1
fi

# Validate diffs directory
if [[ ! -d "$DIFFS_DIR" ]]; then
    echo "Error: Diffs directory not found: $DIFFS_DIR"
    echo "Have you run konflux-snapshot-difftool.sh yet?"
    exit 1
fi

# Check if there are any diff files
shopt -s nullglob
diff_files=("$DIFFS_DIR"/*.diff)
shopt -u nullglob

if [[ ${#diff_files[@]} -eq 0 ]]; then
    echo "Error: No .diff files found in $DIFFS_DIR"
    echo "Have you run konflux-snapshot-difftool.sh yet?"
    exit 1
fi

# Classification functions

# Check if a file path is a dependency management file
is_dependency_file() {
    local file="$1"
    case "$file" in
        package-lock.json|package.json|go.mod|go.sum|Gemfile.lock|Gemfile|\
        requirements.txt|Pipfile.lock|pom.xml|build.gradle|build.gradle.kts|\
        gradle.lockfile|Cargo.lock|Cargo.toml|*.podspec|Podfile.lock|pubspec.lock)
            return 0
            ;;
        */vendor/*)
            return 0
            ;;
        */node_modules/*)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

# Check if a file path is a test file
is_test_file() {
    local file="$1"
    case "$file" in
        *_test.go|*_test.py|*.test.js|*.test.ts|*.spec.js|*.spec.ts|\
        *Test.java|*Tests.java|test_*.py)
            return 0
            ;;
        */test/*|*/tests/*|*/__tests__/*|*/e2e/*|*/integration/*|*/e2e-test/*)
            return 0
            ;;
        .github/workflows/*)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

# Check if a file path is a build/CI file
is_build_file() {
    local file="$1"
    case "$file" in
        Makefile|Dockerfile|Dockerfile.*|*.dockerignore|.gitlab-ci.yml|\
        .travis.yml|Jenkinsfile|*.mk|CMakeLists.txt|meson.build)
            return 0
            ;;
        .github/workflows/*|.github/actions/*|.tekton/*|.konflux/*)
            return 0
            ;;
        build/*|scripts/build/*|ci/*|.ci/*)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

# Check if a file path is documentation
is_doc_file() {
    local file="$1"
    case "$file" in
        *.md|*.rst|*.txt|README*|CHANGELOG*|LICENSE*|CONTRIBUTING*|AUTHORS*)
            return 0
            ;;
        doc/*|docs/*|documentation/*)
            return 0
            ;;
        .vscode/*|.idea/*|*.code-workspace)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

# Analyze a commit message for keywords
analyze_commit_message() {
    local message="$1"
    local lowercase_msg=$(echo "$message" | tr '[:upper:]' '[:lower:]')

    # Feature indicators
    if echo "$lowercase_msg" | grep -qE '\b(feat|feature|add|new|implement|enhancement)\b'; then
        echo "FEATURE"
        return
    fi

    # Bug fix indicators
    if echo "$lowercase_msg" | grep -qE '\b(fix|bug|patch|repair|correct|resolve)\b'; then
        echo "BUGFIX"
        return
    fi

    # Dependency update indicators
    if echo "$lowercase_msg" | grep -qE '\b(dep|dependency|dependencies|update|upgrade|bump|vendor)\b'; then
        echo "DEPENDENCY"
        return
    fi

    # Refactor indicators
    if echo "$lowercase_msg" | grep -qE '\b(refactor|cleanup|clean|reorganize)\b'; then
        echo "REFACTOR"
        return
    fi

    # Test indicators
    if echo "$lowercase_msg" | grep -qE '\b(test|testing|spec|e2e)\b'; then
        echo "TEST"
        return
    fi

    # Build/CI indicators
    if echo "$lowercase_msg" | grep -qE '\b(build|ci|workflow|pipeline|docker)\b'; then
        echo "BUILD"
        return
    fi

    # Documentation indicators
    if echo "$lowercase_msg" | grep -qE '\b(doc|docs|documentation|readme|comment)\b'; then
        echo "DOCS"
        return
    fi

    echo "UNKNOWN"
}

# Analyze the size and nature of code changes
analyze_code_changes() {
    local diff_content="$1"
    local total_additions=0
    local total_deletions=0
    local files_changed=0
    local product_code_files=0

    # Extract file change statistics
    while IFS= read -r line; do
        if [[ "$line" =~ ^diff\ --git ]]; then
            ((files_changed++))
            # Extract filename from diff line
            if [[ "$line" =~ a/([^\ ]+) ]]; then
                local file="${BASH_REMATCH[1]}"
                if ! is_dependency_file "$file" && ! is_test_file "$file" && \
                   ! is_build_file "$file" && ! is_doc_file "$file"; then
                    ((product_code_files++))
                fi
            fi
        elif [[ "$line" =~ ^[\+] && ! "$line" =~ ^\+\+\+ ]]; then
            ((total_additions++))
        elif [[ "$line" =~ ^[-] && ! "$line" =~ ^--- ]]; then
            ((total_deletions++))
        fi
    done <<< "$diff_content"

    echo "$files_changed:$product_code_files:$total_additions:$total_deletions"
}

# Determine if a change is allowed based on mode and file type
is_change_allowed() {
    local mode="$1"
    local file="$2"
    local commit_type="$3"

    # Always allow dependency, test, build, and doc changes
    if is_dependency_file "$file" || is_test_file "$file" || \
       is_build_file "$file" || is_doc_file "$file"; then
        echo "ALLOWED"
        return
    fi

    # Code lockdown mode: reject all product code changes
    if [[ "$mode" == "code-lockdown" ]]; then
        echo "VIOLATION"
        return
    fi

    # Feature complete mode: allow bug fixes, reject features
    if [[ "$mode" == "feature-complete" ]]; then
        case "$commit_type" in
            BUGFIX|REFACTOR|DOCS|TEST|BUILD|DEPENDENCY)
                echo "ALLOWED"
                ;;
            FEATURE)
                echo "VIOLATION"
                ;;
            UNKNOWN)
                echo "WARNING"
                ;;
        esac
        return
    fi

    echo "UNKNOWN"
}

# Extract files changed from diff
extract_changed_files() {
    local diff_content="$1"
    grep -E '^diff --git' <<< "$diff_content" | sed -E 's|^diff --git a/([^ ]+).*|\1|' || true
}

# Process a single diff file
process_diff_file() {
    local diff_file="$1"
    local component_name=$(basename "$diff_file" .diff)

    # Parse diff file header
    local repo_url=$(grep "^Repo:" "$diff_file" | cut -d' ' -f2)
    local diff_url=$(grep "^Diff:" "$diff_file" | cut -d' ' -f2)
    local base_commit=$(grep "^Base Commit:" "$diff_file" | cut -d' ' -f3)

    # Extract commit SHAs
    local commits=$(grep "^+" "$diff_file" | grep -A1 "^New Commits:" | grep "^+" | sed 's/^+ //' || true)
    local commit_count=$(echo "$commits" | grep -v '^$' | wc -l)

    # Extract the actual diff content (after the header)
    local diff_content=$(sed -n '/^diff --git/,$p' "$diff_file")

    # Analyze code changes
    local change_stats=$(analyze_code_changes "$diff_content")
    IFS=':' read -r files_changed product_files additions deletions <<< "$change_stats"

    # Extract changed files
    local changed_files=$(extract_changed_files "$diff_content")

    # Determine overall violation status
    local has_violation=false
    local has_warning=false
    local violation_files=()
    local warning_files=()
    local allowed_files=()

    # Analyze each changed file
    while IFS= read -r file; do
        [[ -z "$file" ]] && continue

        # For simplicity, we'll use the first commit's message for classification
        # In a more sophisticated version, we could track which commit changed which file
        local commit_type="UNKNOWN"
        if [[ $commit_count -eq 1 ]]; then
            local first_commit=$(echo "$commits" | head -1)
            # We don't have commit messages in the diff file, so we'll classify based on files
            commit_type=$(analyze_commit_message "")
        fi

        # Classify based on file type and mode
        local classification=$(is_change_allowed "$MODE" "$file" "$commit_type")

        case "$classification" in
            VIOLATION)
                has_violation=true
                violation_files+=("$file")
                ;;
            WARNING)
                has_warning=true
                warning_files+=("$file")
                ;;
            ALLOWED)
                allowed_files+=("$file")
                ;;
        esac
    done <<< "$changed_files"

    # Build result object
    local result_status="CLEAN"
    if [[ $has_violation == true ]]; then
        result_status="VIOLATION"
    elif [[ $has_warning == true ]]; then
        result_status="WARNING"
    fi

    # Determine if we should show this result
    local should_show=false
    if [[ "$result_status" == "VIOLATION" ]] || [[ "$result_status" == "WARNING" ]]; then
        should_show=true
    elif [[ "$SHOW_ALLOWED" == true ]]; then
        should_show=true
    fi


    # Output based on format
    if [[ "$should_show" == true ]]; then
        case "$OUTPUT_FORMAT" in
            json)
                output_json "$component_name" "$repo_url" "$diff_url" "$result_status" \
                    "$commit_count" "$files_changed" "$product_files" "$additions" "$deletions" \
                    "$(printf '%s\n' "${violation_files[@]+"${violation_files[@]}"}")" \
                    "$(printf '%s\n' "${warning_files[@]+"${warning_files[@]}"}")" \
                    "$(printf '%s\n' "${allowed_files[@]+"${allowed_files[@]}"}")"
                ;;
            csv)
                output_csv "$component_name" "$repo_url" "$diff_url" "$result_status" \
                    "$commit_count" "$files_changed" "$product_files" "$additions" "$deletions" \
                    "${#violation_files[@]}" "${#warning_files[@]}" "${#allowed_files[@]}"
                ;;
            text)
                output_text "$component_name" "$repo_url" "$diff_url" "$result_status" \
                    "$commit_count" "$files_changed" "$product_files" "$additions" "$deletions" \
                    "$(printf '%s\n' "${violation_files[@]+"${violation_files[@]}"}")" \
                    "$(printf '%s\n' "${warning_files[@]+"${warning_files[@]}"}")" \
                    "$(printf '%s\n' "${allowed_files[@]+"${allowed_files[@]}"}")"
                ;;
        esac
    fi

    # Return status for summary via global variable
    PROCESS_STATUS="$result_status"
}

# Output functions for different formats

output_text() {
    local component="$1"
    local repo_url="$2"
    local diff_url="$3"
    local status="$4"
    local commits="$5"
    local files="$6"
    local product_files="$7"
    local additions="$8"
    local deletions="$9"
    local violations_str="${10}"
    local warnings_str="${11}"
    local allowed_str="${12}"

    # Convert string lists to arrays
    local -a violation_files
    local -a warning_files
    local -a allowed_files

    if [[ -n "$violations_str" ]]; then
        readarray -t violation_files <<< "$violations_str"
    fi
    if [[ -n "$warnings_str" ]]; then
        readarray -t warning_files <<< "$warnings_str"
    fi
    if [[ -n "$allowed_str" ]]; then
        readarray -t allowed_files <<< "$allowed_str"
    fi

    # Determine color based on status
    local status_color="$NC"
    case "$status" in
        VIOLATION)
            status_color="$RED"
            ;;
        WARNING)
            status_color="$YELLOW"
            ;;
        CLEAN)
            status_color="$GREEN"
            ;;
    esac

    echo -e "\n${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BLUE}Component:${NC} $component"
    echo -e "${BLUE}Status:${NC} ${status_color}$status${NC}"
    echo -e "${BLUE}Repository:${NC} $repo_url"
    echo -e "${BLUE}Diff URL:${NC} $diff_url"
    echo -e "${BLUE}Changes:${NC} $commits commit(s), $files file(s) ($product_files product code)"
    echo -e "${BLUE}Lines:${NC} +$additions -$deletions"

    if [[ "$VERBOSE" == true ]] || [[ "$status" != "CLEAN" ]] || [[ "$SHOW_ALLOWED" == true ]]; then
        # Check for violations
        local viol_count=0
        for f in "${violation_files[@]+"${violation_files[@]}"}"; do
            [[ -n "$f" ]] && ((viol_count++))
        done

        if [[ $viol_count -gt 0 ]]; then
            echo -e "\n${RED}⚠ VIOLATIONS (product code changes not allowed in $MODE mode):${NC}"
            for file in "${violation_files[@]}"; do
                [[ -z "$file" ]] && continue
                echo -e "  ${RED}✗${NC} $file"
            done
        fi

        # Check for warnings
        local warn_count=0
        for f in "${warning_files[@]+"${warning_files[@]}"}"; do
            [[ -n "$f" ]] && ((warn_count++))
        done

        if [[ $warn_count -gt 0 ]]; then
            echo -e "\n${YELLOW}⚠ WARNINGS (changes need manual review):${NC}"
            for file in "${warning_files[@]}"; do
                [[ -z "$file" ]] && continue
                echo -e "  ${YELLOW}!${NC} $file"
            done
        fi

        # Check for allowed changes
        local allow_count=0
        for f in "${allowed_files[@]+"${allowed_files[@]}"}"; do
            [[ -n "$f" ]] && ((allow_count++))
        done

        if [[ "$SHOW_ALLOWED" == true ]] && [[ $allow_count -gt 0 ]]; then
            # Count allowed files by type
            local dep_count=0
            local test_count=0
            local build_count=0
            local doc_count=0

            for file in "${allowed_files[@]}"; do
                [[ -z "$file" ]] && continue
                if is_dependency_file "$file"; then
                    ((dep_count++))
                elif is_test_file "$file"; then
                    ((test_count++))
                elif is_build_file "$file"; then
                    ((build_count++))
                elif is_doc_file "$file"; then
                    ((doc_count++))
                fi
            done

            if [[ $((dep_count + test_count + build_count + doc_count)) -gt 0 ]]; then
                echo -e "\n${GREEN}✓ ALLOWED CHANGES:${NC}"
                [[ $dep_count -gt 0 ]] && echo -e "  ${GREEN}✓${NC} Dependencies: $dep_count file(s)"
                [[ $test_count -gt 0 ]] && echo -e "  ${GREEN}✓${NC} Tests: $test_count file(s)"
                [[ $build_count -gt 0 ]] && echo -e "  ${GREEN}✓${NC} Build files: $build_count file(s)"
                [[ $doc_count -gt 0 ]] && echo -e "  ${GREEN}✓${NC} Documentation: $doc_count file(s)"
            fi
        fi
    fi
}

output_json() {
    # Simple JSON output - for production use, consider using jq
    echo "{"
    echo "  \"component\": \"$1\","
    echo "  \"repository\": \"$2\","
    echo "  \"diff_url\": \"$3\","
    echo "  \"status\": \"$4\","
    echo "  \"commits\": $5,"
    echo "  \"files_changed\": $6,"
    echo "  \"product_files\": $7,"
    echo "  \"additions\": $8,"
    echo "  \"deletions\": $9"
    echo "},"
}

output_csv() {
    # CSV header is printed by main function
    echo "$1,$2,$3,$4,$5,$6,$7,$8,$9,${10},${11},${12}"
}

# Main execution

echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}Konflux Diff Analyzer${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}Mode:${NC} $MODE"
echo -e "${BLUE}Analyzing:${NC} ${#diff_files[@]} component(s)"
echo ""

# Print CSV header if needed
if [[ "$OUTPUT_FORMAT" == "csv" ]]; then
    echo "component,repository,diff_url,status,commits,files_changed,product_files,additions,deletions,violations,warnings,allowed"
fi

# Print JSON array opening if needed
if [[ "$OUTPUT_FORMAT" == "json" ]]; then
    echo "{"
    echo "  \"mode\": \"$MODE\","
    echo "  \"components\": ["
fi

# Process each diff file
declare -A status_counts
status_counts[VIOLATION]=0
status_counts[WARNING]=0
status_counts[CLEAN]=0

# Global variable to store status from process_diff_file
PROCESS_STATUS=""

for diff_file in "${diff_files[@]}"; do
    PROCESS_STATUS=""
    process_diff_file "$diff_file"
    status="$PROCESS_STATUS"
    ((status_counts[$status]++)) || true
done

# Print JSON array closing if needed
if [[ "$OUTPUT_FORMAT" == "json" ]]; then
    echo "  ],"
    echo "  \"summary\": {"
    echo "    \"total\": ${#diff_files[@]},"
    echo "    \"violations\": ${status_counts[VIOLATION]},"
    echo "    \"warnings\": ${status_counts[WARNING]},"
    echo "    \"clean\": ${status_counts[CLEAN]}"
    echo "  }"
    echo "}"
fi

# Print summary
if [[ "$OUTPUT_FORMAT" == "text" ]]; then
    echo -e "\n${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BLUE}Summary${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "Total components analyzed: ${#diff_files[@]}"
    echo -e "${RED}Violations:${NC} ${status_counts[VIOLATION]}"
    echo -e "${YELLOW}Warnings:${NC} ${status_counts[WARNING]}"
    echo -e "${GREEN}Clean:${NC} ${status_counts[CLEAN]}"

    if [[ ${status_counts[VIOLATION]} -gt 0 ]]; then
        echo -e "\n${RED}⚠ POLICY VIOLATION DETECTED${NC}"
        echo -e "Components have code changes that violate the $MODE policy."
        exit 1
    elif [[ ${status_counts[WARNING]} -gt 0 ]]; then
        echo -e "\n${YELLOW}⚠ WARNINGS DETECTED${NC}"
        echo -e "Some changes could not be automatically classified."
        echo -e "Manual review recommended."
        exit 0
    else
        echo -e "\n${GREEN}✓ ALL CHECKS PASSED${NC}"
        echo -e "All changes comply with the $MODE policy."
        exit 0
    fi
fi
