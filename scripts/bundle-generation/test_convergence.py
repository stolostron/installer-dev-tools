"""
Regression tests for ACM-48518 convergence of divergent logic.

Verifies that both scripts now share a single implementation from
chart_utils for:
  1. resource_kinds / namespace_scoped_kinds tables
  2. find_templates_of_type (branch, multi-doc, version gating)
  3. injectHelmFlowControl (sizes.yaml, env detection, write-once)
  4. Image reference rewriting (image:, env.value, AddOnTemplate)
"""

import inspect
import os
import tempfile
import unittest

import chart_utils
import yaml
from test_helpers import load_script_module

bundles_to_charts = load_script_module('bundles_to_charts', 'bundles-to-charts.py')
generate_charts = load_script_module('generate_charts', 'generate-charts.py')


IMAGE_MAPPINGS = {
    'my-operator': 'my_operator',
    'sidecar': 'sidecar_img',
}


def _build_chart(tmpdir, templates, values=None):
    chart = os.path.join(tmpdir, 'test-chart')
    tpl_dir = os.path.join(chart, 'templates')
    os.makedirs(tpl_dir)
    for filename, content in templates.items():
        with open(os.path.join(tpl_dir, filename), 'w') as f:
            if isinstance(content, str):
                f.write(content)
            else:
                yaml.dump(content, f, sort_keys=False)
    if values is None:
        values = {'global': {'imageOverrides': {}, 'pullPolicy': 'IfNotPresent'}}
    with open(os.path.join(chart, 'values.yaml'), 'w') as f:
        yaml.dump(values, f, sort_keys=False)
    with open(os.path.join(chart, 'Chart.yaml'), 'w') as f:
        yaml.dump({'apiVersion': 'v2', 'name': 'test-chart', 'version': '0.0.1'}, f, sort_keys=False)
    return chart


# ---------------------------------------------------------------------------
# 1. resource_kinds / namespace_scoped_kinds defined once
# ---------------------------------------------------------------------------

class TestUnifiedResourceKindsTables(unittest.TestCase):
    """Both scripts must use the same resource_kinds / namespace_scoped_kinds from chart_utils."""

    def test_chart_utils_is_the_source(self):
        """The canonical tables live in chart_utils, not duplicated in each script."""
        self.assertIsNotNone(chart_utils.RESOURCE_KINDS)
        self.assertIsNotNone(chart_utils.NAMESPACE_SCOPED_KINDS)

    def test_generate_charts_uses_chart_utils_kinds(self):
        """generate-charts.py imports from chart_utils, not a local copy."""
        # The import statement binds the name; check the object identity
        self.assertIs(generate_charts.RESOURCE_KINDS, chart_utils.RESOURCE_KINDS)
        self.assertIs(generate_charts.NAMESPACE_SCOPED_KINDS, chart_utils.NAMESPACE_SCOPED_KINDS)

    def test_bundles_to_charts_uses_chart_utils_kinds(self):
        """bundles-to-charts.py imports from chart_utils, not a local copy."""
        self.assertIs(bundles_to_charts.RESOURCE_KINDS, chart_utils.RESOURCE_KINDS)
        self.assertIs(bundles_to_charts.NAMESPACE_SCOPED_KINDS, chart_utils.NAMESPACE_SCOPED_KINDS)

    def test_resource_kinds_includes_full_superset(self):
        """The unified list includes all kinds from both old scripts."""
        expected_from_generate = {
            "AddOnTemplate", "Certificate", "ClusterManagementAddOn", "Issuer",
            "ManagedClusterSetBinding", "MulticlusterRoleAssignment",
            "Placement", "PodDisruptionBudget",
        }
        expected_from_bundles = {
            "ClusterRole", "ClusterRoleBinding", "ConfigMap", "Deployment",
            "MutatingWebhookConfiguration", "NetworkPolicy",
            "PersistentVolumeClaim", "Role", "RoleBinding", "Route",
            "Secret", "Service", "StatefulSet",
            "ValidatingWebhookConfiguration", "VerticalPodAutoscaler",
            "Job", "ConsolePlugin",
        }
        all_kinds = set(chart_utils.RESOURCE_KINDS)
        self.assertTrue(expected_from_generate.issubset(all_kinds))
        self.assertTrue(expected_from_bundles.issubset(all_kinds))


# ---------------------------------------------------------------------------
# 2. find_templates_of_type is the same function
# ---------------------------------------------------------------------------

class TestUnifiedFindTemplates(unittest.TestCase):
    """Both scripts use the exact same find_templates_of_type."""

    def test_same_function_object(self):
        self.assertIs(
            generate_charts.find_templates_of_type,
            bundles_to_charts.find_templates_of_type,
        )
        self.assertIs(
            generate_charts.find_templates_of_type,
            chart_utils.find_templates_of_type,
        )


# ---------------------------------------------------------------------------
# 3. injectHelmFlowControl converged
# ---------------------------------------------------------------------------

class TestUnifiedInjectHelmFlowControl(unittest.TestCase):
    """Both scripts use the same inject_helm_flow_control from chart_utils."""

    def test_same_function_object(self):
        self.assertIs(
            generate_charts.injectHelmFlowControl,
            chart_utils.inject_helm_flow_control,
        )
        self.assertIs(
            bundles_to_charts.injectHelmFlowControl,
            chart_utils.inject_helm_flow_control,
        )

    def test_writes_file_once(self):
        """inject_helm_flow_control should write the file only once (after the loop)."""
        source = inspect.getsource(chart_utils.inject_helm_flow_control)
        # Count file write operations (both with and without context manager)
        write_count = source.count("open(deployment, 'w'") + source.count('open(deployment, "w"')
        self.assertEqual(write_count, 1, "inject_helm_flow_control should write exactly once")

    def test_sizes_yaml_injection_supported(self):
        """The unified function accepts a sizes parameter."""
        sig = inspect.signature(chart_utils.inject_helm_flow_control)
        self.assertIn('sizes', sig.parameters)

    def test_env_detection_includes_dash_env(self):
        """The unified function detects '- env:' (from generate-charts)."""
        source = inspect.getsource(chart_utils.inject_helm_flow_control)
        self.assertIn('"- env:"', source)


# ---------------------------------------------------------------------------
# 4. Unified image-reference rewriting
# ---------------------------------------------------------------------------

class TestUnifiedImageRewriting(unittest.TestCase):
    """Image reference functions are shared between both scripts."""

    def test_fix_image_references_is_shared(self):
        self.assertIs(
            generate_charts.fixImageReferences,
            bundles_to_charts.fixImageReferences,
        )

    def test_fix_env_var_image_references_is_shared(self):
        self.assertIs(
            generate_charts.fixEnvVarImageReferences,
            bundles_to_charts.fixEnvVarImageReferences,
        )

    def test_fix_addon_template_image_references_is_shared(self):
        self.assertIs(
            generate_charts.fixImageReferencesForAddonTemplate,
            bundles_to_charts.fixImageReferencesForAddonTemplate,
        )

    def test_image_field_rewriting(self):
        """fix_image_references rewrites container image: fields."""
        with tempfile.TemporaryDirectory() as tmpdir:
            chart = _build_chart(tmpdir, {
                'deploy.yaml': {
                    'apiVersion': 'apps/v1', 'kind': 'Deployment',
                    'metadata': {'name': 'test'},
                    'spec': {
                        'template': {
                            'spec': {
                                'containers': [{
                                    'name': 'mgr',
                                    'image': 'quay.io/example/my-operator:v1',
                                }],
                            },
                        },
                    },
                },
            })
            errors = chart_utils.fix_image_references(chart, IMAGE_MAPPINGS)
            self.assertEqual(errors, [])
            with open(os.path.join(chart, 'templates', 'deploy.yaml')) as f:
                dep = yaml.safe_load(f)
            img = dep['spec']['template']['spec']['containers'][0]['image']
            self.assertIn('imageOverrides.my_operator', img)

    def test_env_value_rewriting(self):
        """fix_env_var_image_references rewrites env[*].value fields."""
        with tempfile.TemporaryDirectory() as tmpdir:
            chart = _build_chart(tmpdir, {
                'deploy.yaml': {
                    'apiVersion': 'apps/v1', 'kind': 'Deployment',
                    'metadata': {'name': 'test'},
                    'spec': {
                        'template': {
                            'spec': {
                                'containers': [{
                                    'name': 'mgr',
                                    'image': 'quay.io/example/my-operator:v1',
                                    'env': [
                                        {'name': 'SIDECAR_IMAGE', 'value': 'quay.io/example/sidecar:v1'},
                                    ],
                                }],
                            },
                        },
                    },
                },
            })
            errors = chart_utils.fix_env_var_image_references(chart, IMAGE_MAPPINGS)
            self.assertEqual(errors, [])
            with open(os.path.join(chart, 'templates', 'deploy.yaml')) as f:
                dep = yaml.safe_load(f)
            env_val = dep['spec']['template']['spec']['containers'][0]['env'][0]['value']
            self.assertIn('imageOverrides.sidecar_img', env_val)

    def test_addon_template_rewriting(self):
        """fix_addon_template_image_references handles AddOnTemplate manifests."""
        addon = {
            'apiVersion': 'addons.open-cluster-management.io/v1alpha1',
            'kind': 'AddOnTemplate',
            'metadata': {'name': 'test-addon'},
            'spec': {
                'agentSpec': {
                    'workload': {
                        'manifests': [{
                            'kind': 'Deployment',
                            'metadata': {'name': 'inner'},
                            'spec': {
                                'template': {
                                    'spec': {
                                        'containers': [{
                                            'name': 'mgr',
                                            'image': 'quay.io/example/my-operator:v1',
                                        }],
                                    },
                                },
                            },
                        }],
                    },
                },
            },
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            chart = _build_chart(tmpdir, {'addon.yaml': addon})
            errors = chart_utils.fix_addon_template_image_references(chart, IMAGE_MAPPINGS)
            self.assertEqual(errors, [])
            with open(os.path.join(chart, 'templates', 'addon.yaml')) as f:
                content = yaml.safe_load(f)
            inner_img = (
                content['spec']['agentSpec']['workload']['manifests'][0]
                ['spec']['template']['spec']['containers'][0]['image']
            )
            self.assertIn('imageOverrides.my_operator', inner_img)


# ---------------------------------------------------------------------------
# CodeRabbit review fixes
# ---------------------------------------------------------------------------

class TestParseImageRefRegistryPort(unittest.TestCase):
    """parse_image_ref must not treat a registry port colon as a tag separator."""

    def test_registry_with_port(self):
        """registry:5000/my-operator:v1.2 should parse tag=v1.2, not tag=5000/my-operator:v1.2."""
        ref = chart_utils.parse_image_ref("registry:5000/my-operator:v1.2")
        self.assertEqual(ref["tag"], "v1.2")
        self.assertEqual(ref["repository"], "my-operator")

    def test_registry_with_port_no_tag(self):
        """registry:5000/my-operator should have no tag, repository=my-operator."""
        ref = chart_utils.parse_image_ref("registry:5000/my-operator")
        self.assertIsNone(ref["tag"])
        self.assertEqual(ref["repository"], "my-operator")

    def test_simple_image_still_works(self):
        """quay.io/example/my-operator:latest should still parse correctly."""
        ref = chart_utils.parse_image_ref("quay.io/example/my-operator:latest")
        self.assertEqual(ref["tag"], "latest")
        self.assertEqual(ref["repository"], "my-operator")


class TestEnvListMarkerPreserved(unittest.TestCase):
    """inject_helm_flow_control must preserve the YAML '- ' list marker for env-first containers."""

    def test_dash_env_prefix_preserved(self):
        """A line '        - env:' must keep the '- ' prefix after injection."""
        with tempfile.TemporaryDirectory() as tmpdir:
            deploy_path = os.path.join(tmpdir, "deployment.yaml")
            # Simulate a deployment YAML where env is the first field of a container
            with open(deploy_path, 'w') as f:
                f.write(
                    "spec:\n"
                    "  template:\n"
                    "    spec:\n"
                    "      containers:\n"
                    "        - env:\n"
                    "          - name: FOO\n"
                    "            value: bar\n"
                )
            chart_utils.inject_helm_flow_control(deploy_path, "main")

            with open(deploy_path) as f:
                content = f.read()

            # The output must contain '- env:' with the list marker preserved
            self.assertIn("- env:", content)
            # And must NOT have a bare 'env:' without the list marker at that indent
            for output_line in content.splitlines():
                if "env:" in output_line and "proxyConfigs" not in output_line:
                    if output_line.strip().startswith("env:") or output_line.strip() == "env:":
                        # This is a plain env: without list marker — that's only OK
                        # if the original didn't have one. Since our input had "- env:",
                        # we should find "- env:" not bare "env:"
                        self.fail(
                            f"Expected '- env:' with list marker but got bare: {output_line!r}"
                        )
                    break


if __name__ == '__main__':
    unittest.main()
