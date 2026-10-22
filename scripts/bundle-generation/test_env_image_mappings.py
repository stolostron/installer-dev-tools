#!/usr/bin/env python3
"""
Unit tests for explicit env var image mappings (envImageMappings) in
bundles-to-charts.py and generate-charts.py.
"""

import importlib.util
import os
import sys
import tempfile
import types
import unittest

import yaml


def _load_module(name, filename):
    """Loads a generator script as a module.

    Both scripts do `from validate_csv import *`, but `validate_csv` is
    provided by the *consumer* repo at runtime via PYTHONPATH. Stub it out
    here so the modules under test can be imported standalone.
    """
    if 'validate_csv' not in sys.modules:
        stub = types.ModuleType('validate_csv')
        stub.validateCSV = lambda csvPath: []
        stub.validateFieldMapping = lambda csv, ruleType, fieldMap: []
        sys.modules['validate_csv'] = stub

    module_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), filename)
    spec = importlib.util.spec_from_file_location(name, module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bundles_to_charts = _load_module('bundles_to_charts', 'bundles-to-charts.py')
generate_charts = _load_module('generate_charts', 'generate-charts.py')


IMAGE_MAPPINGS = {
    'assisted-service': 'assisted_service_9',
    'postgresql-15-c9s': 'postgresql_15',
    'postgresql-16-c9s': 'postgresql_16',
}


def build_chart(tmpdir, env_vars):
    """Creates a minimal chart with one Deployment carrying the env vars."""
    chart = os.path.join(tmpdir, 'assisted-service')
    templates = os.path.join(chart, 'templates')
    os.makedirs(templates)

    with open(os.path.join(chart, 'Chart.yaml'), 'w') as f:
        yaml.dump({'apiVersion': 'v2', 'name': 'assisted-service', 'version': '0.0.1'}, f)

    with open(os.path.join(chart, 'values.yaml'), 'w') as f:
        yaml.dump({'global': {'imageOverrides': {}, 'pullPolicy': 'IfNotPresent'}}, f)

    deployment = {
        'apiVersion': 'apps/v1',
        'kind': 'Deployment',
        'metadata': {'name': 'infrastructure-operator'},
        'spec': {
            'template': {
                'spec': {
                    'containers': [{
                        'name': 'manager',
                        'image': 'quay.io/example/operator:latest',
                        'env': env_vars,
                    }],
                },
            },
        },
    }
    with open(os.path.join(templates, 'deployment.yaml'), 'w') as f:
        yaml.dump(deployment, f)
    return chart


def read_chart(chart):
    """Returns (env vars by name, imageOverrides map)."""
    with open(os.path.join(chart, 'templates', 'deployment.yaml')) as f:
        deployment = yaml.safe_load(f)
    env = {e['name']: e['value'] for e in deployment['spec']['template']['spec']['containers'][0]['env']}
    with open(os.path.join(chart, 'values.yaml')) as f:
        values = yaml.safe_load(f)
    return env, values['global']['imageOverrides']


class TestBundlesToChartsEnvImageMappings(unittest.TestCase):

    def run_fix(self, env_vars, env_image_mappings=None, apply=True):
        with tempfile.TemporaryDirectory() as tmpdir:
            chart = build_chart(tmpdir, env_vars)
            errors = bundles_to_charts.fixEnvVarImageReferences(
                chart, IMAGE_MAPPINGS, 'main', 'assisted-service',
                apply=apply, envImageMappings=env_image_mappings,
            )
            return errors, read_chart(chart)

    def test_explicit_mapping_is_templated(self):
        errors, (env, overrides) = self.run_fix(
            [{'name': 'DATABASE_IMAGE_PG15', 'value': 'quay.io/sclorg/postgresql-15-c9s:latest'}],
            {'DATABASE_IMAGE_PG15': 'postgresql_15'},
        )
        self.assertEqual(errors, [])
        self.assertEqual(env['DATABASE_IMAGE_PG15'], '{{ .Values.global.imageOverrides.postgresql_15 }}')
        self.assertEqual(overrides['postgresql_15'], '')

    def test_image_suffix_fallback_still_works(self):
        errors, (env, overrides) = self.run_fix(
            [{'name': 'DATABASE_IMAGE', 'value': 'quay.io/sclorg/postgresql-16-c9s:latest'}],
        )
        self.assertEqual(errors, [])
        self.assertEqual(env['DATABASE_IMAGE'], '{{ .Values.global.imageOverrides.postgresql_16 }}')
        self.assertEqual(overrides['postgresql_16'], '')

    def test_unknown_explicit_key_is_an_error(self):
        errors, (env, overrides) = self.run_fix(
            [{'name': 'DATABASE_IMAGE_PG15', 'value': 'quay.io/sclorg/postgresql-15-c9s:latest'}],
            {'DATABASE_IMAGE_PG15': 'postgresql_99'},
        )
        self.assertEqual(len(errors), 1)
        self.assertIn('postgresql_99', errors[0])
        self.assertEqual(env['DATABASE_IMAGE_PG15'], 'quay.io/sclorg/postgresql-15-c9s:latest')
        self.assertEqual(overrides, {})

    def test_explicit_mapping_wins_over_repository_mapping(self):
        errors, (env, overrides) = self.run_fix(
            [{'name': 'DATABASE_IMAGE_PG15', 'value': 'quay.io/sclorg/postgresql-15-c9s:latest'}],
            {'DATABASE_IMAGE_PG15': 'assisted_service_9'},
        )
        self.assertEqual(errors, [])
        self.assertEqual(env['DATABASE_IMAGE_PG15'], '{{ .Values.global.imageOverrides.assisted_service_9 }}')
        self.assertEqual(overrides['assisted_service_9'], '')

    def test_undeclared_image_like_env_var_is_untouched(self):
        errors, (env, overrides) = self.run_fix(
            [{'name': 'DATABASE_IMAGE_PG15', 'value': 'quay.io/sclorg/postgresql-15-c9s:latest'}],
        )
        self.assertEqual(errors, [])
        self.assertEqual(env['DATABASE_IMAGE_PG15'], 'quay.io/sclorg/postgresql-15-c9s:latest')
        self.assertEqual(overrides, {})

    def test_validate_only_reports_errors_without_writing(self):
        errors, (env, overrides) = self.run_fix(
            [{'name': 'DATABASE_IMAGE_PG15', 'value': 'quay.io/sclorg/postgresql-15-c9s:latest'}],
            {'DATABASE_IMAGE_PG15': 'postgresql_99'},
            apply=False,
        )
        self.assertEqual(len(errors), 1)
        self.assertEqual(env['DATABASE_IMAGE_PG15'], 'quay.io/sclorg/postgresql-15-c9s:latest')
        self.assertEqual(overrides, {})


class TestGenerateChartsEnvImageMappings(unittest.TestCase):

    def run_fix(self, env_vars, env_image_mappings=None):
        with tempfile.TemporaryDirectory() as tmpdir:
            chart = build_chart(tmpdir, env_vars)
            generate_charts.fixEnvVarImageReferences(chart, IMAGE_MAPPINGS, env_image_mappings)
            return read_chart(chart)

    def test_explicit_mapping_is_templated(self):
        env, overrides = self.run_fix(
            [{'name': 'DATABASE_IMAGE_PG15', 'value': 'quay.io/sclorg/postgresql-15-c9s:latest'}],
            {'DATABASE_IMAGE_PG15': 'postgresql_15'},
        )
        self.assertEqual(env['DATABASE_IMAGE_PG15'], '{{ .Values.global.imageOverrides.postgresql_15 }}')
        self.assertEqual(overrides['postgresql_15'], '')

    def test_image_suffix_fallback_still_works(self):
        env, overrides = self.run_fix(
            [{'name': 'DATABASE_IMAGE', 'value': 'quay.io/sclorg/postgresql-16-c9s:latest'}],
        )
        self.assertEqual(env['DATABASE_IMAGE'], '{{ .Values.global.imageOverrides.postgresql_16 }}')
        self.assertEqual(overrides['postgresql_16'], '')

    def test_unknown_explicit_key_exits(self):
        with self.assertRaises(SystemExit):
            self.run_fix(
                [{'name': 'DATABASE_IMAGE_PG15', 'value': 'quay.io/sclorg/postgresql-15-c9s:latest'}],
                {'DATABASE_IMAGE_PG15': 'postgresql_99'},
            )

    def test_undeclared_image_like_env_var_is_untouched(self):
        env, overrides = self.run_fix(
            [{'name': 'DATABASE_IMAGE_PG15', 'value': 'quay.io/sclorg/postgresql-15-c9s:latest'}],
        )
        self.assertEqual(env['DATABASE_IMAGE_PG15'], 'quay.io/sclorg/postgresql-15-c9s:latest')
        self.assertEqual(overrides, {})


if __name__ == '__main__':
    unittest.main()
