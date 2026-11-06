"""
Regression tests for RBAC subject namespace templating in generate-charts.

Covers the fallback used when a ClusterRoleBinding/RoleBinding subject does
not declare a namespace (e.g. a Group subject). The generator must fall back
to the chart's global namespace instead of raising UnboundLocalError and
leaving the file as raw ``helm template`` output.
"""

import os
import tempfile
import unittest

import yaml
from test_helpers import load_script_module

generate_charts = load_script_module('generate_charts', 'generate-charts.py')


def _build_chart(tmpdir, templates):
    """Create a minimal chart directory with the given template files."""
    chart = os.path.join(tmpdir, 'test-chart')
    tpl_dir = os.path.join(chart, 'templates')
    os.makedirs(tpl_dir)

    for filename, content in templates.items():
        with open(os.path.join(tpl_dir, filename), 'w') as f:
            yaml.dump(content, f, sort_keys=False)

    with open(os.path.join(chart, 'values.yaml'), 'w') as f:
        yaml.dump({'global': {'imageOverrides': {}, 'pullPolicy': 'IfNotPresent'}}, f)

    with open(os.path.join(chart, 'Chart.yaml'), 'w') as f:
        yaml.dump({'apiVersion': 'v2', 'name': 'test-chart', 'version': '0.0.1'}, f)

    return chart


def _cluster_role_binding(subjects):
    return {
        'apiVersion': 'rbac.authorization.k8s.io/v1',
        'kind': 'ClusterRoleBinding',
        'metadata': {'name': 'capz-reader-rolebinding'},
        'roleRef': {
            'apiGroup': 'rbac.authorization.k8s.io',
            'kind': 'ClusterRole',
            'name': 'capz-reader',
        },
        'subjects': subjects,
    }


class TestRbacSubjectNamespaceFallback(unittest.TestCase):
    """RBAC subject namespaces must be templated without raising."""

    def test_group_subject_without_namespace_gets_global_namespace(self):
        """A Group subject without a namespace must not abort the update."""
        with tempfile.TemporaryDirectory() as tmpdir:
            chart = _build_chart(tmpdir, {
                'rolebinding.yaml': _cluster_role_binding([
                    {
                        'apiGroup': 'rbac.authorization.k8s.io',
                        'kind': 'Group',
                        'name': 'system:serviceaccounts:capi-kubeadm-bootstrap-system',
                    },
                    {
                        'kind': 'ServiceAccount',
                        'name': 'capi-kubeadm-bootstrap-manager',
                        'namespace': 'system',
                    },
                ]),
            })
            os.environ.pop('ACM_RELEASE_VERSION', None)
            os.environ.pop('MCE_RELEASE_VERSION', None)

            generate_charts.update_helm_resources(
                'test-chart', chart, False, [], [], 'release-5.1',
            )

            with open(os.path.join(chart, 'templates', 'rolebinding.yaml')) as f:
                updated = yaml.safe_load(f)

            group, service_account = updated['subjects']
            self.assertEqual(group['namespace'], '{{ .Values.global.namespace }}')
            self.assertEqual(
                service_account['namespace'],
                '{{ default "system" .Values.global.namespace }}',
            )

    def test_empty_subjects_does_not_raise(self):
        """A binding with an empty subject list must still be written."""
        with tempfile.TemporaryDirectory() as tmpdir:
            chart = _build_chart(tmpdir, {
                'rolebinding.yaml': _cluster_role_binding([]),
            })
            os.environ.pop('ACM_RELEASE_VERSION', None)
            os.environ.pop('MCE_RELEASE_VERSION', None)

            generate_charts.update_helm_resources(
                'test-chart', chart, False, [], [], 'release-5.1',
            )

            with open(os.path.join(chart, 'templates', 'rolebinding.yaml')) as f:
                updated = yaml.safe_load(f)
            self.assertEqual(updated['subjects'], [])

    def test_namespace_does_not_leak_across_bindings(self):
        """Each binding falls back to the global namespace independently."""
        with tempfile.TemporaryDirectory() as tmpdir:
            chart = _build_chart(tmpdir, {
                'cluster-rolebinding.yaml': _cluster_role_binding([
                    {
                        'kind': 'ServiceAccount',
                        'name': 'first-sa',
                        'namespace': 'first-namespace',
                    },
                ]),
                'role-binding.yaml': {
                    'apiVersion': 'rbac.authorization.k8s.io/v1',
                    'kind': 'RoleBinding',
                    'metadata': {'name': 'second-rolebinding', 'namespace': 'PLACEHOLDER_NAMESPACE'},
                    'roleRef': {
                        'apiGroup': 'rbac.authorization.k8s.io',
                        'kind': 'Role',
                        'name': 'second-role',
                    },
                    'subjects': [
                        {
                            'apiGroup': 'rbac.authorization.k8s.io',
                            'kind': 'Group',
                            'name': 'second-group',
                        },
                    ],
                },
            })
            os.environ.pop('ACM_RELEASE_VERSION', None)
            os.environ.pop('MCE_RELEASE_VERSION', None)

            generate_charts.update_helm_resources(
                'test-chart', chart, False, [], [], 'release-5.1',
            )

            with open(os.path.join(chart, 'templates', 'role-binding.yaml')) as f:
                updated = yaml.safe_load(f)

            subject = updated['subjects'][0]
            self.assertEqual(subject['namespace'], '{{ .Values.global.namespace }}')
            self.assertNotIn('first-namespace', subject['namespace'])


if __name__ == '__main__':
    unittest.main()
