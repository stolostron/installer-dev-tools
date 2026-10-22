#!/usr/bin/env python3
"""
ACM/MCE Release Advisory Updater
Updates payload YAML files with bug fixes and CVEs from Jira
"""

import json
import subprocess
import sys
import re
import yaml
import os
from pathlib import Path
from typing import List, Dict, Tuple, Optional

# Colors for output
class Colors:
    BLUE = '\033[0;34m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    RED = '\033[0;31m'
    NC = '\033[0m'  # No Color

def log_info(msg: str):
    print(f"{Colors.BLUE}[INFO]{Colors.NC} {msg}")

def log_success(msg: str):
    print(f"{Colors.GREEN}[SUCCESS]{Colors.NC} {msg}")

def log_warning(msg: str):
    print(f"{Colors.YELLOW}[WARNING]{Colors.NC} {msg}")

def log_error(msg: str):
    print(f"{Colors.RED}[ERROR]{Colors.NC} {msg}", file=sys.stderr)

def load_component_registry(registry_url: str) -> Dict[str, Dict]:
    """Load and parse the component registry YAML."""
    log_info("Fetching component registry...")

    try:
        result = subprocess.run(
            ['curl', '-s', registry_url],
            capture_output=True,
            text=True,
            check=True
        )
        registry_data = yaml.safe_load(result.stdout)

        # Create a mapping from component name to konflux_component
        component_map = {}
        for component in registry_data.get('components', []):
            name = component.get('name')
            konflux_component = component.get('konflux_component')
            if name and konflux_component:
                component_map[name] = component

        log_success(f"Loaded {len(component_map)} components from registry")
        return component_map
    except Exception as e:
        log_error(f"Failed to load component registry: {e}")
        sys.exit(1)

def parse_version(version_str: str) -> Tuple[str, str, str, str]:
    """
    Parse version string to extract product, major, minor, patch.
    Examples:
      - "ACM-2.14.1" -> ("ACM", "2", "14", "1")
      - "MCE-2.8.4" -> ("MCE", "2", "8", "4")
      - "ACM 2.14.1" -> ("ACM", "2", "14", "1")
    """
    # Remove any dash between product and version
    version_str = version_str.replace('-', ' ')

    match = re.match(r'(ACM|MCE)\s+(\d+)\.(\d+)\.(\d+)', version_str, re.IGNORECASE)
    if match:
        return match.group(1).upper(), match.group(2), match.group(3), match.group(4)
    else:
        raise ValueError(f"Invalid version format: {version_str}")

def get_short_version(major: str, minor: str) -> str:
    """Get short version string (e.g., "214" from major=2, minor=14)."""
    return f"{major}{minor}"

def get_jira_fix_version(product: str, major: str, minor: str, patch: str) -> str:
    """Get Jira fixVersion format (e.g., "ACM 2.14.1")."""
    return f"{product} {major}.{minor}.{patch}"

def query_jira(jql: str, max_results: int = 100) -> List[Dict]:
    """Query Jira using JQL and return results as JSON."""
    log_info(f"Querying Jira with JQL: {jql}")

    try:
        # Query in batches (jira CLI max is 100 per page)
        all_issues = []
        batch_size = min(max_results, 100)
        offset = 0

        while True:
            cmd = [
                'jira', 'issue', 'list',
                '-q', jql,
                '--paginate', f'{offset}:{batch_size}',
                '--raw'
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True,
                timeout=60
            )

            batch_issues = json.loads(result.stdout)
            if not batch_issues:
                break

            all_issues.extend(batch_issues)

            # If we got fewer results than batch size, we're done
            if len(batch_issues) < batch_size:
                break

            offset += batch_size

            # Safety limit
            if offset >= 1000:
                log_warning("Reached maximum of 1000 issues")
                break

        log_success(f"Found {len(all_issues)} issues")
        return all_issues
    except subprocess.TimeoutExpired:
        log_error("Jira query timed out")
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        log_error(f"Jira query failed: {e.stderr}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        log_error(f"Failed to parse Jira response: {e}")
        sys.exit(1)

def get_cve_from_issue(issue: Dict) -> Optional[str]:
    """Extract CVE ID from issue key or summary."""
    key = issue.get('key', '')
    summary = issue.get('fields', {}).get('summary', '')

    # Look for CVE pattern in key or summary
    cve_pattern = r'CVE-\d{4}-\d{4,}'

    # Check key first
    match = re.search(cve_pattern, key, re.IGNORECASE)
    if match:
        return match.group(0).upper()

    # Check summary
    match = re.search(cve_pattern, summary, re.IGNORECASE)
    if match:
        return match.group(0).upper()

    return None

def get_pscomponent_from_labels(labels: List[str]) -> Optional[str]:
    """Extract pscomponent from issue labels."""
    for label in labels:
        if label.startswith('pscomponent:'):
            return label
    return None

def get_component_from_pscomponent(pscomponent: str, component_map: Dict) -> Optional[str]:
    """Map pscomponent label to component name using the registry."""
    if not pscomponent:
        return None

    # Find component in registry by matching prodseccomponent field
    for comp_name, comp_info in component_map.items():
        if comp_info.get('prodseccomponent') == pscomponent:
            return comp_name

    return None

def get_component_label(issue: Dict, component_map: Dict) -> Optional[str]:
    """Extract component name from issue using pscomponent label."""
    labels = issue.get('fields', {}).get('labels', [])

    # For vulnerabilities, look for pscomponent label
    pscomponent = get_pscomponent_from_labels(labels)
    if pscomponent:
        component_name = get_component_from_pscomponent(pscomponent, component_map)
        if component_name:
            return component_name
        else:
            log_warning(f"Could not find component for pscomponent: {pscomponent}")

    # Fallback: try to get from Jira component field
    jira_components = issue.get('fields', {}).get('components', [])
    if jira_components:
        # Map Jira component name to registry component
        # This is a best-effort mapping
        for jira_comp in jira_components:
            jira_comp_name = jira_comp.get('name', '').lower().replace(' ', '-')
            if jira_comp_name in component_map:
                return jira_comp_name

    return None

def map_component_to_konflux(component_label: str, component_map: Dict, product: str,
                             short_version: str) -> Optional[str]:
    """
    Map component label to konflux component name with version suffix.
    Example: "console-mce" -> "console-mce-mce-26" or "console-acm-214"
    """
    if not component_label:
        return None

    component_info = component_map.get(component_label)
    if not component_info:
        log_warning(f"Component '{component_label}' not found in registry")
        return None

    konflux_component = component_info.get('konflux_component', '')

    # Add version suffix
    # The konflux_component already has product suffix (e.g., "console-mce")
    # We need to add the version (e.g., "-26" or "-214")
    component_with_version = f"{konflux_component}-{short_version}"

    return component_with_version

def process_issues(issues: List[Dict], component_map: Dict, product: str,
                   short_version: str) -> Tuple[List[str], List[Dict]]:
    """
    Process Jira issues and separate them into bugs and CVEs.
    Returns: (bug_ids, cve_list)
    """
    bugs = []
    cves_dict = {}  # Use dict to deduplicate by CVE key

    for issue in issues:
        issue_type = issue.get('fields', {}).get('issueType', {}).get('name', '')
        key = issue.get('key', '')

        if issue_type in ['Vulnerability', 'Weakness']:
            # This is a CVE
            cve_id = get_cve_from_issue(issue)
            if not cve_id:
                log_warning(f"Could not extract CVE from vulnerability issue {key}")
                continue

            # Get component from labels
            component_label = get_component_label(issue, component_map)

            if not component_label:
                log_warning(f"Could not determine component for vulnerability {key} ({cve_id})")
                continue

            # Map to konflux component
            konflux_component = map_component_to_konflux(component_label, component_map,
                                                         product, short_version)
            if not konflux_component:
                # Try alternative mapping - use the label directly with version
                konflux_component = f"{component_label}-{short_version}"

            # Add to CVEs dict (key is CVE + component to allow multiple components per CVE)
            cve_key = f"{cve_id}::{konflux_component}"
            if cve_key not in cves_dict:
                cves_dict[cve_key] = {
                    'key': cve_id,
                    'component': konflux_component
                }
                log_info(f"  CVE: {cve_id} -> {konflux_component}")
        else:
            # This is a regular bug
            # Check if it has doc-required label or SFDC counter
            fields = issue.get('fields', {})
            labels = fields.get('labels', [])

            # Check for doc labels
            has_doc_label = any(
                label.lower() in ['doc-required', 'doc-require', 'doc-req']
                for label in labels
            )

            # Note: SFDC counter check would require custom field access
            # For now, we'll rely on the JQL filter to have already filtered these

            if key:
                bugs.append(key)
                log_info(f"  Bug: {key}")

    # Convert CVEs dict to list
    cves = list(cves_dict.values())

    # Sort for consistent output
    bugs.sort()
    cves.sort(key=lambda x: (x['key'], x['component']))

    return bugs, cves

def determine_release_type(bugs: List[str], cves: List[Dict]) -> str:
    """Determine the release type based on content."""
    if cves:
        return "RHSA"  # Security advisory
    elif bugs:
        return "RHBA"  # Bug fix advisory
    else:
        return "RHEA"  # Enhancement advisory

def update_payload_yaml(yaml_path: str, bugs: List[str], cves: List[Dict],
                       product: str) -> bool:
    """Update the payload YAML file with bug and CVE data."""
    log_info(f"Updating payload file: {yaml_path}")

    try:
        # Read the YAML file
        with open(yaml_path, 'r') as f:
            content = f.read()

        # Parse YAML
        data = yaml.safe_load(content)

        # Update release type
        release_type = determine_release_type(bugs, cves)
        data['spec']['data']['releaseNotes']['type'] = release_type

        # Add references for ACM RHSA
        if product == 'ACM' and release_type == 'RHSA':
            if 'references' not in data['spec']['data']['releaseNotes']:
                data['spec']['data']['releaseNotes']['references'] = []
            ref = 'https://access.redhat.com/security/updates/classification/#important'
            if ref not in data['spec']['data']['releaseNotes']['references']:
                data['spec']['data']['releaseNotes']['references'] = [ref]

        # Update bugs
        if bugs:
            if 'issues' not in data['spec']['data']['releaseNotes']:
                data['spec']['data']['releaseNotes']['issues'] = {}
            if 'fixed' not in data['spec']['data']['releaseNotes']['issues']:
                data['spec']['data']['releaseNotes']['issues']['fixed'] = []

            # Clear existing bugs and add new ones
            data['spec']['data']['releaseNotes']['issues']['fixed'] = [
                {'id': bug, 'source': 'issues.redhat.com'} for bug in bugs
            ]
        else:
            # Remove issues section if no bugs
            if 'issues' in data['spec']['data']['releaseNotes']:
                del data['spec']['data']['releaseNotes']['issues']

        # Update CVEs
        if cves:
            data['spec']['data']['releaseNotes']['cves'] = [
                {'key': cve['key'], 'component': cve['component']} for cve in cves
            ]
        else:
            # Remove cves section if no CVEs
            if 'cves' in data['spec']['data']['releaseNotes']:
                del data['spec']['data']['releaseNotes']['cves']

        # Write back to file with proper YAML formatting
        with open(yaml_path, 'w') as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False, width=120)

        log_success(f"Updated {yaml_path}")
        log_info(f"  Release Type: {release_type}")
        log_info(f"  Bugs: {len(bugs)}")
        log_info(f"  CVEs: {len(cves)}")

        return True
    except Exception as e:
        log_error(f"Failed to update {yaml_path}: {e}")
        return False

def main():
    if len(sys.argv) < 2:
        print("Usage: update-advisory.py <version> [target] [jql-query]")
        print()
        print("Arguments:")
        print("  version     Version string (e.g., ACM-2.14.1, MCE-2.8.4)")
        print("  target      Target file: 'prod' or 'rc1', 'rc2', etc. (default: prod)")
        print("  jql-query   Optional custom JQL query")
        print()
        print("Examples:")
        print("  update-advisory.py ACM-2.14.1")
        print("  update-advisory.py ACM-2.14.1 prod")
        print("  update-advisory.py MCE-2.8.4 rc1")
        print("  update-advisory.py MCE-2.8.4 rc2")
        print("  update-advisory.py 'ACM 2.14.1' prod 'custom JQL'")
        print()
        print("The script will:")
        print("  1. Query Jira for bugs and vulnerabilities for the given version")
        print("  2. Map vulnerabilities to component names using the component registry")
        print("  3. Update the payload YAML file with the advisory data")
        sys.exit(1)

    version_str = sys.argv[1]

    # Determine target (prod or rc#)
    target = 'prod'
    custom_jql = None

    if len(sys.argv) > 2:
        # Check if arg 2 is a target or a JQL query
        arg2 = sys.argv[2]
        if arg2.lower() == 'prod' or arg2.lower().startswith('rc'):
            target = arg2.lower()
            custom_jql = sys.argv[3] if len(sys.argv) > 3 else None
        else:
            # Assume it's a JQL query
            custom_jql = arg2

    # Parse version
    try:
        product, major, minor, patch = parse_version(version_str)
        short_version = get_short_version(major, minor)
        jira_fix_version = get_jira_fix_version(product, major, minor, patch)
    except ValueError as e:
        log_error(str(e))
        sys.exit(1)

    log_info(f"Processing {product}-{major}.{minor}.{patch}")
    log_info(f"Short version: {short_version}")
    log_info(f"Jira fix version: {jira_fix_version}")

    # Load component registry
    registry_url = "https://raw.githubusercontent.com/stolostron/acm-config/main/product/component-registry.yaml"
    component_map = load_component_registry(registry_url)

    # Build JQL query
    if custom_jql:
        jql = custom_jql
    else:
        jql = (
            f'project = "Red Hat Advanced Cluster Management" '
            f'AND fixVersion in ("{jira_fix_version}") '
            f'AND ( (labels in (doc-required, doc-require, doc-req) OR "SFDC Cases Counter" > 0) '
            f'OR issuetype in (Vulnerability, Weakness) )'
        )

    # Query Jira
    issues = query_jira(jql)

    if not issues:
        log_warning("No issues found")
        return

    # Process issues
    bugs, cves = process_issues(issues, component_map, product, short_version)

    log_info(f"Found {len(bugs)} bugs and {len(cves)} CVEs")

    # Find and update payload file
    repo_dir = os.environ.get('ACM_RELEASE_REPO', 'acm-release-management')
    version_dir = f"{product.upper()}-{major}.{minor}.{patch}"

    # Determine file path based on target (prod or rc#)
    if target == 'prod':
        payload_file = f"{product.lower()}-{short_version}-payload-prod-z{patch}.yaml"
        payload_path = os.path.join(repo_dir, product.upper(), version_dir, payload_file)
    else:
        # Extract RC number (e.g., "rc1" -> "1")
        rc_match = re.match(r'rc(\d+)', target)
        if not rc_match:
            log_error(f"Invalid target format: {target}. Use 'prod' or 'rc1', 'rc2', etc.")
            sys.exit(1)
        rc_num = rc_match.group(1)

        payload_file = f"{product.lower()}-{short_version}-payload-stage-z{patch}-rc{rc_num}.yaml"
        payload_path = os.path.join(repo_dir, product.upper(), version_dir, target, payload_file)

    if not os.path.exists(payload_path):
        log_error(f"Payload file not found: {payload_path}")
        sys.exit(1)

    log_info(f"Target: {target}")

    # Update the payload file
    success = update_payload_yaml(payload_path, bugs, cves, product)

    if success:
        log_success("Advisory update completed successfully")
    else:
        log_error("Advisory update failed")
        sys.exit(1)

if __name__ == '__main__':
    main()
