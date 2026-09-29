#!/usr/bin/env python3
"""
Unit tests for the OperatorPolicy subscription value templating in generate-charts.py.
"""

import importlib.util
import os
import sys
import tempfile
import types
import unittest

import yaml


def _load_generate_charts():
    """Loads generate-charts.py as a module.

    generate-charts.py does `from validate_csv import *`, but `validate_csv`
    is a module provided by the *consumer* repo (e.g.
    multiclusterhub-operator/hack/bundle-automation/validate_csv.py) at runtime
    via PYTHONPATH, not something that lives in this repo. Stub it out here so
    the module under test can be imported standalone.
    """
    if 'validate_csv' not in sys.modules:
        stub = types.ModuleType('validate_csv')
        stub.validateCSV = lambda csvPath: []
        stub.validateFieldMapping = lambda csv, ruleType, fieldMap: []
        sys.modules['validate_csv'] = stub

    module_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'generate-charts.py')
    spec = importlib.util.spec_from_file_location('generate_charts', module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


generate_charts = _load_generate_charts()


def addontemplate_with_policies(*policies):
    """Builds a minimal AddOnTemplate carrying the given OperatorPolicies."""
    return {
        'apiVersion': 'addons.open-cluster-management.io/v1alpha1',
        'kind': 'AddOnTemplate',
        'metadata': {'name': 'an-addon'},
        'spec': {
            'addonName': 'an-addon',
            'agentSpec': {
                'workload': {
                    'manifests': list(policies),
                },
            },
        },
    }


def operator_policy(name, subscription=None, upgrade_approval=None):
    """Builds a minimal OperatorPolicy with the given subscription fields."""
    policy = {
        'apiVersion': 'policy.open-cluster-management.io/v1',
        'kind': 'OperatorPolicy',
        'metadata': {
            'name': name,
            'namespace': 'open-cluster-management-policies',
        },
        'spec': {},
    }
    if subscription is not None:
        policy['spec']['subscription'] = dict(subscription)
    if upgrade_approval is not None:
        policy['spec']['upgradeApproval'] = upgrade_approval
    return policy


def policy_spec(resource_data, name):
    """Returns the spec of the named OperatorPolicy inside an AddOnTemplate."""
    for manifest in resource_data['spec']['agentSpec']['workload']['manifests']:
        if manifest.get('kind') == 'OperatorPolicy' and manifest['metadata']['name'] == name:
            return manifest['spec']
    raise AssertionError("OperatorPolicy '%s' not found" % name)


class TestOperatorPolicyValuesKey(unittest.TestCase):
    """Test cases for operator_policy_values_key."""

    def test_derives_camel_case_from_hyphenated_name(self):
        self.assertEqual(
            generate_charts.operator_policy_values_key('kubevirt-hyperconverged-operator'),
            'kubevirtHyperconvergedOperator',
        )

    def test_derives_camel_case_from_short_name(self):
        self.assertEqual(
            generate_charts.operator_policy_values_key('mtv-operator'),
            'mtvOperator',
        )

    def test_leaves_single_word_name_unchanged(self):
        self.assertEqual(
            generate_charts.operator_policy_values_key('console'),
            'console',
        )

    def test_collapses_repeated_hyphens(self):
        self.assertEqual(
            generate_charts.operator_policy_values_key('foo--bar-'),
            'fooBar',
        )

    def test_returns_none_for_empty_name(self):
        self.assertIsNone(generate_charts.operator_policy_values_key('-'))


class TestEnsureOperatorPolicyValueTemplates(unittest.TestCase):
    """Test cases for ensure_operatorpolicy_value_templates."""

    def test_templates_existing_subscription_fields(self):
        resource_data = addontemplate_with_policies(
            operator_policy('mtv-operator', subscription={
                'channel': 'release-v5.0',
                'name': 'mtv-operator',
                'namespace': 'openshift-mtv',
            })
        )

        defaults = generate_charts.ensure_operatorpolicy_value_templates(resource_data)

        spec = policy_spec(resource_data, 'mtv-operator')
        self.assertEqual(
            spec['subscription']['channel'],
            '{{ .Values.global.mtvOperator.subscription.channel }}',
        )
        self.assertEqual(
            spec['subscription']['namespace'],
            '{{ .Values.global.mtvOperator.subscription.namespace }}',
        )
        self.assertEqual(defaults, {
            'mtvOperator': {
                'subscription': {
                    'channel': 'release-v5.0',
                    'name': 'mtv-operator',
                    'namespace': 'openshift-mtv',
                },
            },
        })

    def test_leaves_absent_well_known_fields_absent(self):
        """Fields upstream omits are not invented, so CNV keeps no source."""
        resource_data = addontemplate_with_policies(
            operator_policy('kubevirt-hyperconverged-operator', subscription={
                'channel': 'stable',
                'name': 'kubevirt-hyperconverged',
            })
        )

        generate_charts.ensure_operatorpolicy_value_templates(resource_data)

        spec = policy_spec(resource_data, 'kubevirt-hyperconverged-operator')
        self.assertEqual(set(spec['subscription']), {'channel', 'name'})

    def test_extra_fields_are_added_even_when_upstream_omits_them(self):
        resource_data = addontemplate_with_policies(
            operator_policy('kubevirt-hyperconverged-operator', subscription={
                'channel': 'stable',
                'name': 'kubevirt-hyperconverged',
            })
        )

        generate_charts.ensure_operatorpolicy_value_templates(
            resource_data, extra_fields=['source', 'sourceNamespace'],
        )

        spec = policy_spec(resource_data, 'kubevirt-hyperconverged-operator')
        self.assertEqual(
            spec['subscription']['source'],
            '{{ .Values.global.kubevirtHyperconvergedOperator.subscription.source }}',
        )
        self.assertEqual(
            spec['subscription']['sourceNamespace'],
            '{{ .Values.global.kubevirtHyperconvergedOperator.subscription.sourceNamespace }}',
        )

    def test_upgrade_approval_is_templated_as_a_sibling(self):
        resource_data = addontemplate_with_policies(
            operator_policy('kubevirt-hyperconverged-operator',
                            subscription={'channel': 'stable'},
                            upgrade_approval='Automatic')
        )

        defaults = generate_charts.ensure_operatorpolicy_value_templates(resource_data)

        spec = policy_spec(resource_data, 'kubevirt-hyperconverged-operator')
        self.assertEqual(
            spec['upgradeApproval'],
            '{{ .Values.global.kubevirtHyperconvergedOperator.upgradeApproval }}',
        )
        # upgradeApproval is a sibling of subscription, never a member of it.
        self.assertNotIn('upgradeApproval', spec['subscription'])
        self.assertEqual(
            defaults['kubevirtHyperconvergedOperator']['upgradeApproval'], 'Automatic',
        )

    def test_is_idempotent_and_never_harvests_a_reference(self):
        """A second pass must not write '{{ ... }}' into values.yaml."""
        resource_data = addontemplate_with_policies(
            operator_policy('mtv-operator',
                            subscription={'channel': 'release-v5.0', 'name': 'mtv-operator'},
                            upgrade_approval='Automatic')
        )

        first = generate_charts.ensure_operatorpolicy_value_templates(resource_data)
        spec = policy_spec(resource_data, 'mtv-operator')
        after_first = {
            'subscription': dict(spec['subscription']),
            'upgradeApproval': spec['upgradeApproval'],
        }
        second = generate_charts.ensure_operatorpolicy_value_templates(resource_data)

        # The first pass harvests the real upstream values...
        self.assertEqual(first['mtvOperator']['subscription']['channel'], 'release-v5.0')
        # ...and the second harvests nothing, so no reference is captured as a
        # default, and the template is left exactly as it was.
        self.assertEqual(second, {})
        self.assertEqual({
            'subscription': dict(spec['subscription']),
            'upgradeApproval': spec['upgradeApproval'],
        }, after_first)

    def test_harvested_defaults_never_contain_a_reference(self):
        """Guards the corruption this transform could cause on a re-run."""
        resource_data = addontemplate_with_policies(
            operator_policy('mtv-operator', subscription={'channel': 'release-v5.0'}),
        )
        generate_charts.ensure_operatorpolicy_value_templates(resource_data)
        second = generate_charts.ensure_operatorpolicy_value_templates(resource_data)

        self.assertEqual(second, {})

    def test_ignores_manifests_that_are_not_operator_policies(self):
        resource_data = addontemplate_with_policies(
            {'kind': 'Deployment', 'metadata': {'name': 'x'}, 'spec': {}},
            operator_policy('mtv-operator', subscription={'channel': 'release-v5.0'}),
        )

        defaults = generate_charts.ensure_operatorpolicy_value_templates(resource_data)

        self.assertEqual(set(defaults), {'mtvOperator'})

    def test_skips_policy_without_a_name(self):
        nameless = operator_policy('placeholder', subscription={'channel': 'stable'})
        del nameless['metadata']['name']
        resource_data = addontemplate_with_policies(nameless)

        defaults = generate_charts.ensure_operatorpolicy_value_templates(resource_data)

        self.assertEqual(defaults, {})

    def test_tolerates_missing_spec_and_manifests(self):
        self.assertEqual(
            generate_charts.ensure_operatorpolicy_value_templates({'metadata': {'name': 'a'}}), {},
        )
        self.assertEqual(
            generate_charts.ensure_operatorpolicy_value_templates({}), {},
        )


class TestRoundTrip(unittest.TestCase):
    """The generator dumps with yaml.dump, so references must survive it."""

    def test_references_survive_a_yaml_dump_round_trip(self):
        resource_data = addontemplate_with_policies(
            operator_policy('mtv-operator',
                            subscription={'channel': 'release-v5.0', 'name': 'mtv-operator'},
                            upgrade_approval='Automatic')
        )
        generate_charts.ensure_operatorpolicy_value_templates(resource_data)

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'out.yaml')
            with open(path, 'w') as f:
                yaml.dump(resource_data, f, width=float("inf"),
                          default_flow_style=False, allow_unicode=True)
            with open(path) as f:
                reloaded = yaml.safe_load(f)

        spec = reloaded['spec']['agentSpec']['workload']['manifests'][0]['spec']
        self.assertEqual(
            spec['subscription']['channel'],
            '{{ .Values.global.mtvOperator.subscription.channel }}',
        )
        self.assertEqual(
            spec['upgradeApproval'],
            '{{ .Values.global.mtvOperator.upgradeApproval }}',
        )


class TestCollectOperatorPolicyDefaults(unittest.TestCase):
    """Test cases for collect_operatorpolicy_defaults."""

    def test_merges_subscription_fields_for_a_shared_policy_name(self):
        accumulated = {}
        generate_charts.collect_operatorpolicy_defaults(accumulated, {
            'mtvOperator': {'subscription': {'channel': 'release-v5.0'}},
        })
        generate_charts.collect_operatorpolicy_defaults(accumulated, {
            'mtvOperator': {'subscription': {'name': 'mtv-operator'}, 'upgradeApproval': 'Automatic'},
        })

        self.assertEqual(accumulated['mtvOperator'], {
            'subscription': {'channel': 'release-v5.0', 'name': 'mtv-operator'},
            'upgradeApproval': 'Automatic',
        })

    def test_tolerates_no_harvested_defaults(self):
        accumulated = {}
        self.assertEqual(
            generate_charts.collect_operatorpolicy_defaults(accumulated, {}), accumulated,
        )


class TestMergeOperatorPolicyValues(unittest.TestCase):
    """Test cases for merge_operatorpolicy_values."""

    def _write_values(self, tmp, values):
        path = os.path.join(tmp, 'values.yaml')
        with open(path, 'w') as f:
            yaml.dump(values, f, default_flow_style=False)
        return path

    def test_adds_nested_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_values(tmp, {'global': {'namespace': 'default'}})
            generate_charts.merge_operatorpolicy_values(path, {
                'mtvOperator': {'subscription': {'channel': 'release-v5.0'}},
            })
            with open(path) as f:
                values = yaml.safe_load(f)

        self.assertEqual(values['global']['namespace'], 'default')
        self.assertEqual(
            values['global']['mtvOperator']['subscription']['channel'], 'release-v5.0',
        )

    def test_existing_values_win_over_harvested_ones(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_values(tmp, {
                'global': {'mtvOperator': {'subscription': {'channel': 'stable'}}},
            })
            generate_charts.merge_operatorpolicy_values(path, {
                'mtvOperator': {'subscription': {'channel': 'release-v5.0', 'name': 'mtv-operator'}},
            })
            with open(path) as f:
                values = yaml.safe_load(f)

        subscription = values['global']['mtvOperator']['subscription']
        self.assertEqual(subscription['channel'], 'stable')
        self.assertEqual(subscription['name'], 'mtv-operator')

    def test_does_nothing_without_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_values(tmp, {'global': {'namespace': 'default'}})
            generate_charts.merge_operatorpolicy_values(path, {})
            with open(path) as f:
                values = yaml.safe_load(f)

        self.assertEqual(values, {'global': {'namespace': 'default'}})

    def test_does_nothing_when_values_file_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Must not raise, even though there are defaults to write.
            generate_charts.merge_operatorpolicy_values(
                os.path.join(tmp, 'absent.yaml'), {'mtvOperator': {'subscription': {}}},
            )

    def test_does_nothing_when_global_is_not_a_mapping(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_values(tmp, {'global': 'not-a-mapping'})
            generate_charts.merge_operatorpolicy_values(path, {
                'mtvOperator': {'subscription': {'channel': 'release-v5.0'}},
            })
            with open(path) as f:
                values = yaml.safe_load(f)

        self.assertEqual(values, {'global': 'not-a-mapping'})


if __name__ == '__main__':
    unittest.main()
