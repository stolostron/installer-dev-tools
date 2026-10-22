"""
Unit tests for the config schema validator (utils/config_validator.py).
"""

import os
import tempfile
import unittest

import yaml
from utils import config_validator as validate_config


def _write_yaml(tmp, data, filename="config.yaml"):
    path = os.path.join(tmp, filename)
    with open(path, "w") as f:
        yaml.dump(data, f, default_flow_style=False)
    return path


# ---------------------------------------------------------------------------
# Operators config (config.yaml / bundles-to-charts.py)
# ---------------------------------------------------------------------------


class TestValidateOperatorsConfig(unittest.TestCase):
    """Tests for validate_operators_config."""

    def _run(self, config, strict=False):
        errors, warnings = [], []
        validate_config.validate_operators_config(config, errors, warnings)
        return errors, warnings

    # --- Valid configs ---

    def test_valid_standard_flow(self):
        config = {
            "acm-release-version": "5.1",
            "components": [
                {
                    "repo_name": "search-v2-operator",
                    "github_ref": "https://github.com/stolostron/search-v2-operator.git",
                    "branch": "release-5.1",
                    "operators": [
                        {
                            "name": "search-v2-operator",
                            "bundlePath": "bundle/manifests/",
                            "imageMappings": {"search-v2-operator": "search_v2_operator"},
                        }
                    ],
                }
            ],
        }
        errors, warnings = self._run(config)
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_valid_gen_command_flow(self):
        config = {
            "mce-release-version": "5.1",
            "components": [
                {
                    "repo_name": "hive",
                    "branch": "master",
                    "name": "hive-operator",
                    "bundlePath": "/tmp/hive-operator-manifests",
                    "gen_command": "./hack/bundle-automation/gen-hive-bundle.sh",
                    "git_remote": "https://github.com/openshift/hive.git",
                    "imageMappings": {"hive": "openshift_hive"},
                }
            ],
        }
        errors, warnings = self._run(config)
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_valid_with_optional_keys(self):
        config = {
            "components": [
                {
                    "repo_name": "my-operator",
                    "github_ref": "https://github.com/org/repo.git",
                    "branch": "main",
                    "operators": [
                        {
                            "name": "my-operator",
                            "bundlePath": "bundle/manifests/",
                            "imageMappings": {"img": "img_key"},
                            "exclusions": ["readOnlyRootFilesystem"],
                            "inclusions": ["pullSecretOverride"],
                            "escape-template-variables": ["ACTION"],
                            "skipRBACOverrides": False,
                            "webhook_paths": ["config/webhook/manifests.yaml"],
                            "preserve_files": ["values.yaml"],
                            "security-context-constraints": [],
                            "envImageMappings": {"DB_IMAGE": "db_key"},
                            "channel": "stable",
                            "bundles-directory": "bundles/",
                            "ignore-webhook-definitions": False,
                        }
                    ],
                }
            ],
        }
        errors, warnings = self._run(config)
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    # --- Missing required keys ---

    def test_missing_components(self):
        errors, _ = self._run({"acm-release-version": "5.1"})
        self.assertTrue(any("missing required key 'components'" in e for e in errors))

    def test_missing_repo_name(self):
        config = {"components": [{"branch": "main", "operators": []}]}
        errors, _ = self._run(config)
        self.assertTrue(any("missing required key 'repo_name'" in e for e in errors))

    def test_missing_branch(self):
        config = {"components": [{"repo_name": "x", "operators": []}]}
        errors, _ = self._run(config)
        self.assertTrue(any("missing required key 'branch'" in e for e in errors))

    def test_missing_operator_required_keys(self):
        config = {
            "components": [
                {
                    "repo_name": "x",
                    "branch": "main",
                    "operators": [{}],
                }
            ],
        }
        errors, _ = self._run(config)
        self.assertTrue(any("'name'" in e for e in errors))
        self.assertTrue(any("'bundlePath'" in e for e in errors))
        self.assertTrue(any("'imageMappings'" in e for e in errors))

    def test_gen_command_missing_name(self):
        config = {
            "components": [
                {
                    "repo_name": "x",
                    "branch": "main",
                    "gen_command": "./gen.sh",
                    "imageMappings": {"a": "b"},
                }
            ],
        }
        errors, _ = self._run(config)
        self.assertTrue(any("'name'" in e for e in errors))

    # --- Unknown keys ---

    def test_unknown_top_level_key(self):
        config = {"components": [], "foo": "bar"}
        _, warnings = self._run(config)
        self.assertTrue(any("unknown key 'foo'" in w for w in warnings))

    def test_unknown_operator_key(self):
        config = {
            "components": [
                {
                    "repo_name": "x",
                    "branch": "main",
                    "operators": [
                        {
                            "name": "x",
                            "bundlePath": "b/",
                            "imageMappings": {},
                            "typo_key": True,
                        }
                    ],
                }
            ],
        }
        _, warnings = self._run(config)
        self.assertTrue(any("unknown key 'typo_key'" in w for w in warnings))

    # --- Type mismatches ---

    def test_image_mappings_wrong_type(self):
        config = {
            "components": [
                {
                    "repo_name": "x",
                    "branch": "main",
                    "operators": [
                        {
                            "name": "x",
                            "bundlePath": "b/",
                            "imageMappings": "not-a-dict",
                        }
                    ],
                }
            ],
        }
        errors, _ = self._run(config)
        self.assertTrue(any("expected dict" in e for e in errors))

    def test_exclusions_wrong_type(self):
        config = {
            "components": [
                {
                    "repo_name": "x",
                    "branch": "main",
                    "operators": [
                        {
                            "name": "x",
                            "bundlePath": "b/",
                            "imageMappings": {},
                            "exclusions": "not-a-list",
                        }
                    ],
                }
            ],
        }
        errors, _ = self._run(config)
        self.assertTrue(any("expected list" in e for e in errors))

    # --- Structural issues ---

    def test_components_not_a_list(self):
        errors, _ = self._run({"components": "bad"})
        self.assertTrue(any("expected list" in e for e in errors))

    def test_component_not_a_dict(self):
        errors, _ = self._run({"components": ["bad"]})
        self.assertTrue(any("expected mapping" in e for e in errors))

    def test_non_dict_top_level(self):
        errors, _ = self._run("not-a-config")
        self.assertTrue(any("expected a mapping or list" in e for e in errors))

    def test_bare_list_top_level_accepted(self):
        # bundles-to-charts.py also accepts a root-level list of components.
        errors, _ = self._run(
            [
                {
                    "repo_name": "x",
                    "branch": "main",
                    "operators": [
                        {"name": "x", "bundlePath": "b/", "imageMappings": {}}
                    ],
                }
            ]
        )
        self.assertEqual(errors, [])


# ---------------------------------------------------------------------------
# Charts config (charts-config.yaml / generate-charts.py)
# ---------------------------------------------------------------------------


class TestValidateChartsConfig(unittest.TestCase):
    """Tests for validate_charts_config."""

    def _run(self, config):
        errors, warnings = [], []
        validate_config.validate_charts_config(config, errors, warnings)
        return errors, warnings

    def test_valid_chart_config(self):
        config = {
            "acm-release-version": "5.1",
            "components": [
                {
                    "repo_name": "mtv-integrations",
                    "github_ref": "https://github.com/stolostron/mtv-integrations.git",
                    "branch": "release-5.1",
                    "charts": [
                        {
                            "name": "mtv-integrations",
                            "chart-path": "charts",
                            "always-or-toggle": "toggle",
                            "imageMappings": {"mtv-integrations": "mtv_integrations"},
                            "skipRBACOverrides": True,
                            "updateChartVersion": True,
                            "operatorPolicySubscriptionFields": ["source"],
                            "auto-install-for-all-clusters": True,
                        }
                    ],
                }
            ],
        }
        errors, warnings = self._run(config)
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_missing_chart_required_keys(self):
        config = {
            "components": [
                {
                    "repo_name": "x",
                    "branch": "main",
                    "charts": [{}],
                }
            ],
        }
        errors, _ = self._run(config)
        self.assertTrue(any("'name'" in e for e in errors))
        self.assertTrue(any("'chart-path'" in e for e in errors))
        self.assertTrue(any("'always-or-toggle'" in e for e in errors))
        self.assertTrue(any("'imageMappings'" in e for e in errors))

    def test_unknown_chart_key(self):
        config = {
            "components": [
                {
                    "repo_name": "x",
                    "branch": "main",
                    "charts": [
                        {
                            "name": "x",
                            "chart-path": "c/",
                            "always-or-toggle": "toggle",
                            "imageMappings": {},
                            "bogus": True,
                        }
                    ],
                }
            ],
        }
        _, warnings = self._run(config)
        self.assertTrue(any("unknown key 'bogus'" in w for w in warnings))

    def test_missing_charts_list(self):
        config = {
            "components": [{"repo_name": "x", "branch": "main"}],
        }
        errors, _ = self._run(config)
        self.assertTrue(any("missing required key 'charts'" in e for e in errors))

    def test_bool_type_check(self):
        config = {
            "components": [
                {
                    "repo_name": "x",
                    "branch": "main",
                    "charts": [
                        {
                            "name": "x",
                            "chart-path": "c/",
                            "always-or-toggle": "toggle",
                            "imageMappings": {},
                            "updateChartVersion": "yes",
                        }
                    ],
                }
            ],
        }
        errors, _ = self._run(config)
        self.assertTrue(any("expected bool" in e for e in errors))


# ---------------------------------------------------------------------------
# End-to-end validate() function
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Copy config (copy-config.yaml / move-charts.py)
# ---------------------------------------------------------------------------


class TestValidateCopyConfig(unittest.TestCase):
    """Tests for validate_copy_config (root-level list)."""

    def _run(self, config):
        errors, warnings = [], []
        validate_config.validate_copy_config(config, errors, warnings)
        return errors, warnings

    def test_valid_copy_config(self):
        config = [
            {
                "repo_name": "multicluster-role-assignment",
                "github_ref": "https://github.com/stolostron/multicluster-role-assignment.git",
                "branch": "release-5.1",
                "charts": [
                    {
                        "name": "fine-grained-rbac",
                        "chart-path": "charts/fine-grained-rbac",
                        "always-or-toggle": "toggle",
                        "imageMappings": {"img": "key"},
                        "crd-path": "config/crd/bases",
                    }
                ],
            }
        ]
        errors, warnings = self._run(config)
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_components_mapping_accepted(self):
        # move-charts.py accepts a dict with a 'components:' key as well.
        errors, _ = self._run({"components": []})
        self.assertEqual(errors, [])

    def test_scalar_top_level_rejected(self):
        errors, _ = self._run("not-a-config")
        self.assertTrue(any("expected a mapping or list" in e for e in errors))

    def test_missing_charts(self):
        config = [{"repo_name": "x", "branch": "main"}]
        errors, _ = self._run(config)
        self.assertTrue(any("missing required key 'charts'" in e for e in errors))

    def test_unknown_chart_key_in_copy(self):
        config = [
            {
                "repo_name": "x",
                "branch": "main",
                "charts": [
                    {
                        "name": "x",
                        "chart-path": "c/",
                        "always-or-toggle": "toggle",
                        "imageMappings": {},
                        "stale_key": True,
                    }
                ],
            }
        ]
        _, warnings = self._run(config)
        self.assertTrue(any("unknown key 'stale_key'" in w for w in warnings))

    def test_end_to_end_copy_file(self):
        config = [
            {
                "repo_name": "x",
                "github_ref": "https://github.com/org/repo.git",
                "branch": "main",
                "charts": [
                    {
                        "name": "x",
                        "chart-path": "charts/x",
                        "always-or-toggle": "toggle",
                        "imageMappings": {"a": "b"},
                    }
                ],
            }
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_yaml(tmp, config)
            self.assertTrue(validate_config.validate(path, "copy"))


class TestValidateEndToEnd(unittest.TestCase):
    """Tests for the top-level validate() function."""

    def test_valid_operators_file(self):
        config = {
            "components": [
                {
                    "repo_name": "x",
                    "branch": "main",
                    "operators": [
                        {
                            "name": "x",
                            "bundlePath": "b/",
                            "imageMappings": {"a": "b"},
                        }
                    ],
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_yaml(tmp, config)
            self.assertTrue(validate_config.validate(path, "operators"))

    def test_valid_charts_file(self):
        config = {
            "components": [
                {
                    "repo_name": "x",
                    "branch": "main",
                    "charts": [
                        {
                            "name": "x",
                            "chart-path": "c/",
                            "always-or-toggle": "toggle",
                            "imageMappings": {},
                        }
                    ],
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_yaml(tmp, config)
            self.assertTrue(validate_config.validate(path, "charts"))

    def test_missing_file(self):
        self.assertFalse(validate_config.validate("/nonexistent.yaml", "operators"))

    def test_empty_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "empty.yaml")
            with open(path, "w") as f:
                f.write("")
            self.assertFalse(validate_config.validate(path, "operators"))

    def test_invalid_yaml(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "bad.yaml")
            with open(path, "w") as f:
                f.write(":::bad yaml:::")
            self.assertFalse(validate_config.validate(path, "operators"))

    def test_strict_mode_fails_on_warnings(self):
        config = {"components": [], "unknown_key": "val"}
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_yaml(tmp, config)
            # Non-strict: passes (warning only)
            self.assertTrue(validate_config.validate(path, "operators", strict=False))
            # Strict: fails (warning promoted to error)
            self.assertFalse(validate_config.validate(path, "operators", strict=True))

    def test_unknown_config_type(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_yaml(tmp, {"components": []})
            with self.assertLogs("utils.config_validator", level="ERROR"):
                self.assertFalse(validate_config.validate(path, "invalid_type"))


# ---------------------------------------------------------------------------
# Config shape handling (mapping-with-components vs bare list)
# ---------------------------------------------------------------------------


class TestConfigShapes(unittest.TestCase):
    """All generators accept both a 'components:' mapping and a bare list."""

    def _operator_component(self):
        return {
            "repo_name": "x",
            "branch": "main",
            "operators": [
                {"name": "x", "bundlePath": "b/", "imageMappings": {"a": "b"}}
            ],
        }

    def _chart_component(self):
        return {
            "repo_name": "x",
            "branch": "main",
            "charts": [
                {
                    "name": "x",
                    "chart-path": "charts/x",
                    "always-or-toggle": "toggle",
                    "imageMappings": {"a": "b"},
                }
            ],
        }

    def test_operators_accepts_bare_list(self):
        errors, warnings = validate_config.collect_issues(
            [self._operator_component()], "operators"
        )
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_charts_accepts_bare_list(self):
        errors, warnings = validate_config.collect_issues(
            [self._chart_component()], "charts"
        )
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_copy_accepts_components_mapping(self):
        errors, warnings = validate_config.collect_issues(
            {"components": [self._chart_component()]}, "copy"
        )
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_scalar_top_level_is_error(self):
        errors, _ = validate_config.collect_issues("nope", "operators")
        self.assertTrue(any("expected a mapping or list" in e for e in errors))


# ---------------------------------------------------------------------------
# validate_or_exit (generator pre-flight hook)
# ---------------------------------------------------------------------------


class TestValidateOrExit(unittest.TestCase):

    def test_passes_silently_on_valid_config(self):
        config = [{"repo_name": "x", "branch": "main", "charts": []}]
        with self.assertLogs("utils.config_validator", level="INFO"):
            validate_config.validate_or_exit(config, "copy", "copy-config.yaml")

    def test_exits_on_error(self):
        config = [{"repo_name": "x"}]  # missing branch + charts
        with self.assertLogs("utils.config_validator", level="ERROR"), self.assertRaises(
            SystemExit
        ) as ctx:
            validate_config.validate_or_exit(config, "copy", "copy-config.yaml")
        self.assertEqual(ctx.exception.code, 1)

    def test_skip_bypasses_errors(self):
        config = [{"repo_name": "x"}]
        with self.assertLogs("utils.config_validator", level="INFO"):
            validate_config.validate_or_exit(
                config, "copy", "copy-config.yaml", skip=True
            )

    def test_strict_promotes_warnings_to_exit(self):
        config = [{"repo_name": "x", "branch": "main", "charts": [], "typo": 1}]
        with self.assertLogs("utils.config_validator", level="WARNING"):
            validate_config.validate_or_exit(config, "copy", "copy-config.yaml")
        with self.assertLogs("utils.config_validator", level="WARNING"), self.assertRaises(
            SystemExit
        ) as ctx:
            validate_config.validate_or_exit(
                config, "copy", "copy-config.yaml", strict=True
            )
        self.assertEqual(ctx.exception.code, 1)

    def test_unknown_type_raises(self):
        with self.assertRaises(validate_config.ConfigValidationError):
            validate_config.collect_issues({}, "bogus")


if __name__ == "__main__":
    unittest.main()
