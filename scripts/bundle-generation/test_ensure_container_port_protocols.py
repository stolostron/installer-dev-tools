#!/usr/bin/env python3
"""
Unit tests for the ensure_container_port_protocols function in bundles-to-charts.py.
"""

import copy
import importlib.util
import os
import sys
import types
import unittest


def _load_bundles_to_charts():
    """Loads bundles-to-charts.py as a module.

    bundles-to-charts.py does `from validate_csv import *`, but `validate_csv`
    is a module provided by the *consumer* repo (e.g.
    multiclusterhub-operator/hack/bundle-automation/validate_csv.py) at
    runtime via PYTHONPATH, not something that lives in this repo. Stub it
    out here so the module under test can be imported standalone.
    """
    if 'validate_csv' not in sys.modules:
        stub = types.ModuleType('validate_csv')
        stub.validateCSV = lambda csvPath: []
        stub.validateFieldMapping = lambda csv, ruleType, fieldMap: []
        sys.modules['validate_csv'] = stub

    module_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'bundles-to-charts.py')
    spec = importlib.util.spec_from_file_location('bundles_to_charts', module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bundles_to_charts = _load_bundles_to_charts()


class TestEnsureContainerPortProtocols(unittest.TestCase):
    """Test cases for ensure_container_port_protocols."""

    def test_adds_protocol_when_missing(self):
        """A containerPort with no protocol should be defaulted to TCP."""
        spec = {
            'template': {
                'spec': {
                    'containers': [
                        {
                            'name': 'multicluster-operators-hub-subscription',
                            'ports': [{'containerPort': 8443}],
                        }
                    ]
                }
            }
        }

        bundles_to_charts.ensure_container_port_protocols(spec)

        port = spec['template']['spec']['containers'][0]['ports'][0]
        self.assertEqual(port['protocol'], 'TCP')
        self.assertEqual(port['containerPort'], 8443)

    def test_defaults_when_protocol_is_explicit_none(self):
        """A `protocol: null` in the source CSV must not be preserved as None.

        setdefault() would leave this as None since the key is already
        present, which would write `protocol: null` to the generated
        chart. It should be treated the same as a missing protocol.
        """
        spec = {
            'template': {
                'spec': {
                    'containers': [
                        {
                            'name': 'container1',
                            'ports': [{'containerPort': 8443, 'protocol': None}],
                        }
                    ]
                }
            }
        }

        bundles_to_charts.ensure_container_port_protocols(spec)

        port = spec['template']['spec']['containers'][0]['ports'][0]
        self.assertEqual(port['protocol'], 'TCP')

    def test_defaults_when_protocol_is_empty_string(self):
        """An empty-string protocol is also treated as unset."""
        spec = {
            'template': {
                'spec': {
                    'containers': [
                        {
                            'name': 'container1',
                            'ports': [{'containerPort': 8443, 'protocol': ''}],
                        }
                    ]
                }
            }
        }

        bundles_to_charts.ensure_container_port_protocols(spec)

        port = spec['template']['spec']['containers'][0]['ports'][0]
        self.assertEqual(port['protocol'], 'TCP')

    def test_preserves_explicit_non_tcp_protocol(self):
        """An explicitly set protocol (e.g. UDP) must not be overwritten."""
        spec = {
            'template': {
                'spec': {
                    'containers': [
                        {
                            'name': 'container1',
                            'ports': [{'containerPort': 53, 'protocol': 'UDP'}],
                        }
                    ]
                }
            }
        }

        bundles_to_charts.ensure_container_port_protocols(spec)

        port = spec['template']['spec']['containers'][0]['ports'][0]
        self.assertEqual(port['protocol'], 'UDP')

    def test_leaves_explicit_tcp_protocol_unchanged(self):
        """A port that already declares protocol: TCP is left as-is."""
        spec = {
            'template': {
                'spec': {
                    'containers': [
                        {
                            'name': 'container1',
                            'ports': [
                                {'containerPort': 8080, 'name': 'downloads', 'protocol': 'TCP'}
                            ],
                        }
                    ]
                }
            }
        }
        original = copy.deepcopy(spec)

        bundles_to_charts.ensure_container_port_protocols(spec)

        self.assertEqual(spec, original)

    def test_handles_multiple_containers_and_ports(self):
        """Every port across every container should get a default protocol."""
        spec = {
            'template': {
                'spec': {
                    'containers': [
                        {
                            'name': 'container1',
                            'ports': [
                                {'containerPort': 8443},
                                {'containerPort': 9443, 'protocol': 'TCP'},
                            ],
                        },
                        {
                            'name': 'container2',
                            'ports': [{'containerPort': 8080}],
                        },
                    ]
                }
            }
        }

        bundles_to_charts.ensure_container_port_protocols(spec)

        containers = spec['template']['spec']['containers']
        self.assertEqual(containers[0]['ports'][0]['protocol'], 'TCP')
        self.assertEqual(containers[0]['ports'][1]['protocol'], 'TCP')
        self.assertEqual(containers[1]['ports'][0]['protocol'], 'TCP')

    def test_handles_container_with_no_ports(self):
        """A container with no `ports` key at all should not raise."""
        spec = {
            'template': {
                'spec': {
                    'containers': [{'name': 'container1'}]
                }
            }
        }

        # Should not raise.
        bundles_to_charts.ensure_container_port_protocols(spec)

        self.assertNotIn('ports', spec['template']['spec']['containers'][0])

    def test_handles_no_containers_field(self):
        """A spec with no `containers` key at all should not raise."""
        spec = {'template': {'spec': {}}}

        # Should not raise.
        bundles_to_charts.ensure_container_port_protocols(spec)

    def test_handles_empty_spec(self):
        """An empty or None spec should not raise."""
        bundles_to_charts.ensure_container_port_protocols({})
        bundles_to_charts.ensure_container_port_protocols(None)


if __name__ == '__main__':
    unittest.main()
