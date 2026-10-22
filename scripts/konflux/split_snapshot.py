#!/usr/bin/env python3
"""
Split a Konflux Snapshot YAML file into individual snapshots per component.

This script takes a snapshot YAML file containing multiple components and
creates separate snapshot files for each component, making it easier to
manage and track individual container images.

Usage:
    ./split_snapshot.py <input_snapshot.yaml> [output_directory]
"""

import sys
import os
import yaml
from pathlib import Path


def sanitize_filename(name):
    """Convert component name to a safe filename."""
    # Replace characters that might cause issues in filenames
    safe_name = name.replace('/', '-').replace(':', '-').replace('@', '-at-')
    return safe_name


def create_single_component_snapshot(original_snapshot, component, base_name, namespace):
    """
    Create a new snapshot containing only one component.

    Args:
        original_snapshot: The original snapshot dict
        component: The component to include
        base_name: Base name for the new snapshot
        namespace: Namespace for the snapshot

    Returns:
        Dict representing the new snapshot
    """
    component_name = component.get('name', 'unknown')

    # Create unique snapshot name based on component name
    snapshot_name = f"{component_name}"

    # Build minimal snapshot with only essential metadata
    new_snapshot = {
        'apiVersion': 'appstudio.redhat.com/v1alpha1',
        'kind': 'Snapshot',
        'metadata': {
            'name': snapshot_name,
            'namespace': namespace
        },
        'spec': {
            'application': original_snapshot['spec'].get('application', ''),
            'artifacts': original_snapshot['spec'].get('artifacts', {}),
            'components': [component]
        }
    }

    return new_snapshot


def split_snapshot(input_file, output_dir=None):
    """
    Split a snapshot YAML file into individual component snapshots.

    Args:
        input_file: Path to input snapshot YAML file
        output_dir: Directory to write output files (default: same as input file)

    Returns:
        List of created file paths
    """
    # Read the input YAML file
    try:
        with open(input_file, 'r') as f:
            snapshot = yaml.safe_load(f)
    except Exception as e:
        print(f"Error reading input file: {e}")
        sys.exit(1)

    # Validate it's a snapshot
    if snapshot.get('kind') != 'Snapshot':
        print(f"Error: Input file is not a Snapshot resource (kind={snapshot.get('kind')})")
        sys.exit(1)

    # Extract metadata
    original_name = snapshot['metadata'].get('name', 'snapshot')
    namespace = snapshot['metadata'].get('namespace', 'default')

    # Get components
    components = snapshot['spec'].get('components', [])
    if not components:
        print("Warning: No components found in snapshot")
        return []

    print(f"Processing snapshot: {original_name}")
    print(f"Found {len(components)} components")
    print(f"Namespace: {namespace}")
    print()

    # Determine output directory
    if output_dir is None:
        output_dir = Path(input_file).parent
    else:
        output_dir = Path(output_dir)

    # Create output directory if it doesn't exist
    output_dir.mkdir(parents=True, exist_ok=True)

    # Process each component
    created_files = []
    for idx, component in enumerate(components, 1):
        component_name = component.get('name', f'component-{idx}')
        container_image = component.get('containerImage', 'unknown')

        print(f"[{idx}/{len(components)}] Processing: {component_name}")
        print(f"  Image: {container_image}")

        # Create new snapshot for this component
        new_snapshot = create_single_component_snapshot(
            snapshot,
            component,
            original_name,
            namespace
        )

        # Generate output filename based on component name
        safe_component_name = sanitize_filename(component_name)
        output_filename = f"snapshot-{safe_component_name}.yaml"
        output_path = output_dir / output_filename

        # Write the new snapshot to file
        try:
            with open(output_path, 'w') as f:
                yaml.dump(new_snapshot, f, default_flow_style=False, sort_keys=False)
            print(f"  Created: {output_path}")
            created_files.append(str(output_path))
        except Exception as e:
            print(f"  Error writing file: {e}")

        print()

    return created_files


def main():
    """Main entry point."""
    # Parse arguments
    if len(sys.argv) < 2:
        print("Usage: split_snapshot.py <input_snapshot.yaml> [output_directory]")
        print()
        print("Example:")
        print("  ./split_snapshot.py snapshot.yaml")
        print("  ./split_snapshot.py snapshot.yaml ./output")
        sys.exit(1)

    input_file = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else None

    # Check input file exists
    if not os.path.exists(input_file):
        print(f"Error: Input file not found: {input_file}")
        sys.exit(1)

    # Split the snapshot
    created_files = split_snapshot(input_file, output_dir)

    # Summary
    print("="*60)
    print(f"Summary: Created {len(created_files)} snapshot files")
    print("="*60)
    if created_files:
        print("\nCreated files:")
        for f in created_files:
            print(f"  - {f}")


if __name__ == '__main__':
    main()
