#!/usr/bin/env python3
"""
Shared test helpers for bundle-generation unit tests.

Centralises the ``validate_csv`` stub and the importlib loader so that
every test module does not need to duplicate the shim.
"""

import importlib.util
import os
import sys
import types

_SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))


def _ensure_validate_csv_stub():
    """Register a no-op ``validate_csv`` module if one is not on PYTHONPATH.

    The generator scripts do ``from validate_csv import *`` at the top
    level.  ``validate_csv`` lives in the *consumer* repo (e.g.
    ``multiclusterhub-operator/hack/bundle-automation/validate_csv.py``)
    and is added to ``PYTHONPATH`` at runtime.  For offline unit tests we
    substitute a lightweight stub.
    """
    if 'validate_csv' not in sys.modules:
        stub = types.ModuleType('validate_csv')
        stub.validateCSV = lambda csvPath: []
        stub.validateFieldMapping = lambda csv, ruleType, fieldMap: []
        sys.modules['validate_csv'] = stub


def load_script_module(name, filename):
    """Import a hyphenated script file as a Python module.

    Parameters
    ----------
    name : str
        Module name to register (e.g. ``'bundles_to_charts'``).
    filename : str
        Basename of the script relative to ``scripts/bundle-generation/``
        (e.g. ``'bundles-to-charts.py'``).

    Returns
    -------
    types.ModuleType
        The loaded module.
    """
    _ensure_validate_csv_stub()
    module_path = os.path.join(_SCRIPT_DIR, filename)
    spec = importlib.util.spec_from_file_location(name, module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
