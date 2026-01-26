#!/usr/bin/env python3
"""
Parse vulnerability warnings from konflux logs and create a CSV file with CVE information.

Usage:
    # Parse a log file and output to CSV
    python3 parse_vulnerabilities.py -i logfile.log -o vulnerabilities.csv

    # Read from stdin
    cat logfile.log | python3 parse_vulnerabilities.py -o output.csv

    # Use default output file (vulnerabilities.csv)
    python3 parse_vulnerabilities.py -i logfile.log

    # Force overwrite existing output file
    python3 parse_vulnerabilities.py -i logfile.log -o existing.csv --force

GitHub API Rate Limiting:
    This script queries the GitHub API for GHSA (GitHub Security Advisory) information.

    Without authentication: 60 requests/hour
    With authentication: 5,000 requests/hour

    To use authentication and avoid rate limits, set the GITHUB_TOKEN environment variable:
        export GITHUB_TOKEN="your_github_personal_access_token"

    Create a token at: https://github.com/settings/tokens (no special scopes needed)

Features:
    - Automatic rate limiting with delays between requests
    - Exponential backoff retry logic for rate limit errors
    - Caching to avoid duplicate API calls
    - Read from file or stdin
    - Prevents accidental overwriting of output files
"""

import sys
import re
import csv
import json
import urllib.request
import urllib.error
import time
import os
import argparse
from typing import Dict, List, Optional, Tuple


# Default log file to parse
#DEFAULT_LOG_FILE = '/home/gparvin/ACM/install/managed-7mrqc-verify-conforma-mce284.log'
DEFAULT_LOG_FILE = '/home/gparvin/ACM/install/managed-46zc4-verify-conforma-acm21110.log'

# Cache for GHSA to CVE lookups and details to avoid rate limiting
_ghsa_cache: Dict[str, Tuple[Optional[str], str]] = {}  # ghsa_id -> (cve_id, details)
# Cache for CVE details lookups
_cve_cache: Dict[str, str] = {}  # cve_id -> details

# Rate limiting settings
_last_github_request_time = 0
_last_osv_request_time = 0
GITHUB_API_DELAY = 1.0  # Delay between GitHub API requests (seconds)
OSV_API_DELAY = 0.5  # Delay between OSV API requests (seconds)

# Retry settings
MAX_RETRIES = 3
INITIAL_RETRY_DELAY = 2.0  # Initial delay for exponential backoff (seconds)


def rate_limit_github_api():
    """Enforce rate limiting for GitHub API requests."""
    global _last_github_request_time
    current_time = time.time()
    time_since_last_request = current_time - _last_github_request_time

    if time_since_last_request < GITHUB_API_DELAY:
        sleep_time = GITHUB_API_DELAY - time_since_last_request
        time.sleep(sleep_time)

    _last_github_request_time = time.time()


def rate_limit_osv_api():
    """Enforce rate limiting for OSV API requests."""
    global _last_osv_request_time
    current_time = time.time()
    time_since_last_request = current_time - _last_osv_request_time

    if time_since_last_request < OSV_API_DELAY:
        sleep_time = OSV_API_DELAY - time_since_last_request
        time.sleep(sleep_time)

    _last_osv_request_time = time.time()


def make_http_request_with_retry(url: str, headers: dict, timeout: int = 10, api_name: str = "API") -> Optional[dict]:
    """
    Make HTTP request with exponential backoff retry logic.
    Returns parsed JSON or None on failure.
    """
    for attempt in range(MAX_RETRIES):
        try:
            req = urllib.request.Request(url)
            for header_name, header_value in headers.items():
                req.add_header(header_name, header_value)

            with urllib.request.urlopen(req, timeout=timeout) as response:
                return json.loads(response.read().decode())

        except urllib.error.HTTPError as e:
            if e.code == 403:
                # Rate limit exceeded
                if attempt < MAX_RETRIES - 1:
                    delay = INITIAL_RETRY_DELAY * (2 ** attempt)  # Exponential backoff
                    print(f"  Rate limit hit for {api_name}, retrying in {delay:.1f}s (attempt {attempt + 1}/{MAX_RETRIES})...", file=sys.stderr)
                    time.sleep(delay)
                else:
                    print(f"  Max retries reached for {api_name}, skipping...", file=sys.stderr)
                    return None
            elif e.code == 404:
                # Not found, no point in retrying
                return None
            else:
                # Other HTTP error
                if attempt < MAX_RETRIES - 1:
                    delay = INITIAL_RETRY_DELAY * (2 ** attempt)
                    print(f"  HTTP {e.code} error for {api_name}, retrying in {delay:.1f}s...", file=sys.stderr)
                    time.sleep(delay)
                else:
                    return None

        except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as e:
            if attempt < MAX_RETRIES - 1:
                delay = INITIAL_RETRY_DELAY * (2 ** attempt)
                print(f"  Error accessing {api_name}: {e}, retrying in {delay:.1f}s...", file=sys.stderr)
                time.sleep(delay)
            else:
                return None

    return None


def get_cve_and_details_from_ghsa(ghsa_id: str) -> Tuple[Optional[str], str]:
    """
    Look up CVE ID and details from GitHub Security Advisory ID using GitHub API.
    Returns tuple of (CVE ID, details) where details includes fix information or summary.
    Uses caching to avoid duplicate lookups.
    Supports authentication via GITHUB_TOKEN environment variable.
    """
    # Check cache first
    if ghsa_id in _ghsa_cache:
        return _ghsa_cache[ghsa_id]

    # Apply rate limiting before making request
    rate_limit_github_api()

    # GitHub API endpoint for security advisories
    url = f"https://api.github.com/advisories/{ghsa_id}"

    # Prepare headers
    headers = {
        'Accept': 'application/vnd.github+json',
        'User-Agent': 'CVE-Parser/1.0',
        'X-GitHub-Api-Version': '2022-11-28'
    }

    # Add authentication if token is available
    github_token = os.getenv('GITHUB_TOKEN')
    if github_token:
        headers['Authorization'] = f'token {github_token}'

    # Make request with retry logic
    data = make_http_request_with_retry(url, headers, timeout=10, api_name=f"GitHub API ({ghsa_id})")

    if data:
        # Extract CVE ID from identifiers
        cve_id = None
        if 'identifiers' in data:
            for identifier in data['identifiers']:
                if identifier.get('type') == 'CVE':
                    cve_id = identifier.get('value')
                    break

        # Also check cve_id field
        if not cve_id and 'cve_id' in data and data['cve_id']:
            cve_id = data['cve_id']

        # Extract fix/remediation details
        details = extract_details_from_advisory(data)

        # Cache the result
        _ghsa_cache[ghsa_id] = (cve_id, details)
        return cve_id, details
    else:
        # If lookup fails, cache None/empty to avoid retrying
        _ghsa_cache[ghsa_id] = (None, "")
        print(f"  Warning: Could not lookup CVE for {ghsa_id}", file=sys.stderr)

    return None, ""


def extract_details_from_advisory(data: dict) -> str:
    """
    Extract fix/remediation details from GitHub advisory data.
    Priority:
    1. Fixed version information from vulnerabilities array
    2. Summary if no fix information available
    """
    details_parts = []

    # Try to extract fixed versions from vulnerabilities
    if 'vulnerabilities' in data and data['vulnerabilities']:
        for vuln in data['vulnerabilities']:
            package_name = vuln.get('package', {}).get('name', '')

            # Look for patched versions
            if 'patched_versions' in vuln and vuln['patched_versions']:
                patched = vuln['patched_versions']
                if patched and patched != 'none':
                    details_parts.append(f"Fix: {package_name} {patched}")

            # If no patched versions, look for vulnerable version ranges
            elif 'vulnerable_version_range' in vuln and vuln['vulnerable_version_range']:
                vuln_range = vuln['vulnerable_version_range']
                if package_name:
                    details_parts.append(f"Affects: {package_name} {vuln_range}")

    # If we found fix/version info, return it
    if details_parts:
        return '; '.join(details_parts[:2])  # Limit to first 2 entries to keep brief

    # Otherwise, use summary (truncated to keep brief)
    if 'summary' in data and data['summary']:
        summary = data['summary'].strip()
        # Truncate if too long
        if len(summary) > 120:
            summary = summary[:117] + "..."
        return summary

    return ""


def get_cve_details(cve_id: str) -> str:
    """
    For direct CVE entries (not GHSA), fetch package details from OSV API.
    Returns details about affected package and marks as base image vulnerability.
    Uses caching to avoid duplicate lookups.
    """
    # Check cache first
    if cve_id in _cve_cache:
        return _cve_cache[cve_id]

    # Apply rate limiting before making request
    rate_limit_osv_api()

    # OSV API endpoint
    url = f"https://api.osv.dev/v1/vulns/{cve_id}"

    # Prepare headers
    headers = {
        'Content-Type': 'application/json',
        'User-Agent': 'CVE-Parser/1.0'
    }

    # Make request with retry logic
    data = make_http_request_with_retry(url, headers, timeout=10, api_name=f"OSV API ({cve_id})")

    if data:
        # Extract package information
        details = extract_cve_package_info(data)

        # Cache the result
        _cve_cache[cve_id] = details
        return details
    else:
        # If lookup fails, cache empty string to avoid retrying
        _cve_cache[cve_id] = ""
        print(f"  Warning: Could not lookup details for {cve_id}", file=sys.stderr)

    return ""


def extract_cve_package_info(data: dict) -> str:
    """
    Extract package information from OSV CVE data.
    Marks as base image vulnerability.
    """
    packages = []

    # Extract affected packages
    if 'affected' in data and data['affected']:
        for affected in data['affected']:
            if 'package' in affected and 'name' in affected['package']:
                pkg_name = affected['package']['name']
                ecosystem = affected['package'].get('ecosystem', '')

                # Determine if this is a base image package
                base_image_indicators = [
                    'Debian', 'Ubuntu', 'Alpine', 'Red Hat', 'RHEL',
                    'cpe', 'OS', 'Linux'
                ]

                is_base_image = any(indicator in ecosystem for indicator in base_image_indicators)

                # Look for version information
                version_info = ""
                if 'ranges' in affected and affected['ranges']:
                    for range_obj in affected['ranges']:
                        if 'events' in range_obj:
                            for event in range_obj['events']:
                                if 'fixed' in event:
                                    version_info = f" (fix: {event['fixed']})"
                                    break
                            if version_info:
                                break

                # Format package info
                if is_base_image:
                    packages.append(f"Base image: {pkg_name}{version_info}")
                else:
                    packages.append(f"{pkg_name}{version_info}")

    if packages:
        # Limit to first 2 packages to keep brief
        return '; '.join(packages[:2])

    # Try to extract package from details or summary field
    text_to_search = ""
    if 'details' in data and data['details']:
        text_to_search = data['details']
    elif 'summary' in data and data['summary']:
        text_to_search = data['summary']

    if text_to_search:
        # Define base OS packages with their common names
        base_packages = {
            'glibc': ['GNU C Library', 'glibc'],
            'libxml2': ['libxml2'],
            'openssl': ['OpenSSL', 'openssl'],
            'curl': ['curl', 'libcurl'],
            'sqlite': ['SQLite', 'sqlite'],
            'libarchive': ['libarchive'],
            'rsync': ['rsync'],
            'bind': ['BIND', 'ISC BIND', 'bind'],
            'libtasn1': ['libtasn1'],
            'gnutls': ['GnuTLS', 'gnutls'],
            'libxslt': ['libxslt'],
            'vim': ['Vim'],
            'requests': ['Requests'],
            'libssh': ['libssh'],
            'libtiff': ['libtiff'],
            'expat': ['expat'],
            'zlib': ['zlib'],
            'python': ['Python'],
        }

        # Check for each package
        for pkg_canonical, pkg_variants in base_packages.items():
            for variant in pkg_variants:
                if variant in text_to_search:
                    # Extract version if mentioned
                    version_match = re.search(rf'{re.escape(variant)}[:\s]+(?:versions?\s+)?([0-9.]+(?:\s+to\s+[0-9.]+)?)', text_to_search, re.IGNORECASE)
                    version_info = ""
                    if version_match:
                        version_info = f" {version_match.group(1)}"

                    return f"Base image: {pkg_canonical}{version_info}"

        # If no specific package identified, return truncated description
        if len(text_to_search) > 80:
            text_to_search = text_to_search[:77] + "..."
        return text_to_search

    return ""


def extract_image_name(image_ref: str) -> str:
    """
    Extract image name without digest.
    Example: quay.io/repo/image@sha256:abc123 -> quay.io/repo/image
    """
    if '@sha256:' in image_ref:
        return image_ref.split('@sha256:')[0]
    return image_ref


def extract_component_name(image_ref: str) -> str:
    """
    Extract component name from image reference.
    Example: quay.io/redhat-user-workloads/crt-redhat-acm-tenant/work-mce-28@sha256:... -> work-mce-28
    """
    # Remove digest first
    image_path = image_ref.split('@sha256:')[0] if '@sha256:' in image_ref else image_ref

    # Extract the last part of the path (component name)
    parts = image_path.split('/')
    if parts:
        return parts[-1]

    return ""


def parse_vulnerabilities(input_file) -> List[Dict[str, str]]:
    """Parse vulnerability warnings from log file."""
    vulnerabilities = []
    current_entry = {}

    for line in input_file:
        line = line.strip()

        # Check for ImageRef
        if line.startswith('ImageRef:'):
            current_entry['ImageRef'] = line.split('ImageRef:', 1)[1].strip()

        # Check for Reason (contains security level)
        elif line.startswith('Reason:'):
            # Extract security level from reason
            match = re.search(r'(critical|high|medium|low|unknown)\s+security\s+level', line, re.IGNORECASE)
            if match:
                current_entry['SecurityLevel'] = match.group(1).lower()

        # Check for Term
        elif line.startswith('Term:'):
            term = line.split('Term:', 1)[1].strip()
            current_entry['Term'] = term

            # When we have all three fields, add to list
            if all(key in current_entry for key in ['ImageRef', 'Term', 'SecurityLevel']):
                # Extract component name
                current_entry['Component'] = extract_component_name(current_entry['ImageRef'])

                # Determine CVE and details
                if term.startswith('CVE-'):
                    # Term is already a CVE
                    current_entry['CVE'] = term
                    if term not in _cve_cache:
                        print(f"Looking up details for {term}...", file=sys.stderr)
                    current_entry['Details'] = get_cve_details(term)
                elif term.startswith('GHSA-'):
                    # Term is a GHSA, try to look up CVE and details (with caching)
                    if term not in _ghsa_cache:
                        print(f"Looking up CVE for {term}...", file=sys.stderr)
                    cve, details = get_cve_and_details_from_ghsa(term)
                    current_entry['CVE'] = cve if cve else ''
                    current_entry['Details'] = details
                else:
                    current_entry['CVE'] = ''
                    current_entry['Details'] = ''

                vulnerabilities.append(current_entry.copy())
                current_entry = {}

    return vulnerabilities


def deduplicate_vulnerabilities(vulnerabilities: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """
    Deduplicate vulnerabilities by image name (without digest) and term.
    Keeps the first occurrence of each unique combination.
    """
    seen = set()
    deduplicated = []

    for vuln in vulnerabilities:
        image_name = extract_image_name(vuln['ImageRef'])
        term = vuln['Term']
        security_level = vuln['SecurityLevel']

        # Create a unique key for this vulnerability
        key = (image_name, term, security_level)

        if key not in seen:
            seen.add(key)
            deduplicated.append(vuln)

    return deduplicated


def write_csv(vulnerabilities: List[Dict[str, str]], output_file: str):
    """Write vulnerabilities to CSV file."""
    if not vulnerabilities:
        print("No vulnerabilities found in input", file=sys.stderr)
        return

    with open(output_file, 'w', newline='') as csvfile:
        fieldnames = ['Component', 'ImageRef', 'Term', 'CVE', 'SecurityLevel', 'Details']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

        writer.writeheader()
        for vuln in vulnerabilities:
            writer.writerow(vuln)

    print(f"\nWrote {len(vulnerabilities)} vulnerabilities to {output_file}")

    # Print summary statistics
    cve_count = sum(1 for v in vulnerabilities if v['CVE'])
    ghsa_count = sum(1 for v in vulnerabilities if v['Term'].startswith('GHSA-'))
    ghsa_with_cve = sum(1 for v in vulnerabilities if v['Term'].startswith('GHSA-') and v['CVE'])
    ghsa_without_cve = ghsa_count - ghsa_with_cve
    with_details = sum(1 for v in vulnerabilities if v.get('Details'))

    print(f"  Total CVEs (direct): {sum(1 for v in vulnerabilities if v['Term'].startswith('CVE-'))}")
    print(f"  Total GHSAs: {ghsa_count}")
    print(f"  GHSAs with CVE mapping: {ghsa_with_cve}")
    if ghsa_without_cve > 0:
        print(f"  GHSAs without CVE mapping: {ghsa_without_cve}")
    print(f"  Entries with details: {with_details}")
    print(f"  Unique GHSA IDs looked up: {len(_ghsa_cache)}")
    print(f"  Unique CVE IDs looked up: {len(_cve_cache)}")


def main():
    parser = argparse.ArgumentParser(
        description='Parse vulnerability warnings from konflux logs and create a CSV file with CVE information.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Parse a log file and output to CSV
  %(prog)s -i logfile.log -o vulnerabilities.csv

  # Read from stdin
  cat logfile.log | %(prog)s -o output.csv

  # Use default output file (vulnerabilities.csv)
  %(prog)s -i logfile.log

  # Force overwrite existing output file
  %(prog)s -i logfile.log -o existing.csv --force

Environment Variables:
  GITHUB_TOKEN    GitHub personal access token for higher API rate limits
                  (5,000 requests/hour vs 60 without authentication)
        """
    )

    parser.add_argument(
        '-i', '--input',
        metavar='FILE',
        help='Input log file to parse. If not specified, reads from stdin.'
    )

    parser.add_argument(
        '-o', '--output',
        metavar='FILE',
        default='vulnerabilities.csv',
        help='Output CSV file (default: vulnerabilities.csv)'
    )

    parser.add_argument(
        '-f', '--force',
        action='store_true',
        help='Force overwrite of output file if it exists'
    )

    args = parser.parse_args()

    # Check if output file exists
    if os.path.exists(args.output) and not args.force:
        print(f"❌ Error: Output file '{args.output}' already exists", file=sys.stderr)
        print(f"   Use --force to overwrite, or specify a different output file with -o", file=sys.stderr)
        sys.exit(1)

    # Check for GitHub token and inform user
    github_token = os.getenv('GITHUB_TOKEN')
    if github_token:
        print("✓ GitHub authentication enabled (5,000 requests/hour)", file=sys.stderr)
    else:
        print("⚠  No GitHub token found - using unauthenticated API (60 requests/hour)", file=sys.stderr)
        print("   Set GITHUB_TOKEN environment variable to increase rate limit:", file=sys.stderr)
        print("   export GITHUB_TOKEN='your_token'", file=sys.stderr)
    print("", file=sys.stderr)

    # Determine input source
    if args.input:
        print(f"Parsing log file: {args.input}", file=sys.stderr)
        try:
            with open(args.input, 'r') as f:
                vulnerabilities = parse_vulnerabilities(f)
        except FileNotFoundError:
            print(f"❌ Error: Log file not found: {args.input}", file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            print(f"❌ Error reading log file: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        print("Reading from stdin...", file=sys.stderr)
        try:
            vulnerabilities = parse_vulnerabilities(sys.stdin)
        except Exception as e:
            print(f"❌ Error reading from stdin: {e}", file=sys.stderr)
            sys.exit(1)

    print(f"Output file: {args.output}", file=sys.stderr)
    print("", file=sys.stderr)

    print(f"\nParsed {len(vulnerabilities)} total vulnerability entries", file=sys.stderr)

    # Deduplicate by image name (without digest) and term
    deduplicated = deduplicate_vulnerabilities(vulnerabilities)
    print(f"After deduplication: {len(deduplicated)} unique vulnerabilities", file=sys.stderr)

    # Write to CSV
    write_csv(deduplicated, args.output)


if __name__ == '__main__':
    main()
