# Copyright (c) 2026 Red Hat, Inc.
# Copyright Contributors to the Open Cluster Management project
# Assumes: Python 3.6+

"""
Schema validation for bundle-generation config files.

This module is the single source of truth for the config schema shared by
``bundles-to-charts.py`` (config.yaml), ``generate-charts.py``
(charts-config.yaml) and ``move-charts.py`` (copy-config.yaml).

The generator entry points call :func:`validate_or_exit` as a pre-flight
check so a malformed config fails fast instead of producing a partially
generated chart tree. The ``validate-config.py`` CLI is a thin wrapper
around :func:`validate_file` for standalone/manual use.

Detected issue classes:
  - Missing required keys
  - Unknown keys (typos or stale config)
  - Type mismatches (e.g. string where list expected)
  - Structural issues (e.g. missing components/operators/charts list)
"""

import logging
import sys

import yaml

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Schema definitions
# ---------------------------------------------------------------------------

# Keys recognised at the top level of the dict-form config files.
_TOP_LEVEL_KEYS = {
    "acm-release-version",
    "mce-release-version",
    "components",
}

# --- config.yaml  (operators / bundles-to-charts.py) -----------------------

# Keys recognised on each component entry in config.yaml.
_OPERATOR_COMPONENT_KEYS = {
    # required
    "repo_name",
    "branch",
    # one of github_ref or gen_command flow
    "github_ref",
    # operator list (standard flow)
    "operators",
    # flat operator keys (gen_command flow — operator fields live directly
    # on the component instead of inside an "operators" list)
    "name",
    "bundlePath",
    "gen_command",
    "git_remote",
    "sha",
    "imageMappings",
    "envImageMappings",
    "exclusions",
    "inclusions",
    "escape-template-variables",
    "skipRBACOverrides",
    "webhook_paths",
    "preserve_files",
    "security-context-constraints",
    "channel",
    "bundles-directory",
    "ignore-webhook-definitions",
}

# Keys recognised on each operator entry inside an "operators" list.
_OPERATOR_ENTRY_KEYS = {
    "name",
    "bundlePath",
    "imageMappings",
    "envImageMappings",
    "exclusions",
    "inclusions",
    "escape-template-variables",
    "skipRBACOverrides",
    "webhook_paths",
    "preserve_files",
    "security-context-constraints",
    "channel",
    "bundles-directory",
    "ignore-webhook-definitions",
}

# ``bundlePath`` is not listed here: it is only required when the alternate
# ``bundles-directory`` + ``channel`` flow is not used. See
# ``_validate_operator_entry``.
_OPERATOR_ENTRY_REQUIRED = {"name", "imageMappings"}

# --- charts-config.yaml / copy-config.yaml --------------------------------

_CHART_COMPONENT_KEYS = {
    "repo_name",
    "github_ref",
    "branch",
    "charts",
}

_CHART_ENTRY_KEYS = {
    "name",
    "chart-path",
    "always-or-toggle",
    "imageMappings",
    "envImageMappings",
    "inclusions",
    "exclusions",
    "skipRBACOverrides",
    "updateChartVersion",
    "escape-template-variables",
    "operatorPolicySubscriptionFields",
    "security-context-constraints",
    "auto-install-for-all-clusters",
    "crd-path",
}

_CHART_ENTRY_REQUIRED = {"name", "chart-path", "always-or-toggle", "imageMappings"}

# Fields that must be dicts when present.
_DICT_FIELDS = {"imageMappings", "envImageMappings"}

# Fields that must be lists when present.
_LIST_FIELDS = {
    "exclusions",
    "inclusions",
    "escape-template-variables",
    "webhook_paths",
    "preserve_files",
    "security-context-constraints",
    "operatorPolicySubscriptionFields",
    "operators",
    "charts",
    "components",
}

# Fields that must be bool when present.
_BOOL_FIELDS = {
    "skipRBACOverrides",
    "updateChartVersion",
    "auto-install-for-all-clusters",
    "ignore-webhook-definitions",
}


class ConfigValidationError(Exception):
    """Raised when a bundle-generation config fails schema validation."""


# ---------------------------------------------------------------------------
# Validation primitives
# ---------------------------------------------------------------------------

def _check_keys(entry, known_keys, required_keys, path, errors, warnings):
    """Check for unknown and missing keys in an entry."""
    for key in entry:
        if key not in known_keys:
            warnings.append(f"{path}: unknown key '{key}'")
    for key in required_keys:
        if key not in entry or entry[key] is None:
            errors.append(f"{path}: missing required key '{key}'")


def _check_types(entry, path, errors):
    """Check that fields have the expected types."""
    for key, value in entry.items():
        if value is None:
            continue
        if key in _DICT_FIELDS and not isinstance(value, dict):
            errors.append(f"{path}.{key}: expected dict, got {type(value).__name__}")
        if key in _LIST_FIELDS and not isinstance(value, list):
            errors.append(f"{path}.{key}: expected list, got {type(value).__name__}")
        if key in _BOOL_FIELDS and not isinstance(value, bool):
            errors.append(f"{path}.{key}: expected bool, got {type(value).__name__}")


def _extract_components(config, errors):
    """Normalize a config into a list of component mappings.

    All three generators accept two shapes:

      - a mapping with a ``components:`` list (canonical for
        config.yaml and charts-config.yaml)
      - a bare root-level list (canonical for copy-config.yaml, but
        accepted by all three)

    Returns ``(components, top_level)``. On a structural error
    ``components`` is ``None``.
    """
    if isinstance(config, list):
        return config, None

    if isinstance(config, dict):
        components = config.get("components")
        if components is None:
            errors.append("top-level: missing required key 'components'")
            return None, config
        if not isinstance(components, list):
            errors.append(
                "top-level.components: expected list, got "
                + type(components).__name__
            )
            return None, config
        return components, config

    errors.append(
        "top-level: expected a mapping or list, got " + type(config).__name__
    )
    return None, None


def _validate_operator_entry(entry, path, errors, warnings):
    """Validate a single operator entry inside an operators list."""
    _check_keys(
        entry, _OPERATOR_ENTRY_KEYS, _OPERATOR_ENTRY_REQUIRED, path, errors, warnings
    )
    # ``bundles-to-charts.py`` resolves the bundle path either from an explicit
    # ``bundlePath`` or by scanning ``bundles-directory`` for ``channel``.
    if entry.get("bundlePath") is None and not (
        entry.get("bundles-directory") and entry.get("channel")
    ):
        errors.append(
            f"{path}: missing required key 'bundlePath' "
            "(or both 'bundles-directory' and 'channel')"
        )
    _check_types(entry, path, errors)


def _validate_chart_entry(entry, path, errors, warnings):
    """Validate a single chart entry inside a charts list."""
    _check_keys(
        entry, _CHART_ENTRY_KEYS, _CHART_ENTRY_REQUIRED, path, errors, warnings
    )
    _check_types(entry, path, errors)


# ---------------------------------------------------------------------------
# Per-config-type validators
# ---------------------------------------------------------------------------

def validate_operators_config(config, errors, warnings):
    """Validate a config.yaml (operators / bundles-to-charts.py)."""
    components, top_level = _extract_components(config, errors)

    if top_level is not None:
        for key in top_level:
            if key not in _TOP_LEVEL_KEYS:
                warnings.append(f"top-level: unknown key '{key}'")

    if components is None:
        return

    for i, comp in enumerate(components):
        comp_path = f"components[{i}]"
        if not isinstance(comp, dict):
            errors.append(f"{comp_path}: expected mapping, got {type(comp).__name__}")
            continue

        _check_keys(comp, _OPERATOR_COMPONENT_KEYS, set(), comp_path, errors, warnings)
        _check_types(comp, comp_path, errors)

        if "repo_name" not in comp:
            errors.append(f"{comp_path}: missing required key 'repo_name'")
        if "branch" not in comp:
            errors.append(f"{comp_path}: missing required key 'branch'")

        operators = comp.get("operators")
        if operators is not None:
            if not isinstance(operators, list):
                errors.append(
                    f"{comp_path}.operators: expected list, got "
                    + type(operators).__name__
                )
            else:
                for j, op in enumerate(operators):
                    op_path = f"{comp_path}.operators[{j}]"
                    if not isinstance(op, dict):
                        errors.append(
                            f"{op_path}: expected mapping, got {type(op).__name__}"
                        )
                        continue
                    _validate_operator_entry(op, op_path, errors, warnings)
        else:
            # gen_command flow: operator fields live on the component directly.
            if "gen_command" in comp or "name" in comp:
                if "name" not in comp:
                    errors.append(f"{comp_path}: gen_command flow requires 'name'")
                if "imageMappings" not in comp:
                    errors.append(
                        f"{comp_path}: gen_command flow requires 'imageMappings'"
                    )
                # bundles-to-charts.py reads repo["bundlePath"] to locate the
                # generated bundle, so it is required on this flow.
                if "gen_command" in comp and comp.get("bundlePath") is None:
                    errors.append(
                        f"{comp_path}: gen_command flow requires 'bundlePath'"
                    )


def _validate_chart_components(
    config, errors, warnings, require_github_ref=False, require_branch=True
):
    """Shared chart-component validation for charts-config and copy-config.

    Both shapes are accepted: a mapping with ``components:`` (canonical for
    charts-config.yaml) and a bare root-level list (canonical for
    copy-config.yaml). ``move-charts.py`` and ``generate-charts.py`` both
    handle either, so rejecting one would produce false positives.

    ``require_github_ref`` / ``require_branch`` differ per caller:
      - ``move-charts.py`` always clone from ``github_ref`` (no override
        mechanism) but fall back to the repository default branch when
        ``branch`` is absent.
      - ``generate-charts.py`` can supply the clone URL via
        ``--component-fork`` and the branch via ``--component-branch``, so
        the validator cannot require ``github_ref`` there.
    """
    components, top_level = _extract_components(config, errors)

    if top_level is not None:
        for key in top_level:
            if key not in _TOP_LEVEL_KEYS:
                warnings.append(f"top-level: unknown key '{key}'")

    if components is None:
        return

    for i, comp in enumerate(components):
        comp_path = f"components[{i}]"
        if not isinstance(comp, dict):
            errors.append(f"{comp_path}: expected mapping, got {type(comp).__name__}")
            continue

        _check_keys(comp, _CHART_COMPONENT_KEYS, set(), comp_path, errors, warnings)

        if "repo_name" not in comp:
            errors.append(f"{comp_path}: missing required key 'repo_name'")
        if require_github_ref and comp.get("github_ref") is None:
            errors.append(f"{comp_path}: missing required key 'github_ref'")
        if require_branch and comp.get("branch") is None:
            errors.append(f"{comp_path}: missing required key 'branch'")

        charts = comp.get("charts")
        if charts is None:
            errors.append(f"{comp_path}: missing required key 'charts'")
            continue
        if not isinstance(charts, list):
            errors.append(
                f"{comp_path}.charts: expected list, got " + type(charts).__name__
            )
            continue

        for j, chart in enumerate(charts):
            chart_path = f"{comp_path}.charts[{j}]"
            if not isinstance(chart, dict):
                errors.append(
                    f"{chart_path}: expected mapping, got {type(chart).__name__}"
                )
                continue
            _validate_chart_entry(chart, chart_path, errors, warnings)


def validate_charts_config(config, errors, warnings):
    """Validate a charts-config.yaml (charts / generate-charts.py)."""
    _validate_chart_components(config, errors, warnings)


def validate_copy_config(config, errors, warnings):
    """Validate a copy-config.yaml (copy / move-charts.py)."""
    # move-charts.py always uses ``github_ref`` for the clone URL and clones
    # the repository default branch when ``branch`` is omitted.
    _validate_chart_components(
        config, errors, warnings, require_github_ref=True, require_branch=False
    )


_VALIDATORS = {
    "operators": validate_operators_config,
    "charts": validate_charts_config,
    "copy": validate_copy_config,
}


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def collect_issues(config, config_type):
    """Return ``(errors, warnings)`` for an already-loaded config object."""
    validator = _VALIDATORS.get(config_type)
    if validator is None:
        raise ConfigValidationError(
            f"unknown config type: {config_type!r} "
            f"(expected one of {sorted(_VALIDATORS)})"
        )

    errors = []
    warnings = []
    validator(config, errors, warnings)
    return errors, warnings


def validate_file(config_path, config_type, strict=False, source=None):
    """Load and validate a config file, logging the outcome.

    Parameters
    ----------
    config_path : str
        Path to the YAML config file.
    config_type : str
        ``"operators"`` (config.yaml), ``"charts"`` (charts-config.yaml) or
        ``"copy"`` (copy-config.yaml).
    strict : bool
        If True, treat warnings (unknown keys) as errors.
    source : str, optional
        Label used in log messages. Defaults to ``config_path``.

    Returns
    -------
    bool
        True if validation passed, False otherwise.
    """
    label = source or config_path

    try:
        with open(config_path, "r") as f:
            config = yaml.safe_load(f)
    except FileNotFoundError:
        logger.error("Config file not found: %s", config_path)
        return False
    except yaml.YAMLError as e:
        logger.error("Failed to parse YAML: %s: %s", config_path, e)
        return False

    if config is None:
        logger.error("Config file is empty: %s", config_path)
        return False

    try:
        errors, warnings = collect_issues(config, config_type)
    except ConfigValidationError as e:
        logger.error("%s", e)
        return False

    for w in warnings:
        logger.warning("[CONFIG] %s", w)
    for e in errors:
        logger.error("[CONFIG] %s", e)

    if strict and warnings:
        logger.error("Strict mode: %d warning(s) treated as errors", len(warnings))

    total_issues = len(errors) + (len(warnings) if strict else 0)

    if total_issues == 0:
        logger.info(
            "Config validation passed: %s (%d warning(s))", label, len(warnings)
        )
        return True

    logger.error(
        "Config validation failed: %s (%d error(s), %d warning(s))",
        label,
        len(errors),
        len(warnings),
    )
    return False


def validate_or_exit(config, config_type, source, strict=False, skip=False):
    """Validate an already-loaded config, exiting on failure.

    Pre-flight helper for the generator entry points, which have already
    parsed their YAML (and support both the dict and bare-list shapes).

    Parameters
    ----------
    config : object
        The object returned by ``yaml.safe_load``.
    config_type : str
        ``"operators"``, ``"charts"`` or ``"copy"``.
    source : str
        Config path or label, used in log/error messages.
    strict : bool
        If True, treat warnings as errors.
    skip : bool
        If True, skip validation entirely (``--skip-validation``).
    """
    if skip:
        logger.info("Config validation skipped for %s (--skip-validation)", source)
        return

    errors, warnings = collect_issues(config, config_type)

    for w in warnings:
        logger.warning("[CONFIG] %s", w)

    if errors:
        for e in errors:
            logger.error("[CONFIG] %s", e)
        logger.error(
            "Config validation failed for %s (%d error(s)). "
            "Fix the config or re-run with --skip-validation to bypass.",
            source,
            len(errors),
        )
        sys.exit(1)

    if strict and warnings:
        logger.error(
            "Config validation failed for %s in strict mode "
            "(%d warning(s) treated as errors).",
            source,
            len(warnings),
        )
        sys.exit(1)

    logger.info(
        "Config validation passed for %s (%d warning(s))", source, len(warnings)
    )


# Backwards-compatible alias for the previous single-file API.
validate = validate_file
