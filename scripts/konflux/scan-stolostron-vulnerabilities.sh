#!/bin/bash

# Security Vulnerability Scanner for github.com/stolostron repositories
# Scans go.mod files in active repositories for vulnerabilities with CVSS >= 4.0

set -uo pipefail

GITHUB_ORG="stolostron"
MIN_CVSS_SCORE=4.0
CACHE_DIR="/tmp/stolostron-vuln-scan"
RESULTS_FILE="vulnerability-report-$(date +%Y%m%d-%H%M%S).json"
SUMMARY_FILE="vulnerability-summary-$(date +%Y%m%d-%H%M%S).txt"

# Colors for output
RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Check dependencies
check_dependencies() {
    local missing_deps=()

    if ! command -v gh &> /dev/null; then
        missing_deps+=("gh (GitHub CLI)")
    fi

    if ! command -v jq &> /dev/null; then
        missing_deps+=("jq")
    fi

    if ! command -v curl &> /dev/null; then
        missing_deps+=("curl")
    fi

    if [ ${#missing_deps[@]} -ne 0 ]; then
        echo -e "${RED}Error: Missing required dependencies:${NC}"
        for dep in "${missing_deps[@]}"; do
            echo "  - $dep"
        done
        echo ""
        echo "Please install missing dependencies:"
        echo "  - GitHub CLI: https://cli.github.com/"
        echo "  - jq: sudo dnf install jq (or apt-get/brew)"
        exit 1
    fi
}

# Get list of active repositories
get_active_repos() {
    echo -e "${BLUE}Fetching active repositories from ${GITHUB_ORG}...${NC}" >&2

    # Get repos that are not archived - output as JSON array
    gh repo list "$GITHUB_ORG" \
        --limit 1000 \
        --json name,isArchived,defaultBranchRef \
        --jq '[.[] | select(.isArchived == false) | {name: .name, branch: .defaultBranchRef.name}]'
}

# Check if repository has go.mod file
has_gomod() {
    local repo=$1
    local branch=$2

    gh api "repos/${GITHUB_ORG}/${repo}/contents/go.mod?ref=${branch}" &> /dev/null
    return $?
}

# Download go.mod and go.sum files
download_go_files() {
    local repo=$1
    local branch=$2
    local repo_dir="${CACHE_DIR}/${repo}"

    mkdir -p "$repo_dir"

    # Download go.mod
    local content=$(gh api "repos/${GITHUB_ORG}/${repo}/contents/go.mod?ref=${branch}" --jq '.content' 2>/dev/null || echo "")

    if [ -n "$content" ]; then
        echo "$content" | base64 -d > "${repo_dir}/go.mod" 2>/dev/null || return 1

        # Try to download go.sum (optional)
        local sum_content=$(gh api "repos/${GITHUB_ORG}/${repo}/contents/go.sum?ref=${branch}" --jq '.content' 2>/dev/null || echo "")
        if [ -n "$sum_content" ]; then
            echo "$sum_content" | base64 -d > "${repo_dir}/go.sum" 2>/dev/null || true
        fi

        return 0
    fi

    return 1
}

# Scan for vulnerabilities using OSV API
scan_vulnerabilities() {
    local repo=$1
    local repo_dir="${CACHE_DIR}/${repo}"

    if [ ! -f "${repo_dir}/go.mod" ]; then
        echo "[]"
        return 0
    fi

    local all_vulns="[]"

    # Parse dependencies from go.mod (only direct dependencies)
    while IFS= read -r line; do
        # Skip comments and empty lines
        [[ "$line" =~ ^[[:space:]]*// ]] && continue
        [[ -z "$line" ]] && continue

        # Match dependency lines: package version
        if [[ "$line" =~ ^[[:space:]]*([a-zA-Z0-9._/-]+)[[:space:]]+v([0-9]+\.[0-9]+\.[0-9]+[^[:space:]]*) ]]; then
            local pkg="${BASH_REMATCH[1]}"
            local version="v${BASH_REMATCH[2]}"

            # Query OSV API
            local response=$(curl -s -X POST "https://api.osv.dev/v1/query" \
                -H "Content-Type: application/json" \
                -d "{\"package\": {\"name\": \"$pkg\", \"ecosystem\": \"Go\"}, \"version\": \"$version\"}" \
                --max-time 5 2>/dev/null || echo '{}')

            # Parse and filter vulnerabilities
            local pkg_vulns=$(echo "$response" | jq --arg repo "$repo" --arg pkg "$pkg" --argjson min_cvss "$MIN_CVSS_SCORE" '
                [.vulns[]? |
                 select(.database_specific.severity != null or .severity != null) |
                 {
                     cvss: (
                         .database_specific.cvss.score //
                         .database_specific.cvss_score //
                         (if .severity[0]?.score then .severity[0].score else
                          (if .severity[0]?.type == "CRITICAL" then 9.0
                           elif .severity[0]?.type == "HIGH" then 7.5
                           elif .severity[0]?.type == "MODERATE" or .severity[0]?.type == "MEDIUM" then 5.0
                           else 0 end) end)
                     ),
                     data: .
                 } |
                 select(.cvss >= $min_cvss) |
                 {
                     repository: $repo,
                     vulnerability_id: .data.id,
                     package: $pkg,
                     cvss_score: .cvss,
                     severity: (.data.severity[0]?.type // .data.database_specific.severity // "UNKNOWN"),
                     summary: .data.summary,
                     details: (.data.details // ""),
                     fixed_version: ([.data.affected[]?.ranges[]?.events[]? | select(.fixed != null) | .fixed] | first),
                     references: [.data.references[]?.url // empty]
                 }]
            ' 2>/dev/null || echo '[]')

            # Merge results
            all_vulns=$(echo "$all_vulns" "$pkg_vulns" | jq -s 'add' 2>/dev/null || echo "$all_vulns")
        fi
    done < "${repo_dir}/go.mod"

    echo "$all_vulns"
}


# Main scanning function
main() {
    echo -e "${BLUE}╔════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║  Security Vulnerability Scanner for stolostron Organization   ║${NC}"
    echo -e "${BLUE}║  Minimum CVSS Score: ${MIN_CVSS_SCORE}                                      ║${NC}"
    echo -e "${BLUE}╚════════════════════════════════════════════════════════════════╝${NC}"
    echo ""

    check_dependencies

    # Create cache directory
    mkdir -p "$CACHE_DIR"

    # Get active repositories
    local repos=$(get_active_repos)
    local total_repos=$(echo "$repos" | jq 'length')

    echo -e "${GREEN}Found ${total_repos} active repositories${NC}"
    echo ""

    # Initialize results
    local all_vulns="[]"
    local scanned_count=0
    local repos_with_vulns=0

    # Scan each repository
    local repo_count=$(echo "$repos" | jq 'length')
    local i=0

    while [ $i -lt $repo_count ]; do
        local repo_info=$(echo "$repos" | jq -c ".[$i]")
        local repo_name=$(echo "$repo_info" | jq -r '.name')
        local branch=$(echo "$repo_info" | jq -r '.branch // "main"')

        echo -n "[$((i+1))/$repo_count] Scanning ${repo_name} (${branch})... "

        # Check if repo has go.mod
        if ! has_gomod "$repo_name" "$branch" 2>/dev/null; then
            echo -e "${YELLOW}no go.mod${NC}"
            ((i++))
            continue
        fi

        # Download go files
        if ! download_go_files "$repo_name" "$branch" 2>/dev/null; then
            echo -e "${RED}failed to download${NC}"
            ((i++))
            continue
        fi

        # Scan for vulnerabilities
        local repo_vulns=$(scan_vulnerabilities "$repo_name" 2>/dev/null || echo "[]")
        local vuln_count=$(echo "$repo_vulns" | jq 'length' 2>/dev/null || echo "0")

        if [ "$vuln_count" -gt 0 ]; then
            echo -e "${RED}${vuln_count} vulnerabilities found${NC}"
            all_vulns=$(echo "$all_vulns" | jq -s --argjson new "$repo_vulns" '.[0] + $new' 2>/dev/null || echo "$all_vulns")
            ((repos_with_vulns++))
        else
            echo -e "${GREEN}clean${NC}"
        fi

        ((scanned_count++))
        ((i++))
    done

    echo ""
    echo -e "${BLUE}Scan complete. Generating reports...${NC}"

    # Save results
    echo "$all_vulns" | jq '.' > "$RESULTS_FILE"

    # Generate summary
    generate_summary "$all_vulns" "$scanned_count" "$repos_with_vulns"

    echo ""
    echo -e "${BLUE}Results saved to:${NC}"
    echo -e "  - ${RESULTS_FILE}"
    echo -e "  - ${SUMMARY_FILE}"
}

# Generate human-readable summary
generate_summary() {
    local vulns=$1
    local scanned=$2
    local affected=$3

    local total_vulns=$(echo "$vulns" | jq 'length')
    local critical=$(echo "$vulns" | jq '[.[] | select(.cvss_score >= 9.0)] | length')
    local high=$(echo "$vulns" | jq '[.[] | select(.cvss_score >= 7.0 and .cvss_score < 9.0)] | length')
    local medium=$(echo "$vulns" | jq '[.[] | select(.cvss_score >= 4.0 and .cvss_score < 7.0)] | length')

    {
        echo "════════════════════════════════════════════════════════════════"
        echo "  Security Vulnerability Report - stolostron Organization"
        echo "  Generated: $(date)"
        echo "  Minimum CVSS Score: ${MIN_CVSS_SCORE}"
        echo "════════════════════════════════════════════════════════════════"
        echo ""
        echo "SUMMARY"
        echo "-------"
        echo "  Repositories Scanned: ${scanned}"
        echo "  Repositories with Vulnerabilities: ${affected}"
        echo "  Total Vulnerabilities Found: ${total_vulns}"
        echo ""
        echo "SEVERITY BREAKDOWN"
        echo "------------------"
        echo "  Critical (CVSS 9.0+): ${critical}"
        echo "  High (CVSS 7.0-8.9):  ${high}"
        echo "  Medium (CVSS 4.0-6.9): ${medium}"
        echo ""

        if [ "$total_vulns" -gt 0 ]; then
            echo "DETAILED FINDINGS"
            echo "-----------------"
            echo ""

            echo "$vulns" | jq -r '
                group_by(.repository) |
                .[] |
                "Repository: " + .[0].repository + "\n" +
                (. | map(
                    "  • " + .vulnerability_id + " (" + (.cvss_score | tostring) + ")\n" +
                    "    Package: " + .package + "\n" +
                    "    Summary: " + .summary + "\n" +
                    "    Fixed: " + (.fixed_version // "Not available") + "\n"
                ) | join("\n")) + "\n"
            '
        else
            echo "No vulnerabilities found with CVSS score >= ${MIN_CVSS_SCORE}"
        fi

    } | tee "$SUMMARY_FILE"
}

# Run main function
main
