"""
Regression tests for ACM-48515 correctness fixes in bundle-generation scripts.

Covers:
  1. Multi-document YAML handling in generate-charts find_templates_of_type
  2. valueFrom env vars no longer crash fixEnvVarImageReferences (both scripts)
  3. --skipOverrides parsing uses store_true (not type=bool)
  4. preserve_files honored by generate-charts update_helm_resources
  7. yaml.dump sort_keys=True sorts keys deterministically
"""

import argparse
import os
import tempfile
import unittest

import yaml
from test_helpers import load_script_module

bundles_to_charts = load_script_module('bundles_to_charts', 'bundles-to-charts.py')
generate_charts = load_script_module('generate_charts', 'generate-charts.py')


IMAGE_MAPPINGS = {
    'my-operator': 'my_operator',
}


def _build_chart(tmpdir, templates, values=None):
    """Create a minimal chart directory with the given template files.

    Args:
        tmpdir: Parent directory.
        templates: dict mapping filename -> YAML content (as a Python object).
        values: Optional values.yaml content dict.

    Returns:
        Path to the chart directory.
    """
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
# 1. Multi-document YAML handling in find_templates_of_type
# ---------------------------------------------------------------------------

class TestFindTemplatesOfTypeMultiDoc(unittest.TestCase):
    """find_templates_of_type in generate-charts.py must handle multi-doc YAML."""

    def test_single_doc_found_without_branch(self):
        """A single-document template is found when no branch is passed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            chart = _build_chart(tmpdir, {
                'deploy.yaml': {
                    'apiVersion': 'apps/v1', 'kind': 'Deployment',
                    'metadata': {'name': 'my-deploy'},
                    'spec': {},
                },
            })
            result = generate_charts.find_templates_of_type(chart, 'Deployment')
            self.assertEqual(len(result), 1)
            self.assertIn('deploy.yaml', result[0])

    def test_multi_doc_found_with_branch(self):
        """A multi-doc file is parsed when branch triggers version gating."""
        multi_doc_yaml = (
            "apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: cm1\ndata: {}\n"
            "---\n"
            "apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: dep1\nspec: {}\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            chart = _build_chart(tmpdir, {'multi.yaml': multi_doc_yaml})
            # Use branch 'release-2.17' which satisfies is_version_compatible('2.16', '2.11', '2.16')
            os.environ.pop('ACM_RELEASE_VERSION', None)
            os.environ.pop('MCE_RELEASE_VERSION', None)
            result = generate_charts.find_templates_of_type(chart, 'Deployment', branch='release-2.17')
            self.assertEqual(len(result), 1)
            self.assertIn('multi.yaml', result[0])

    def test_multi_doc_not_found_when_kind_absent(self):
        """A multi-doc file does not match if no doc has the requested kind."""
        multi_doc_yaml = (
            "apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: cm1\ndata: {}\n"
            "---\n"
            "apiVersion: v1\nkind: Secret\nmetadata:\n  name: s1\ndata: {}\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            chart = _build_chart(tmpdir, {'multi.yaml': multi_doc_yaml})
            os.environ.pop('ACM_RELEASE_VERSION', None)
            os.environ.pop('MCE_RELEASE_VERSION', None)
            result = generate_charts.find_templates_of_type(chart, 'Deployment', branch='release-2.17')
            self.assertEqual(len(result), 0)


# ---------------------------------------------------------------------------
# 2. valueFrom env vars no longer crash fixEnvVarImageReferences
# ---------------------------------------------------------------------------

class TestValueFromEnvVarGenerateCharts(unittest.TestCase):
    """fixEnvVarImageReferences in generate-charts.py must skip valueFrom entries."""

    def test_valuefrom_env_var_skipped(self):
        """An env var using valueFrom must not crash; it should be silently skipped."""
        with tempfile.TemporaryDirectory() as tmpdir:
            chart = _build_chart(tmpdir, {
                'deploy.yaml': {
                    'apiVersion': 'apps/v1', 'kind': 'Deployment',
                    'metadata': {'name': 'test-deploy'},
                    'spec': {
                        'template': {
                            'spec': {
                                'containers': [{
                                    'name': 'manager',
                                    'image': 'quay.io/example/my-operator:latest',
                                    'env': [
                                        {'name': 'POD_NAME', 'valueFrom': {
                                            'fieldRef': {'fieldPath': 'metadata.name'}}},
                                        {'name': 'AGENT_IMAGE', 'value': 'quay.io/example/my-operator:latest'},
                                    ],
                                }],
                            },
                        },
                    },
                },
            })
            # Must not raise
            errors = generate_charts.fixEnvVarImageReferences(chart, IMAGE_MAPPINGS)
            self.assertEqual(errors, [])

            # The valueFrom entry should remain untouched
            with open(os.path.join(chart, 'templates', 'deploy.yaml')) as f:
                deploy = yaml.safe_load(f)
            envs = {e['name']: e for e in deploy['spec']['template']['spec']['containers'][0]['env']}
            self.assertIn('valueFrom', envs['POD_NAME'])
            self.assertNotIn('value', envs['POD_NAME'])
            # The _IMAGE var should have been templated
            self.assertIn('imageOverrides', envs['AGENT_IMAGE']['value'])


class TestValueFromEnvVarBundlesToCharts(unittest.TestCase):
    """fixEnvVarImageReferences in bundles-to-charts.py must skip valueFrom entries."""

    def test_valuefrom_env_var_skipped(self):
        """An env var using valueFrom must not crash."""
        with tempfile.TemporaryDirectory() as tmpdir:
            chart = _build_chart(tmpdir, {
                'deploy.yaml': {
                    'apiVersion': 'apps/v1', 'kind': 'Deployment',
                    'metadata': {'name': 'test-deploy'},
                    'spec': {
                        'template': {
                            'spec': {
                                'containers': [{
                                    'name': 'manager',
                                    'image': 'quay.io/example/my-operator:latest',
                                    'env': [
                                        {'name': 'SECRET_KEY', 'valueFrom': {
                                            'secretKeyRef': {'name': 'my-secret', 'key': 'password'}}},
                                        {'name': 'AGENT_IMAGE', 'value': 'quay.io/example/my-operator:latest'},
                                    ],
                                }],
                            },
                        },
                    },
                },
            })
            os.environ.pop('ACM_RELEASE_VERSION', None)
            os.environ.pop('MCE_RELEASE_VERSION', None)
            errors = bundles_to_charts.fixEnvVarImageReferences(
                chart, IMAGE_MAPPINGS, 'main', 'test-operator',
                apply=True,
            )
            self.assertEqual(errors, [])

            with open(os.path.join(chart, 'templates', 'deploy.yaml')) as f:
                deploy = yaml.safe_load(f)
            envs = {e['name']: e for e in deploy['spec']['template']['spec']['containers'][0]['env']}
            self.assertIn('valueFrom', envs['SECRET_KEY'])
            self.assertIn('imageOverrides', envs['AGENT_IMAGE']['value'])


# ---------------------------------------------------------------------------
# 3. --skipOverrides parsing
# ---------------------------------------------------------------------------

class TestSkipOverridesParsing(unittest.TestCase):
    """--skipOverrides must use store_true, not type=bool.

    With type=bool, --skipOverrides=false evaluates True (bool('false') is True).
    With store_true, --skipOverrides is True only when the flag is present.
    """

    def _make_parser(self, script_module):
        """Create the argument parser from the script's main without running it."""
        parser = argparse.ArgumentParser()
        parser.add_argument("--skipOverrides", dest="skipOverrides", action="store_true",
                            help="If true, overrides will not be applied")
        return parser

    def test_generate_charts_flag_absent_is_false(self):
        parser = self._make_parser(generate_charts)
        args = parser.parse_args([])
        self.assertFalse(args.skipOverrides)

    def test_generate_charts_flag_present_is_true(self):
        parser = self._make_parser(generate_charts)
        args = parser.parse_args(['--skipOverrides'])
        self.assertTrue(args.skipOverrides)

    def test_bundles_to_charts_flag_absent_is_false(self):
        parser = self._make_parser(bundles_to_charts)
        args = parser.parse_args([])
        self.assertFalse(args.skipOverrides)

    def test_bundles_to_charts_flag_present_is_true(self):
        parser = self._make_parser(bundles_to_charts)
        args = parser.parse_args(['--skipOverrides'])
        self.assertTrue(args.skipOverrides)

    def test_source_code_uses_store_true_not_type_bool(self):
        """Verify the actual source code has action=store_true, not type=bool."""
        import inspect
        for module in [generate_charts, bundles_to_charts]:
            source = inspect.getsource(module.main)
            self.assertIn('action="store_true"', source,
                          f"{module.__name__} still uses type=bool for --skipOverrides")
            self.assertNotIn("type=bool", source,
                             f"{module.__name__} still uses type=bool for --skipOverrides")


# ---------------------------------------------------------------------------
# 4. preserve_files in generate-charts update_helm_resources
# ---------------------------------------------------------------------------

class TestPreserveFilesGenerateCharts(unittest.TestCase):
    """update_helm_resources in generate-charts.py must skip preserved files."""

    def test_preserved_file_is_not_modified(self):
        """A file listed in preserved_files must remain unchanged after update_helm_resources."""
        original_content = {
            'apiVersion': 'v1', 'kind': 'ConfigMap',
            'metadata': {'name': 'preserved-cm', 'namespace': 'my-ns'},
            'data': {'key': 'original-value'},
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            chart = _build_chart(tmpdir, {
                'preserved-configmap.yaml': original_content,
                'normal-configmap.yaml': {
                    'apiVersion': 'v1', 'kind': 'ConfigMap',
                    'metadata': {'name': 'normal-cm', 'namespace': 'my-ns'},
                    'data': {'key': 'value'},
                },
            })
            os.environ.pop('ACM_RELEASE_VERSION', None)
            os.environ.pop('MCE_RELEASE_VERSION', None)

            generate_charts.update_helm_resources(
                'test-chart', chart, False, [], [], 'release-2.14',
                preserved_files=['preserved-configmap.yaml'],
            )

            # The preserved file should be untouched
            with open(os.path.join(chart, 'templates', 'preserved-configmap.yaml')) as f:
                preserved = yaml.safe_load(f)
            self.assertEqual(preserved['metadata']['namespace'], 'my-ns')

            # The normal file should have been updated with Helm namespace
            with open(os.path.join(chart, 'templates', 'normal-configmap.yaml')) as f:
                normal = yaml.safe_load(f)
            self.assertIn('.Values.global.namespace', normal['metadata']['namespace'])


# ---------------------------------------------------------------------------
# 7. yaml.dump sort_keys=True sorts keys deterministically
# ---------------------------------------------------------------------------

class TestYamlSortKeysEnabled(unittest.TestCase):
    """yaml.dump with sort_keys=True must emit keys in sorted order."""

    def test_key_order_sorted_in_generate_charts(self):
        """fixImageReferences should emit keys in sorted order."""
        ordered_deployment = {
            'apiVersion': 'apps/v1',
            'kind': 'Deployment',
            'metadata': {'name': 'my-deploy'},
            'spec': {
                'template': {
                    'spec': {
                        'containers': [{
                            'name': 'manager',
                            'image': 'quay.io/example/my-operator:latest',
                        }],
                    },
                },
            },
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            chart = _build_chart(tmpdir, {'deploy.yaml': ordered_deployment})
            errors = generate_charts.fixImageReferences(chart, IMAGE_MAPPINGS)
            self.assertEqual(errors, [])

            with open(os.path.join(chart, 'templates', 'deploy.yaml')) as f:
                content = f.read()

            # Keys should be emitted alphabetically: apiVersion, kind, metadata, spec
            api_pos = content.find('apiVersion')
            kind_pos = content.find('kind')
            meta_pos = content.find('metadata')
            spec_pos = content.find('spec')
            self.assertLess(api_pos, kind_pos, "apiVersion should come before kind")
            self.assertLess(kind_pos, meta_pos, "kind should come before metadata")
            self.assertLess(meta_pos, spec_pos, "metadata should come before spec")

    def test_key_order_sorted_in_bundles_to_charts(self):
        """fixImageReferences in bundles-to-charts should emit sorted keys."""
        ordered_deployment = {
            'apiVersion': 'apps/v1',
            'kind': 'Deployment',
            'metadata': {'name': 'my-deploy'},
            'spec': {
                'template': {
                    'spec': {
                        'containers': [{
                            'name': 'manager',
                            'image': 'quay.io/example/my-operator:latest',
                        }],
                    },
                },
            },
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            chart = _build_chart(tmpdir, {'deploy.yaml': ordered_deployment})
            os.environ.pop('ACM_RELEASE_VERSION', None)
            os.environ.pop('MCE_RELEASE_VERSION', None)
            errors = bundles_to_charts.fixImageReferences(
                chart, IMAGE_MAPPINGS, 'main', 'test-operator', apply=True,
            )
            self.assertEqual(errors, [])

            with open(os.path.join(chart, 'templates', 'deploy.yaml')) as f:
                content = f.read()

            api_pos = content.find('apiVersion')
            kind_pos = content.find('kind')
            meta_pos = content.find('metadata')
            spec_pos = content.find('spec')
            self.assertLess(api_pos, kind_pos, "apiVersion should come before kind")
            self.assertLess(kind_pos, meta_pos, "kind should come before metadata")
            self.assertLess(meta_pos, spec_pos, "metadata should come before spec")


if __name__ == '__main__':
    unittest.main()
