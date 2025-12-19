#!/bin/bash

# OpenShift Cluster Image Vulnerability Scanner
# Uses Trivy to scan all container images in the cluster and generate a vulnerability report

set -euo pipefail

# Color codes for output
RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Get script directory
SCRIPT_DIR="$(cd "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
OUTPUT_DIR="${SCRIPT_DIR}/vulnerability-reports"
mkdir -p "$OUTPUT_DIR"

# Default values
SEVERITY="CRITICAL,HIGH"
OUTPUT_FORMAT="table"
SCAN_TIMEOUT=300
NAMESPACE=""
IMAGE_FILTER=""
SKIP_TRIVY_CHECK=false
MAX_PARALLEL_SCANS=5
INCLUDE_UNFIXED=false
TRIVY_DB_REPO=""
OFFLINE_SCAN=false
DETAILED_REPORT=false

# Help function
show_help() {
  local script_name=$(basename "$0")
  cat << EOF
Usage: $script_name [OPTIONS]

Scan container images in an OpenShift cluster for vulnerabilities using Trivy.

Options:
  -n, --namespace NAMESPACE        Scan only images in specific namespace (default: all namespaces)
  -s, --severity SEVERITY          Severity levels to report (default: CRITICAL,HIGH)
                                   Valid values: UNKNOWN,LOW,MEDIUM,HIGH,CRITICAL
  -f, --format FORMAT              Output format (default: table)
                                   Valid values: table, json, sarif, cyclonedx, spdx
  -o, --output-dir DIR             Directory for reports (default: ./vulnerability-reports)
  -t, --timeout SECONDS            Scan timeout per image (default: 300)
  -i, --image-filter PATTERN       Only scan images matching pattern (grep pattern)
  -p, --parallel NUM               Number of parallel scans (default: 5)
  -u, --include-unfixed            Include vulnerabilities without fixes
  -d, --detailed                   Generate detailed per-image reports
  --skip-trivy-check               Skip Trivy installation check
  --trivy-db-repo URL              Custom Trivy DB repository
  --offline                        Offline scan mode (requires pre-downloaded DB)
  -h, --help                       Show this help message

Examples:
  # Scan all images in the cluster
  $script_name

  # Scan only images in specific namespace
  $script_name --namespace openshift-gitops

  # Scan with all severity levels
  $script_name --severity UNKNOWN,LOW,MEDIUM,HIGH,CRITICAL

  # Generate JSON report
  $script_name --format json

  # Scan images matching pattern
  $script_name --image-filter "acm-d"

  # Detailed scan with individual reports
  $script_name --detailed

  # Scan with custom severity and include unfixed vulnerabilities
  $script_name --severity HIGH,CRITICAL --include-unfixed

EOF
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -n|--namespace)
            NAMESPACE="$2"
            shift 2
            ;;
        -s|--severity)
            SEVERITY="$2"
            shift 2
            ;;
        -f|--format)
            OUTPUT_FORMAT="$2"
            shift 2
            ;;
        -o|--output-dir)
            OUTPUT_DIR="$2"
            shift 2
            ;;
        -t|--timeout)
            SCAN_TIMEOUT="$2"
            shift 2
            ;;
        -i|--image-filter)
            IMAGE_FILTER="$2"
            shift 2
            ;;
        -p|--parallel)
            MAX_PARALLEL_SCANS="$2"
            shift 2
            ;;
        -u|--include-unfixed)
            INCLUDE_UNFIXED=true
            shift
            ;;
        -d|--detailed)
            DETAILED_REPORT=true
            shift
            ;;
        --skip-trivy-check)
            SKIP_TRIVY_CHECK=true
            shift
            ;;
        --trivy-db-repo)
            TRIVY_DB_REPO="$2"
            shift 2
            ;;
        --offline)
            OFFLINE_SCAN=true
            shift
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

# Check prerequisites
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}OpenShift Cluster Vulnerability Scanner${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# Check OpenShift CLI
if ! command -v oc &> /dev/null; then
    echo -e "${RED}Error: 'oc' command not found. Please install OpenShift CLI.${NC}"
    exit 1
fi

# Verify cluster connection
echo -n "Checking OpenShift cluster connection... "
if ! oc whoami &> /dev/null; then
    echo -e "${RED}Failed${NC}"
    echo -e "${RED}Error: Not logged into OpenShift cluster. Please run 'oc login' first.${NC}"
    exit 1
fi
echo -e "${GREEN}OK${NC}"

current_context=$(oc project -q 2>/dev/null || echo "unknown")
echo -e "Current project: ${CYAN}$current_context${NC}"
echo ""

# Check/Install Trivy
if [[ "$SKIP_TRIVY_CHECK" != true ]]; then
    echo -n "Checking for Trivy... "
    if ! command -v trivy &> /dev/null; then
        echo -e "${YELLOW}Not found${NC}"
        echo ""
        echo -e "${YELLOW}Trivy is not installed. Installing Trivy...${NC}"

        # Detect OS and architecture
        OS=$(uname -s | tr '[:upper:]' '[:lower:]')
        ARCH=$(uname -m)

        case $ARCH in
            x86_64)
                ARCH="64bit"
                ;;
            aarch64|arm64)
                ARCH="ARM64"
                ;;
            *)
                echo -e "${RED}Error: Unsupported architecture: $ARCH${NC}"
                exit 1
                ;;
        esac

        # Download and install Trivy
        TRIVY_VERSION="0.48.3"
        TRIVY_TAR="trivy_${TRIVY_VERSION}_${OS^}-${ARCH}.tar.gz"
        DOWNLOAD_URL="https://github.com/aquasecurity/trivy/releases/download/v${TRIVY_VERSION}/${TRIVY_TAR}"

        echo "Downloading Trivy from: $DOWNLOAD_URL"

        TEMP_DIR=$(mktemp -d)
        trap "rm -rf $TEMP_DIR" EXIT

        if ! curl -sL "$DOWNLOAD_URL" -o "$TEMP_DIR/$TRIVY_TAR"; then
            echo -e "${RED}Error: Failed to download Trivy${NC}"
            exit 1
        fi

        tar -xzf "$TEMP_DIR/$TRIVY_TAR" -C "$TEMP_DIR"

        # Try to install to user's local bin
        INSTALL_DIR="$HOME/.local/bin"
        mkdir -p "$INSTALL_DIR"

        if mv "$TEMP_DIR/trivy" "$INSTALL_DIR/trivy"; then
            chmod +x "$INSTALL_DIR/trivy"
            export PATH="$INSTALL_DIR:$PATH"
            echo -e "${GREEN}Trivy installed to $INSTALL_DIR/trivy${NC}"
            echo -e "${YELLOW}Note: Add $INSTALL_DIR to your PATH permanently${NC}"
        else
            echo -e "${RED}Error: Failed to install Trivy${NC}"
            echo "You may need to install Trivy manually: https://aquasecurity.github.io/trivy/latest/getting-started/installation/"
            exit 1
        fi
    else
        TRIVY_PATH=$(which trivy)
        TRIVY_VER=$(trivy --version | head -1)
        echo -e "${GREEN}Found${NC} ($TRIVY_PATH - $TRIVY_VER)"
    fi
else
    echo -e "${YELLOW}Skipping Trivy installation check${NC}"
fi
echo ""

# Update Trivy DB if not offline
if [[ "$OFFLINE_SCAN" != true ]]; then
    echo "Updating Trivy vulnerability database..."
    TRIVY_DB_OPTS=""
    if [[ -n "$TRIVY_DB_REPO" ]]; then
        TRIVY_DB_OPTS="--db-repository $TRIVY_DB_REPO"
    fi

    if ! trivy image --download-db-only $TRIVY_DB_OPTS; then
        echo -e "${YELLOW}Warning: Failed to update Trivy database. Continuing with existing DB...${NC}"
    fi
    echo ""
fi

# Get list of images from cluster
echo "Discovering images in cluster..."

if [[ -n "$NAMESPACE" ]]; then
    echo -e "Scanning namespace: ${CYAN}$NAMESPACE${NC}"
    NAMESPACE_FILTER="-n $NAMESPACE"
else
    echo -e "Scanning: ${CYAN}All namespaces${NC}"
    NAMESPACE_FILTER="--all-namespaces"
fi

# Get unique images from all pods
IMAGES=$(oc get pods $NAMESPACE_FILTER -o jsonpath='{range .items[*]}{range .spec.containers[*]}{.image}{"\n"}{end}{range .spec.initContainers[*]}{.image}{"\n"}{end}{end}' | sort -u)

# Apply image filter if specified
if [[ -n "$IMAGE_FILTER" ]]; then
    IMAGES=$(echo "$IMAGES" | grep "$IMAGE_FILTER" || true)
    echo -e "Filter: ${CYAN}$IMAGE_FILTER${NC}"
fi

IMAGE_COUNT=$(echo "$IMAGES" | grep -v '^$' | wc -l)

if [[ $IMAGE_COUNT -eq 0 ]]; then
    echo -e "${YELLOW}No images found to scan.${NC}"
    exit 0
fi

echo -e "Found ${CYAN}$IMAGE_COUNT${NC} unique images to scan"
echo -e "Severity filter: ${CYAN}$SEVERITY${NC}"
echo -e "Output format: ${CYAN}$OUTPUT_FORMAT${NC}"
echo -e "Output directory: ${CYAN}$OUTPUT_DIR${NC}"
echo ""

# Create timestamp for this scan run
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
SUMMARY_REPORT="$OUTPUT_DIR/vulnerability-summary-$TIMESTAMP.txt"
JSON_SUMMARY="$OUTPUT_DIR/vulnerability-summary-$TIMESTAMP.json"

# Initialize summary report
cat > "$SUMMARY_REPORT" << EOF
OpenShift Cluster Vulnerability Scan Report
Generated: $(date)
Namespace: ${NAMESPACE:-All namespaces}
Severity Filter: $SEVERITY
Total Images Scanned: $IMAGE_COUNT

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

EOF

# Initialize JSON summary
echo "{" > "$JSON_SUMMARY"
echo "  \"scan_date\": \"$(date -Iseconds)\"," >> "$JSON_SUMMARY"
echo "  \"namespace\": \"${NAMESPACE:-all}\"," >> "$JSON_SUMMARY"
echo "  \"severity_filter\": \"$SEVERITY\"," >> "$JSON_SUMMARY"
echo "  \"total_images\": $IMAGE_COUNT," >> "$JSON_SUMMARY"
echo "  \"results\": [" >> "$JSON_SUMMARY"

# Tracking variables
TOTAL_CRITICAL=0
TOTAL_HIGH=0
TOTAL_MEDIUM=0
TOTAL_LOW=0
TOTAL_UNKNOWN=0
SCANNED=0
FAILED=0
CLEAN=0

# Detailed vulnerability tracking
DETAILED_VULNS_FILE="$OUTPUT_DIR/detailed-vulnerabilities-$TIMESTAMP.csv"
echo "Image,CVE ID,Severity,CVSS Score,Package Name,Installed Version,Fixed Version,Title" > "$DETAILED_VULNS_FILE"

# Function to scan a single image
scan_image() {
    local image="$1"
    local image_num="$2"
    local total="$3"

    # Sanitize image name for filename
    local safe_name=$(echo "$image" | tr '/:@' '_')
    local scan_output="$OUTPUT_DIR/${safe_name}-${TIMESTAMP}.${OUTPUT_FORMAT}"

    echo -e "${BLUE}[$image_num/$total]${NC} Scanning: ${CYAN}$image${NC}"

    # Build Trivy command
    local trivy_cmd="trivy image"
    trivy_cmd="$trivy_cmd --severity $SEVERITY"
    trivy_cmd="$trivy_cmd --format $OUTPUT_FORMAT"
    trivy_cmd="$trivy_cmd --timeout ${SCAN_TIMEOUT}s"

    if [[ "$INCLUDE_UNFIXED" != true ]]; then
        trivy_cmd="$trivy_cmd --ignore-unfixed"
    fi

    if [[ "$OFFLINE_SCAN" == true ]]; then
        trivy_cmd="$trivy_cmd --skip-db-update"
    fi

    if [[ -n "$TRIVY_DB_REPO" ]]; then
        trivy_cmd="$trivy_cmd --db-repository $TRIVY_DB_REPO"
    fi

    trivy_cmd="$trivy_cmd --quiet"

    # Execute scan
    local scan_result=0
    if [[ "$DETAILED_REPORT" == true ]]; then
        eval "$trivy_cmd --output $scan_output $image" 2>&1 || scan_result=$?
    else
        eval "$trivy_cmd $image" > /dev/null 2>&1 || scan_result=$?
    fi

    # Get vulnerability counts using JSON format temporarily
    local vuln_json=$(trivy image --severity "$SEVERITY" --format json --quiet "$image" 2>/dev/null || echo "{}")

    local critical=$(echo "$vuln_json" | jq '[.Results[]?.Vulnerabilities[]? | select(.Severity=="CRITICAL")] | length' 2>/dev/null || echo "0")
    local high=$(echo "$vuln_json" | jq '[.Results[]?.Vulnerabilities[]? | select(.Severity=="HIGH")] | length' 2>/dev/null || echo "0")
    local medium=$(echo "$vuln_json" | jq '[.Results[]?.Vulnerabilities[]? | select(.Severity=="MEDIUM")] | length' 2>/dev/null || echo "0")
    local low=$(echo "$vuln_json" | jq '[.Results[]?.Vulnerabilities[]? | select(.Severity=="LOW")] | length' 2>/dev/null || echo "0")
    local unknown=$(echo "$vuln_json" | jq '[.Results[]?.Vulnerabilities[]? | select(.Severity=="UNKNOWN")] | length' 2>/dev/null || echo "0")

    local total_vulns=$((critical + high + medium + low + unknown))

    # Update summary
    if [[ $scan_result -ne 0 ]]; then
        echo -e "  ${RED}✗ Scan failed${NC}"
        echo "$image - SCAN FAILED" >> "$SUMMARY_REPORT"
        return 1
    elif [[ $total_vulns -eq 0 ]]; then
        echo -e "  ${GREEN}✓ Clean (no vulnerabilities)${NC}"
        echo "$image - CLEAN" >> "$SUMMARY_REPORT"
        return 0
    else
        local status_color="$YELLOW"
        if [[ $critical -gt 0 ]]; then
            status_color="$RED"
        fi

        echo -e "  ${status_color}⚠ Found vulnerabilities:${NC} CRITICAL=$critical HIGH=$high MEDIUM=$medium LOW=$low UNKNOWN=$unknown"

        cat >> "$SUMMARY_REPORT" << VULN_EOF
$image
  CRITICAL: $critical
  HIGH: $high
  MEDIUM: $medium
  LOW: $low
  UNKNOWN: $unknown
VULN_EOF

        if [[ "$DETAILED_REPORT" == true ]]; then
            echo "  Report: $scan_output"
        fi

        # Extract detailed CVE information and add to CSV
        echo "$vuln_json" | jq -r --arg img "$image" '
            .Results[]?.Vulnerabilities[]? |
            [
                $img,
                .VulnerabilityID,
                .Severity,
                (.CVSS.nvd.V3Score // .CVSS.redhat.V3Score // "N/A"),
                .PkgName,
                .InstalledVersion,
                (.FixedVersion // "No fix available"),
                (.Title // .Description // "N/A" | gsub("[,\n]"; " "))
            ] | @csv
        ' 2>/dev/null >> "$DETAILED_VULNS_FILE" || true

        # Add to JSON
        cat >> "$JSON_SUMMARY" << JSON_EOF
    {
      "image": "$image",
      "status": "vulnerable",
      "vulnerabilities": {
        "critical": $critical,
        "high": $high,
        "medium": $medium,
        "low": $low,
        "unknown": $unknown
      }
    },
JSON_EOF

        return 0
    fi
}

# Scan images
echo -e "${BLUE}Starting vulnerability scan...${NC}"
echo ""

export -f scan_image
export OUTPUT_DIR TIMESTAMP OUTPUT_FORMAT SEVERITY SCAN_TIMEOUT INCLUDE_UNFIXED OFFLINE_SCAN TRIVY_DB_REPO DETAILED_REPORT DETAILED_VULNS_FILE
export RED YELLOW GREEN BLUE CYAN NC

# Counter for images
counter=1

# Process images
while IFS= read -r image; do
    [[ -z "$image" ]] && continue

    if scan_image "$image" "$counter" "$IMAGE_COUNT"; then
        if grep -q "CLEAN" <<< "$(tail -1 "$SUMMARY_REPORT")"; then
            CLEAN=$((CLEAN + 1))
        else
            SCANNED=$((SCANNED + 1))

            # Extract counts from the summary
            scan_line=$(tail -5 "$SUMMARY_REPORT")
            crit=$(echo "$scan_line" | grep "CRITICAL:" | awk '{print $2}' || echo "0")
            high_c=$(echo "$scan_line" | grep "HIGH:" | awk '{print $2}' || echo "0")
            med=$(echo "$scan_line" | grep "MEDIUM:" | awk '{print $2}' || echo "0")
            low_c=$(echo "$scan_line" | grep "LOW:" | awk '{print $2}' || echo "0")
            unk=$(echo "$scan_line" | grep "UNKNOWN:" | awk '{print $2}' || echo "0")

            TOTAL_CRITICAL=$((TOTAL_CRITICAL + crit))
            TOTAL_HIGH=$((TOTAL_HIGH + high_c))
            TOTAL_MEDIUM=$((TOTAL_MEDIUM + med))
            TOTAL_LOW=$((TOTAL_LOW + low_c))
            TOTAL_UNKNOWN=$((TOTAL_UNKNOWN + unk))
        fi
    else
        FAILED=$((FAILED + 1))
    fi

    counter=$((counter + 1))

    echo ""
done <<< "$IMAGES"

# Finalize JSON summary
# Remove trailing comma from last entry
sed -i '$ s/,$//' "$JSON_SUMMARY"
cat >> "$JSON_SUMMARY" << EOF
  ],
  "summary": {
    "scanned": $SCANNED,
    "clean": $CLEAN,
    "failed": $FAILED,
    "total_vulnerabilities": {
      "critical": $TOTAL_CRITICAL,
      "high": $TOTAL_HIGH,
      "medium": $TOTAL_MEDIUM,
      "low": $TOTAL_LOW,
      "unknown": $TOTAL_UNKNOWN
    }
  }
}
EOF

# Add top critical CVEs to summary report
cat >> "$SUMMARY_REPORT" << EOF

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

TOP CRITICAL VULNERABILITIES (Sample)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

EOF

# Add top 10 critical CVEs to summary
if [[ -f "$DETAILED_VULNS_FILE" ]]; then
    grep -i "CRITICAL" "$DETAILED_VULNS_FILE" | head -10 | while IFS=, read -r img cve sev cvss pkg inst fix title; do
        # Remove quotes from CSV fields
        img=$(echo "$img" | tr -d '"')
        cve=$(echo "$cve" | tr -d '"')
        cvss=$(echo "$cvss" | tr -d '"')
        pkg=$(echo "$pkg" | tr -d '"')
        fix=$(echo "$fix" | tr -d '"')

        cat >> "$SUMMARY_REPORT" << CVE_EOF
$cve (CVSS: $cvss)
  Image: $img
  Package: $pkg
  Fixed Version: $fix

CVE_EOF
    done

    echo "For complete CVE details, see: $DETAILED_VULNS_FILE" >> "$SUMMARY_REPORT"
    echo "" >> "$SUMMARY_REPORT"
fi

# Add summary to text report
cat >> "$SUMMARY_REPORT" << EOF

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SUMMARY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Total Images Scanned: $IMAGE_COUNT
  - With Vulnerabilities: $SCANNED
  - Clean: $CLEAN
  - Failed: $FAILED

Total Vulnerabilities Found:
  - CRITICAL: $TOTAL_CRITICAL
  - HIGH: $TOTAL_HIGH
  - MEDIUM: $TOTAL_MEDIUM
  - LOW: $TOTAL_LOW
  - UNKNOWN: $TOTAL_UNKNOWN

Detailed CVE Report: $DETAILED_VULNS_FILE

EOF

# Print final summary
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}Scan Complete${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "Total Images: ${CYAN}$IMAGE_COUNT${NC}"
echo -e "  With Vulnerabilities: ${YELLOW}$SCANNED${NC}"
echo -e "  Clean: ${GREEN}$CLEAN${NC}"
echo -e "  Failed: ${RED}$FAILED${NC}"
echo ""
echo -e "Total Vulnerabilities:"
[[ $TOTAL_CRITICAL -gt 0 ]] && echo -e "  ${RED}CRITICAL: $TOTAL_CRITICAL${NC}" || echo -e "  CRITICAL: $TOTAL_CRITICAL"
[[ $TOTAL_HIGH -gt 0 ]] && echo -e "  ${RED}HIGH: $TOTAL_HIGH${NC}" || echo -e "  HIGH: $TOTAL_HIGH"
[[ $TOTAL_MEDIUM -gt 0 ]] && echo -e "  ${YELLOW}MEDIUM: $TOTAL_MEDIUM${NC}" || echo -e "  MEDIUM: $TOTAL_MEDIUM"
echo -e "  LOW: $TOTAL_LOW"
echo -e "  UNKNOWN: $TOTAL_UNKNOWN"
echo ""
echo -e "Reports saved to:"
echo -e "  ${CYAN}Summary Report:${NC}"
echo -e "    $SUMMARY_REPORT"
echo -e "  ${CYAN}JSON Summary:${NC}"
echo -e "    $JSON_SUMMARY"
echo -e "  ${CYAN}CVE Details (CSV):${NC}"
echo -e "    $DETAILED_VULNS_FILE"

if [[ "$DETAILED_REPORT" == true ]]; then
    echo -e "  ${CYAN}Per-Image Reports:${NC}"
    echo -e "    $OUTPUT_DIR/*-${TIMESTAMP}.${OUTPUT_FORMAT}"
fi

echo ""

# Count CVEs in detailed file
CVE_COUNT=$(($(wc -l < "$DETAILED_VULNS_FILE") - 1))  # Subtract header
if [[ $CVE_COUNT -gt 0 ]]; then
    echo -e "${CYAN}Total CVEs documented: $CVE_COUNT${NC}"
    echo -e "View detailed CVE report: ${CYAN}$DETAILED_VULNS_FILE${NC}"
    echo ""
fi

# Exit with error if critical or high vulnerabilities found
if [[ $TOTAL_CRITICAL -gt 0 ]] || [[ $TOTAL_HIGH -gt 0 ]]; then
    echo -e "${RED}⚠ WARNING: Critical or High severity vulnerabilities detected!${NC}"
    exit 1
else
    echo -e "${GREEN}✓ No Critical or High severity vulnerabilities found${NC}"
    exit 0
fi
