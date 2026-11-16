"""
Regression tests for ClusterManagementAddOn namespace templating.

A ClusterManagementAddOn may reference add-on resources through the flat
``spec.defaultConfigs`` list (for example an AddOnDeploymentConfig). The chart
is rendered from the upstream repository before it is copied into the consumer
repo, so a hardcoded namespace in that list used to be written back verbatim and
would not follow a custom install namespace. The generator must wrap it as
``{{ default "<chart value>" .Values.global.namespace }}`` so the override works
while releases that do not supply ``global.namespace`` keep the chart's value.
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


def _cluster_management_addon(default_configs=None, install_strategy=None):
    """Build a minimal ClusterManagementAddOn with the given spec fragments."""
    spec = {'addOnMeta': {'description': 'Test add-on', 'displayName': 'Test add-on'}}
    if default_configs is not None:
        spec['defaultConfigs'] = default_configs
    if install_strategy is not None:
        spec['installStrategy'] = install_strategy
    return {
        'apiVersion': 'addon.open-cluster-management.io/v1beta1',
        'kind': 'ClusterManagementAddOn',
        'metadata': {
            'name': 'test-addon',
            'annotations': {'addon.open-cluster-management.io/lifecycle': 'addon-manager'},
        },
        'spec': spec,
    }


DEFAULT_NAMESPACE = '{{ .Values.global.namespace }}'


class TestClusterManagementAddOnDefaultConfigs(unittest.TestCase):
    """spec.defaultConfigs namespace references must be templated."""

    def test_default_config_namespace_uses_chart_value_as_default(self):
        """The chart's namespace becomes the Helm default, not a hardcoded one."""
        resource = _cluster_management_addon(default_configs=[
            {
                'group': 'addon.open-cluster-management.io',
                'name': 'test-addon',
                'resource': 'addontemplates',
            },
            {
                'group': 'addon.open-cluster-management.io',
                'name': 'test-addon-template-values',
                'namespace': 'open-cluster-management',
                'resource': 'addondeploymentconfigs',
            },
        ])

        generate_charts.ensure_clustermanagementaddon_namespace(
            resource, 'test-addon', DEFAULT_NAMESPACE,
        )

        addon_template, deployment_config = resource['spec']['defaultConfigs']
        self.assertNotIn('namespace', addon_template)
        self.assertEqual(
            deployment_config['namespace'],
            '{{ default "open-cluster-management" .Values.global.namespace }}',
        )

    def test_non_default_chart_namespace_is_used_as_the_default(self):
        """A chart that declares its own namespace keeps it as the fallback."""
        resource = _cluster_management_addon(default_configs=[
            {
                'group': 'addon.open-cluster-management.io',
                'name': 'test-addon-template-values',
                'namespace': 'custom-hub-namespace',
                'resource': 'addondeploymentconfigs',
            },
        ])

        generate_charts.ensure_clustermanagementaddon_namespace(
            resource, 'test-addon', DEFAULT_NAMESPACE,
        )

        self.assertEqual(
            resource['spec']['defaultConfigs'][0]['namespace'],
            '{{ default "custom-hub-namespace" .Values.global.namespace }}',
        )

    def test_default_config_without_namespace_does_not_raise(self):
        """An entry without a namespace is skipped instead of failing."""
        resource = _cluster_management_addon(default_configs=[
            {
                'group': 'addon.open-cluster-management.io',
                'name': 'test-addon',
                'resource': 'addontemplates',
            },
        ])

        generate_charts.ensure_clustermanagementaddon_namespace(
            resource, 'test-addon', DEFAULT_NAMESPACE,
        )

        self.assertNotIn('namespace', resource['spec']['defaultConfigs'][0])

    def test_already_templated_namespace_is_not_re_wrapped(self):
        """Re-running the generator must not nest Helm expressions."""
        existing = '{{ default "open-cluster-management" .Values.global.namespace }}'
        resource = _cluster_management_addon(default_configs=[
            {
                'group': 'addon.open-cluster-management.io',
                'name': 'test-addon-template-values',
                'namespace': existing,
                'resource': 'addondeploymentconfigs',
            },
        ])

        generate_charts.ensure_clustermanagementaddon_namespace(
            resource, 'test-addon', DEFAULT_NAMESPACE,
        )

        self.assertEqual(resource['spec']['defaultConfigs'][0]['namespace'], existing)

    def test_missing_install_strategy_does_not_raise(self):
        """A ClusterManagementAddOn without installStrategy must still be updated."""
        resource = _cluster_management_addon(default_configs=[
            {
                'group': 'addon.open-cluster-management.io',
                'name': 'test-addon-template-values',
                'namespace': 'open-cluster-management',
                'resource': 'addondeploymentconfigs',
            },
        ])

        generate_charts.ensure_clustermanagementaddon_namespace(
            resource, 'test-addon', DEFAULT_NAMESPACE,
        )

        self.assertEqual(
            resource['spec']['defaultConfigs'][0]['namespace'],
            '{{ default "open-cluster-management" .Values.global.namespace }}',
        )

    def test_placement_namespace_still_templated_with_default_fallback(self):
        """Existing installStrategy.placements handling must not regress."""
        resource = _cluster_management_addon(install_strategy={
            'type': 'Placements',
            'placements': [{'name': 'test-placement', 'namespace': 'open-cluster-management'}],
        })

        generate_charts.ensure_clustermanagementaddon_namespace(
            resource, 'test-addon', DEFAULT_NAMESPACE,
        )

        self.assertEqual(
            resource['spec']['installStrategy']['placements'][0]['namespace'],
            '{{ default "open-cluster-management" .Values.global.namespace }}',
        )


class TestClusterManagementAddOnThroughUpdateHelmResources(unittest.TestCase):
    """End-to-end: the written chart template keeps the namespace templated."""

    def test_written_template_templates_default_configs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            chart = _build_chart(tmpdir, {
                'clustermanagementaddon.yaml': _cluster_management_addon(
                    default_configs=[
                        {
                            'group': 'addon.open-cluster-management.io',
                            'name': 'test-addon-template-values',
                            'namespace': 'open-cluster-management',
                            'resource': 'addondeploymentconfigs',
                        },
                    ],
                    install_strategy={
                        'type': 'Placements',
                        'placements': [
                            {'name': 'test-placement', 'namespace': 'open-cluster-management'},
                        ],
                    },
                ),
            })
            os.environ.pop('ACM_RELEASE_VERSION', None)
            os.environ.pop('MCE_RELEASE_VERSION', None)

            generate_charts.update_helm_resources(
                'test-chart', chart, False, [], [], 'release-5.1',
            )

            with open(os.path.join(chart, 'templates', 'clustermanagementaddon.yaml')) as f:
                updated = yaml.safe_load(f)

            self.assertEqual(
                updated['spec']['defaultConfigs'][0]['namespace'],
                '{{ default "open-cluster-management" .Values.global.namespace }}',
            )
            self.assertEqual(
                updated['spec']['installStrategy']['placements'][0]['namespace'],
                '{{ default "open-cluster-management" .Values.global.namespace }}',
            )


if __name__ == '__main__':
    unittest.main()
