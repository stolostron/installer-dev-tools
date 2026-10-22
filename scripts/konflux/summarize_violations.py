#!/usr/bin/env python3
"""
Policy Violation Summary Script

Parses konflux log files and summarizes policy violations by component and violation type.
"""

import re
import sys
import glob
from collections import defaultdict, Counter
from pathlib import Path

def extract_component_from_image(image_ref):
    """Extract component name from image reference."""
    # Example: quay.io/redhat-user-workloads/crt-redhat-acm-tenant/release-mce-27/hypershift-addon-operator-mce-27@sha256:...
    # We want: hypershift-addon-operator-mce-27
    
    if not image_ref:
        return "unknown"
    
    # Split by '/' and take the last part before '@'
    parts = image_ref.split('/')
    if len(parts) >= 4:
        # Take the last part (component) from the path
        component_part = parts[-1].split('@')[0]
        return component_part
    
    # Fallback: try to extract from the full path
    match = re.search(r'/([^/@]+)@sha256:', image_ref)
    if match:
        return match.group(1)
    
    return "unknown"

def simplify_violation_type(violation_title):
    """Simplify violation type to a human-readable summary."""
    simplifications = {
        'trusted_task.trusted': 'Task not trusted',
        'tasks.required_untrusted_task_found': 'Required untrusted task found',
        'test.no_erred_tests': 'ClamAV scan test error',
        'slsa_build_scripted_build.image_built_by_trusted_task': 'Image not built by trusted task',
        'quay_expiration.expires_label': 'Missing expiration label',
        'tasks.required_tasks_found': 'Required tasks missing'
    }
    
    return simplifications.get(violation_title, violation_title)

def parse_violation_block(lines, start_idx):
    """Parse a single violation block starting from the given index."""
    violation = {}
    current_idx = start_idx
    
    # Extract violation type from first line
    violation_line = lines[current_idx].strip()
    match = re.search(r'✕ \[Violation\] (.+)', violation_line)
    if match:
        violation['type'] = match.group(1)
        violation['simplified_type'] = simplify_violation_type(match.group(1))
    
    current_idx += 1
    
    # Parse subsequent lines until we hit another violation or end
    while current_idx < len(lines):
        line = lines[current_idx].strip()
        
        # Stop if we hit another violation or empty line followed by violation
        if line.startswith('✕ [Violation]'):
            break
        if not line and current_idx + 1 < len(lines) and lines[current_idx + 1].strip().startswith('✕ [Violation]'):
            break
            
        # Extract key information
        if line.startswith('ImageRef:'):
            violation['image_ref'] = line.replace('ImageRef:', '').strip()
            violation['component'] = extract_component_from_image(violation['image_ref'])
        elif line.startswith('Reason:'):
            violation['reason'] = line.replace('Reason:', '').strip()
        elif line.startswith('Term:'):
            violation['term'] = line.replace('Term:', '').strip()
        elif line.startswith('Title:'):
            violation['title'] = line.replace('Title:', '').strip()
        
        current_idx += 1
    
    return violation, current_idx

def parse_log_file(file_path):
    """Parse a single log file and extract all violations."""
    violations = []
    
    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
        lines = f.readlines()
    
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith('✕ [Violation]'):
            violation, next_idx = parse_violation_block(lines, i)
            if violation.get('component') and violation.get('type'):
                violations.append(violation)
            i = next_idx
        else:
            i += 1
    
    return violations

def main():
    if len(sys.argv) > 1:
        log_files = sys.argv[1:]
    else:
        # Default to all managed-*-verify-conforma.log files in logs directory
        log_files = glob.glob('./logs/managed-*-verify-conforma.log')
    
    if not log_files:
        print("No log files found. Usage: python3 summarize_violations.py [log_files...]")
        sys.exit(1)
    
    print(f"Processing {len(log_files)} log files...")
    
    all_violations = []
    for log_file in log_files:
        violations = parse_log_file(log_file)
        all_violations.extend(violations)
    
    print(f"\nFound {len(all_violations)} total violations\n")
    
    # Group by component and violation type
    component_violations = defaultdict(lambda: defaultdict(list))
    violation_type_counts = Counter()
    component_counts = Counter()
    
    for violation in all_violations:
        component = violation['component']
        vtype = violation['simplified_type']
        component_violations[component][vtype].append(violation)
        violation_type_counts[vtype] += 1
        component_counts[component] += 1
    
    # Print summary by violation type
    print("=== VIOLATION TYPES SUMMARY ===")
    for vtype, count in violation_type_counts.most_common():
        print(f"{count:3d} | {vtype}")
    
    print(f"\n=== COMPONENT SUMMARY ({len(component_counts)} components) ===")
    for component, count in component_counts.most_common():
        print(f"{count:3d} violations | {component}")
    
    print(f"\n=== DETAILED BREAKDOWN BY COMPONENT ===")
    for component in sorted(component_violations.keys()):
        violations_by_type = component_violations[component]
        total_violations = sum(len(v) for v in violations_by_type.values())
        
        print(f"\n📦 {component} ({total_violations} violations)")
        for vtype in sorted(violations_by_type.keys()):
            violation_list = violations_by_type[vtype]
            print(f"   {len(violation_list):2d} × {vtype}")
            
            # Show unique reasons/terms if available
            reasons = set()
            terms = set()
            for v in violation_list:
                if v.get('reason'):
                    reasons.add(v['reason'])
                if v.get('term'):
                    terms.add(v['term'])
            
            if len(reasons) == 1:
                print(f"       → {list(reasons)[0]}")
            elif len(terms) == 1:
                print(f"       → Term: {list(terms)[0]}")
    
    print(f"\n=== COMMON FAILURE PATTERNS ===")
    # Group violations by type and reason to find common patterns
    pattern_counts = Counter()
    for violation in all_violations:
        vtype = violation.get('simplified_type', 'unknown')
        reason = violation.get('reason', 'no reason')
        term = violation.get('term', '')
        
        # Create a pattern key
        if term:
            pattern = f"{vtype} (Term: {term})"
        else:
            pattern = f"{vtype}: {reason[:80]}"
        
        pattern_counts[pattern] += 1
    
    for pattern, count in pattern_counts.most_common(10):
        affected_components = set()
        for violation in all_violations:
            vtype = violation.get('simplified_type', 'unknown')
            reason = violation.get('reason', 'no reason')
            term = violation.get('term', '')
            
            if term:
                check_pattern = f"{vtype} (Term: {term})"
            else:
                check_pattern = f"{vtype}: {reason[:80]}"
            
            if check_pattern == pattern:
                affected_components.add(violation.get('component', 'unknown'))
        
        print(f"{count:3d} violations | {pattern}")
        if len(affected_components) > 1:
            print(f"      → Affects {len(affected_components)} components: {', '.join(sorted(list(affected_components)[:5]))}")
            if len(affected_components) > 5:
                print(f"        (and {len(affected_components) - 5} more)")

if __name__ == '__main__':
    main()