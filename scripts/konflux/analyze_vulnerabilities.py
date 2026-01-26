#!/usr/bin/env python3
"""
Analyze vulnerability CSV files and report high/critical issues by component.

This script reads a vulnerability CSV file (created by parse_vulnerabilities.py)
and reports on high and critical severity vulnerabilities grouped by component.
"""

import csv
import sys
import argparse
from collections import defaultdict
from typing import Dict, List, Set


def analyze_vulnerabilities(csv_file: str, severity_levels: List[str]) -> Dict[str, Dict]:
    """
    Analyze vulnerabilities from CSV file.

    Returns dict of component -> {severity -> count, cves: set()}
    """
    components = defaultdict(lambda: {
        'high': 0,
        'critical': 0,
        'cves': set(),
        'terms': set()
    })

    try:
        with open(csv_file, 'r') as f:
            reader = csv.DictReader(f)

            for row in reader:
                component = row['Component']
                severity = row['SecurityLevel'].lower()
                cve = row.get('CVE', '')
                term = row.get('Term', '')

                # Filter by severity levels
                if severity in severity_levels:
                    components[component][severity] += 1
                    if cve:
                        components[component]['cves'].add(cve)
                    if term:
                        components[component]['terms'].add(term)

    except FileNotFoundError:
        print(f"Error: File not found: {csv_file}", file=sys.stderr)
        sys.exit(1)
    except KeyError as e:
        print(f"Error: Missing column in CSV: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error reading CSV: {e}", file=sys.stderr)
        sys.exit(1)

    return components


def print_summary(components: Dict, severity_levels: List[str], show_cves: bool = False):
    """Print summary report."""
    if not components:
        print("No vulnerabilities found matching the specified severity levels.")
        return

    # Calculate totals
    total_high = sum(c['high'] for c in components.values())
    total_critical = sum(c['critical'] for c in components.values())
    total = total_high + total_critical

    # Header
    print("=" * 80)
    print("VULNERABILITY SUMMARY BY COMPONENT")
    print("=" * 80)
    print(f"Severity Levels: {', '.join(s.upper() for s in severity_levels)}")
    print(f"Total Components Affected: {len(components)}")
    print(f"Total Vulnerabilities: {total} ({total_critical} critical, {total_high} high)")
    print("=" * 80)
    print()

    # Sort components by total count (critical first, then high)
    sorted_components = sorted(
        components.items(),
        key=lambda x: (x[1]['critical'], x[1]['high']),
        reverse=True
    )

    # Print table
    print(f"{'Component':<50} {'Critical':>10} {'High':>10} {'Total':>10}")
    print("-" * 80)

    for component, data in sorted_components:
        critical_count = data['critical']
        high_count = data['high']
        total_count = critical_count + high_count

        print(f"{component:<50} {critical_count:>10} {high_count:>10} {total_count:>10}")

        # Show CVEs if requested
        if show_cves and data['cves']:
            cves = sorted(data['cves'])
            print(f"  CVEs: {', '.join(cves[:5])}")
            if len(cves) > 5:
                print(f"        ... and {len(cves) - 5} more")

    print("-" * 80)
    print(f"{'TOTAL':<50} {total_critical:>10} {total_high:>10} {total:>10}")
    print()


def print_detailed_report(components: Dict, severity_levels: List[str]):
    """Print detailed report with all CVEs."""
    if not components:
        print("No vulnerabilities found matching the specified severity levels.")
        return

    # Sort components by total count
    sorted_components = sorted(
        components.items(),
        key=lambda x: (x[1]['critical'], x[1]['high']),
        reverse=True
    )

    print("=" * 80)
    print("DETAILED VULNERABILITY REPORT")
    print("=" * 80)
    print()

    for component, data in sorted_components:
        critical_count = data['critical']
        high_count = data['high']
        total_count = critical_count + high_count

        print(f"Component: {component}")
        print(f"  Critical: {critical_count}, High: {high_count}, Total: {total_count}")

        if data['cves']:
            print(f"  CVEs ({len(data['cves'])}):")
            for cve in sorted(data['cves']):
                print(f"    - {cve}")

        if data['terms'] and not data['cves']:
            print(f"  Security Advisories ({len(data['terms'])}):")
            for term in sorted(data['terms']):
                print(f"    - {term}")

        print()


def main():
    parser = argparse.ArgumentParser(
        description='Analyze vulnerability CSV files and report high/critical issues by component.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Show high and critical vulnerabilities
  %(prog)s acm-2142.csv

  # Show only critical vulnerabilities
  %(prog)s acm-2142.csv --critical

  # Show detailed report with all CVEs
  %(prog)s acm-2142.csv --detailed

  # Include medium severity
  %(prog)s acm-2142.csv --include-medium

  # Show CVEs in summary view
  %(prog)s acm-2142.csv --show-cves
        """
    )

    parser.add_argument(
        'csv_file',
        help='Path to vulnerability CSV file'
    )

    parser.add_argument(
        '--critical',
        action='store_true',
        help='Show only critical vulnerabilities (excludes high)'
    )

    parser.add_argument(
        '--include-medium',
        action='store_true',
        help='Include medium severity vulnerabilities'
    )

    parser.add_argument(
        '--detailed',
        action='store_true',
        help='Show detailed report with all CVEs'
    )

    parser.add_argument(
        '--show-cves',
        action='store_true',
        help='Show CVEs in summary view (first 5 per component)'
    )

    args = parser.parse_args()

    # Determine severity levels to include
    severity_levels = []
    if args.critical:
        severity_levels = ['critical']
    else:
        severity_levels = ['critical', 'high']

    if args.include_medium:
        severity_levels.append('medium')

    # Analyze vulnerabilities
    components = analyze_vulnerabilities(args.csv_file, severity_levels)

    # Print report
    if args.detailed:
        print_detailed_report(components, severity_levels)
    else:
        print_summary(components, severity_levels, show_cves=args.show_cves)


if __name__ == '__main__':
    main()
