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

Pass ``verbose=True`` to any public entry point to get a per-component,
per-field checklist printed to the log so you can see exactly what was
checked and whether each item passed, warned, or failed.
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
# Verbose checklist report
# ---------------------------------------------------------------------------

_PASS = "\u2705"   # green check
_WARN = "\u26a0\ufe0f"   # warning sign
_FAIL = "\u274c"   # red cross


class _VerboseReport:
    """Accumulates checklist entries for a verbose validation run.

    Each entry is ``(indent_level, icon, message)`` where *icon* is one of
    the module-level emoji constants and *indent_level* controls nesting in
    the final output.

    When ``active`` is False every method is a no-op so callers do not need
    ``if verbose:`` guards everywhere.
    """

    def __init__(self, active=False):
        self.active = active
        self._lines = []
        self._counts = {"pass": 0, "warn": 0, "fail": 0}

    # -- recording helpers ---------------------------------------------------

    def passed(self, message, indent=0):
        if not self.active:
            return
        self._lines.append((indent, _PASS, message))
        self._counts["pass"] += 1

    def warned(self, message, indent=0):
        if not self.active:
            return
        self._lines.append((indent, _WARN, message))
        self._counts["warn"] += 1

    def failed(self, message, indent=0):
        if not self.active:
            return
        self._lines.append((indent, _FAIL, message))
        self._counts["fail"] += 1

    def section(self, message, indent=0):
        """Add a non-counted section header."""
        if not self.active:
            return
        self._lines.append((indent, "", message))

    # -- output --------------------------------------------------------------

    def log(self, label):
        """Emit the collected checklist to the module logger."""
        if not self.active or not self._lines:
            return
        logger.info("")
        logger.info("Config validation report: %s", label)
        logger.info("")
        prev_indent = -1
        for indent, icon, msg in self._lines:
            # Blank line before each section header (non-icon line) or when
            # stepping back to a lower indent level, so component and
            # operator/chart blocks are visually separated.
            if (not icon and prev_indent >= 0) or (prev_indent > indent >= 0 and prev_indent >= 0):
                logger.info("")
            prefix = "  " * indent
            if icon:
                logger.info("  %s%s %s", prefix, icon, msg)
            else:
                logger.info("  %s%s", prefix, msg)
            prev_indent = indent
        total = self._counts["pass"] + self._counts["warn"] + self._counts["fail"]
        logger.info("")
        logger.info(
            "  Summary: %d checked, %s %d passed, %s %d warning(s), %s %d error(s)",
            total,
            _PASS, self._counts["pass"],
            _WARN, self._counts["warn"],
            _FAIL, self._counts["fail"],
        )
        logger.info("")


# ---------------------------------------------------------------------------
# Validation primitives
# ---------------------------------------------------------------------------

def _check_keys(entry, known_keys, required_keys, path, errors, warnings,
                report=None, indent=0):
    """Check for unknown and missing keys in an entry."""
    for key in entry:
        if key not in known_keys:
            warnings.append(f"{path}: unknown key '{key}'")
            if report:
                report.warned(f"unknown key '{key}'", indent)
        elif report:
            report.passed(key, indent)
    for key in required_keys:
        if key not in entry or entry[key] is None:
            errors.append(f"{path}: missing required key '{key}'")
            if report:
                report.failed(f"missing required key '{key}'", indent)


def _check_types(entry, path, errors, report=None, indent=0):
    """Check that fields have the expected types."""
    for key, value in entry.items():
        if value is None:
            continue
        if key in _DICT_FIELDS and not isinstance(value, dict):
            errors.append(f"{path}.{key}: expected dict, got {type(value).__name__}")
            if report:
                report.failed(f"{key}: expected dict, got {type(value).__name__}", indent)
        if key in _LIST_FIELDS and not isinstance(value, list):
            errors.append(f"{path}.{key}: expected list, got {type(value).__name__}")
            if report:
                report.failed(f"{key}: expected list, got {type(value).__name__}", indent)
        if key in _BOOL_FIELDS and not isinstance(value, bool):
            errors.append(f"{path}.{key}: expected bool, got {type(value).__name__}")
            if report:
                report.failed(f"{key}: expected bool, got {type(value).__name__}", indent)
        if key == "webhook_paths" and isinstance(value, list):
            for i, item in enumerate(value):
                if not isinstance(item, str) or not item.strip():
                    errors.append(
                        f"{path}.{key}[{i}]: expected non-empty string, "
                        f"got {type(item).__name__}"
                    )
                    if report:
                        report.failed(
                            f"{key}[{i}]: expected non-empty string",
                            indent,
                        )


def _extract_components(config, errors, report=None):
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
        if report:
            report.passed(f"top-level structure (list, {len(config)} component(s))")
        return config, None

    if isinstance(config, dict):
        components = config.get("components")
        if components is None:
            errors.append("top-level: missing required key 'components'")
            if report:
                report.failed("missing required key 'components'")
            return None, config
        if not isinstance(components, list):
            errors.append(
                "top-level.components: expected list, got "
                + type(components).__name__
            )
            if report:
                report.failed(
                    "components: expected list, got " + type(components).__name__
                )
            return None, config
        if report:
            report.passed(
                f"top-level structure (dict, {len(components)} component(s))"
            )
        return components, config

    errors.append(
        "top-level: expected a mapping or list, got " + type(config).__name__
    )
    if report:
        report.failed(
            "top-level: expected a mapping or list, got " + type(config).__name__
        )
    return None, None


def _validate_operator_entry(entry, path, errors, warnings, report=None,
                             indent=0):
    """Validate a single operator entry inside an operators list."""
    _check_keys(
        entry, _OPERATOR_ENTRY_KEYS, _OPERATOR_ENTRY_REQUIRED, path, errors,
        warnings, report=report, indent=indent,
    )
    # ``bundles-to-charts.py`` resolves the bundle path either from a truthy
    # ``bundlePath`` or by scanning ``bundles-directory`` for ``channel``. A
    # null or empty ``bundlePath`` counts as absent, matching the generator.
    if not entry.get("bundlePath") and not (
        entry.get("bundles-directory") and entry.get("channel")
    ):
        errors.append(
            f"{path}: missing required key 'bundlePath' "
            "(or both 'bundles-directory' and 'channel')"
        )
        if report:
            report.failed(
                "missing 'bundlePath' (or 'bundles-directory' + 'channel')",
                indent,
            )
    elif report:
        report.passed("bundlePath / bundle-source", indent)
    _check_types(entry, path, errors, report=report, indent=indent)


def _validate_chart_entry(entry, path, errors, warnings, report=None,
                           indent=0):
    """Validate a single chart entry inside a charts list."""
    _check_keys(
        entry, _CHART_ENTRY_KEYS, _CHART_ENTRY_REQUIRED, path, errors,
        warnings, report=report, indent=indent,
    )
    _check_types(entry, path, errors, report=report, indent=indent)


# ---------------------------------------------------------------------------
# Per-config-type validators
# ---------------------------------------------------------------------------

def validate_operators_config(config, errors, warnings, report=None):
    """Validate a config.yaml (operators / bundles-to-charts.py)."""
    components, top_level = _extract_components(config, errors, report=report)

    if top_level is not None:
        for key in top_level:
            if key not in _TOP_LEVEL_KEYS:
                warnings.append(f"top-level: unknown key '{key}'")
                if report:
                    report.warned(f"unknown top-level key '{key}'")

    if components is None:
        return

    for i, comp in enumerate(components):
        comp_path = f"components[{i}]"
        comp_label = comp.get("repo_name", f"#{i}") if isinstance(comp, dict) else f"#{i}"
        if report:
            report.section(f"components[{i}] ({comp_label})", indent=1)

        if not isinstance(comp, dict):
            errors.append(f"{comp_path}: expected mapping, got {type(comp).__name__}")
            if report:
                report.failed(f"expected mapping, got {type(comp).__name__}", indent=2)
            continue

        _check_keys(comp, _OPERATOR_COMPONENT_KEYS, set(), comp_path, errors,
                     warnings, report=report, indent=2)
        _check_types(comp, comp_path, errors, report=report, indent=2)

        if "repo_name" not in comp:
            errors.append(f"{comp_path}: missing required key 'repo_name'")
            if report:
                report.failed("missing required key 'repo_name'", indent=2)
        if "branch" not in comp:
            errors.append(f"{comp_path}: missing required key 'branch'")
            if report:
                report.failed("missing required key 'branch'", indent=2)

        operators = comp.get("operators")
        if operators is not None:
            if not isinstance(operators, list):
                errors.append(
                    f"{comp_path}.operators: expected list, got "
                    + type(operators).__name__
                )
                if report:
                    report.failed(
                        "operators: expected list, got " + type(operators).__name__,
                        indent=2,
                    )
            else:
                if report:
                    report.passed(
                        f"operators ({len(operators)} entries)", indent=2
                    )
                for j, op in enumerate(operators):
                    op_path = f"{comp_path}.operators[{j}]"
                    op_name = op.get("name", f"#{j}") if isinstance(op, dict) else f"#{j}"
                    if report:
                        report.section(f"operators[{j}] ({op_name})", indent=3)
                    if not isinstance(op, dict):
                        errors.append(
                            f"{op_path}: expected mapping, got {type(op).__name__}"
                        )
                        if report:
                            report.failed(
                                f"expected mapping, got {type(op).__name__}",
                                indent=4,
                            )
                        continue
                    _validate_operator_entry(
                        op, op_path, errors, warnings,
                        report=report, indent=4,
                    )

                # ``bundles-to-charts.py`` needs git_url or gen_command to
                # produce bundles for an operators list; otherwise it reaches
                # the source-selection fallback and exits after cloning the
                # components processed before it.
                if not comp.get("github_ref") and "gen_command" not in comp:
                    errors.append(
                        f"{comp_path}: 'operators' requires 'github_ref' or "
                        "'gen_command'"
                    )
                    if report:
                        report.failed(
                            "'operators' requires 'github_ref' or 'gen_command'",
                            indent=2,
                        )
                elif report:
                    report.passed("source selection (github_ref / gen_command)", indent=2)

                # The gen_command flow reads the component-level
                # ``imageMappings`` even when operator entries are present.
                if (
                    "gen_command" in comp
                    and not comp.get("github_ref")
                    and "imageMappings" not in comp
                ):
                    errors.append(
                        f"{comp_path}: gen_command flow requires 'imageMappings'"
                    )
                    if report:
                        report.failed(
                            "gen_command flow requires 'imageMappings'", indent=2
                        )
        else:
            # gen_command flow: operator fields live on the component directly.
            if "gen_command" in comp or "name" in comp:
                if "name" not in comp:
                    errors.append(f"{comp_path}: gen_command flow requires 'name'")
                    if report:
                        report.failed("gen_command flow requires 'name'", indent=2)
                if "imageMappings" not in comp:
                    errors.append(
                        f"{comp_path}: gen_command flow requires 'imageMappings'"
                    )
                    if report:
                        report.failed(
                            "gen_command flow requires 'imageMappings'", indent=2
                        )

        # ``bundles-to-charts.py`` selects the gen_command flow whenever
        # ``github_ref`` is absent, so this requirement applies even when an
        # ``operators`` list is configured alongside ``gen_command``.
        if (
            "gen_command" in comp
            and not comp.get("github_ref")
            and not comp.get("bundlePath")
        ):
            errors.append(f"{comp_path}: gen_command flow requires 'bundlePath'")
            if report:
                report.failed("gen_command flow requires 'bundlePath'", indent=2)
        # The gen_command branch reads ``repo["sha"]`` unless ``git_remote``
        # is set, so one of the two must be present.
        if (
            "gen_command" in comp
            and not comp.get("github_ref")
            and "git_remote" not in comp
            and "sha" not in comp
        ):
            errors.append(
                f"{comp_path}: gen_command flow requires 'sha' or 'git_remote'"
            )
            if report:
                report.failed(
                    "gen_command flow requires 'sha' or 'git_remote'", indent=2
                )


def _validate_chart_components(
    config, errors, warnings, require_github_ref=False, require_branch=True,
    report=None,
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
    components, top_level = _extract_components(config, errors, report=report)

    if top_level is not None:
        for key in top_level:
            if key not in _TOP_LEVEL_KEYS:
                warnings.append(f"top-level: unknown key '{key}'")
                if report:
                    report.warned(f"unknown top-level key '{key}'")

    if components is None:
        return

    for i, comp in enumerate(components):
        comp_path = f"components[{i}]"
        comp_label = comp.get("repo_name", f"#{i}") if isinstance(comp, dict) else f"#{i}"
        if report:
            report.section(f"components[{i}] ({comp_label})", indent=1)

        if not isinstance(comp, dict):
            errors.append(f"{comp_path}: expected mapping, got {type(comp).__name__}")
            if report:
                report.failed(f"expected mapping, got {type(comp).__name__}", indent=2)
            continue

        _check_keys(comp, _CHART_COMPONENT_KEYS, set(), comp_path, errors,
                     warnings, report=report, indent=2)

        if "repo_name" not in comp:
            errors.append(f"{comp_path}: missing required key 'repo_name'")
            if report:
                report.failed("missing required key 'repo_name'", indent=2)
        if require_github_ref and comp.get("github_ref") is None:
            errors.append(f"{comp_path}: missing required key 'github_ref'")
            if report:
                report.failed("missing required key 'github_ref'", indent=2)
        if require_branch and comp.get("branch") is None:
            errors.append(f"{comp_path}: missing required key 'branch'")
            if report:
                report.failed("missing required key 'branch'", indent=2)

        charts = comp.get("charts")
        if charts is None:
            errors.append(f"{comp_path}: missing required key 'charts'")
            if report:
                report.failed("missing required key 'charts'", indent=2)
            continue
        if not isinstance(charts, list):
            errors.append(
                f"{comp_path}.charts: expected list, got " + type(charts).__name__
            )
            if report:
                report.failed(
                    "charts: expected list, got " + type(charts).__name__,
                    indent=2,
                )
            continue

        if report:
            report.passed(f"charts ({len(charts)} entries)", indent=2)

        for j, chart in enumerate(charts):
            chart_path = f"{comp_path}.charts[{j}]"
            chart_name = chart.get("name", f"#{j}") if isinstance(chart, dict) else f"#{j}"
            if report:
                report.section(f"charts[{j}] ({chart_name})", indent=3)
            if not isinstance(chart, dict):
                errors.append(
                    f"{chart_path}: expected mapping, got {type(chart).__name__}"
                )
                if report:
                    report.failed(
                        f"expected mapping, got {type(chart).__name__}",
                        indent=4,
                    )
                continue
            _validate_chart_entry(
                chart, chart_path, errors, warnings,
                report=report, indent=4,
            )


def validate_charts_config(config, errors, warnings, report=None):
    """Validate a charts-config.yaml (charts / generate-charts.py)."""
    # generate-charts.py exits early with "No charts listed in config to be
    # moved!" for an empty config, so treat that as a valid no-op. Older
    # release branches ship an empty charts-config.yaml.
    if not config:
        if report:
            report.passed("empty charts config (valid no-op)")
        return
    # generate-charts.py clones the repository default branch when ``branch``
    # is omitted, and ``--component-branch`` can supply it at run time.
    _validate_chart_components(
        config, errors, warnings, require_branch=False, report=report,
    )


def validate_copy_config(config, errors, warnings, report=None):
    """Validate a copy-config.yaml (copy / move-charts.py)."""
    # move-charts.py always uses ``github_ref`` for the clone URL and clones
    # the repository default branch when ``branch`` is omitted.
    _validate_chart_components(
        config, errors, warnings, require_github_ref=True,
        require_branch=False, report=report,
    )


_VALIDATORS = {
    "operators": validate_operators_config,
    "charts": validate_charts_config,
    "copy": validate_copy_config,
}


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def collect_issues(config, config_type, verbose=False):
    """Return ``(errors, warnings)`` for an already-loaded config object.

    When *verbose* is True a checklist-style report is also logged showing
    every component and field that was checked.
    """
    validator = _VALIDATORS.get(config_type)
    if validator is None:
        raise ConfigValidationError(
            f"unknown config type: {config_type!r} "
            f"(expected one of {sorted(_VALIDATORS)})"
        )

    report = _VerboseReport(active=verbose)
    errors = []
    warnings = []
    validator(config, errors, warnings, report=report)
    return errors, warnings, report


def validate_file(config_path, config_type, strict=False, source=None,
                  verbose=False):
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
    verbose : bool
        If True, print a per-component checklist showing every field that
        was validated and its pass/warn/fail status.

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

    if not config and config_type == "charts":
        # generate-charts.py treats an empty charts-config.yaml as "no charts
        # to move" and exits successfully, so match that behaviour here.
        logger.info(
            "Config validation passed: %s (empty charts config)", label
        )
        return True

    if config is None:
        logger.error("Config file is empty: %s", config_path)
        return False

    try:
        errors, warnings, report = collect_issues(
            config, config_type, verbose=verbose,
        )
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

    report.log(label)

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


def validate_or_exit(config, config_type, source, strict=False, skip=False,
                     verbose=False):
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
    verbose : bool
        If True, print a per-component checklist showing every field that
        was validated and its pass/warn/fail status.
    """
    if skip:
        logger.info("Config validation skipped for %s (--skip-validation)", source)
        return

    errors, warnings, report = collect_issues(
        config, config_type, verbose=verbose,
    )

    for w in warnings:
        logger.warning("[CONFIG] %s", w)

    report.log(source)

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
