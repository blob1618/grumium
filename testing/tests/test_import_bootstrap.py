"""Regression tests for the Streamlit entrypoint import path."""

import importlib.machinery
from pathlib import Path


def test_testing_entrypoint_does_not_shadow_production_app_package():
    root = Path(__file__).resolve().parents[2]
    testing_dir = root / "testing"

    spec = importlib.machinery.PathFinder.find_spec(
        "app",
        [str(testing_dir), str(root)],
    )

    assert spec is not None
    assert spec.submodule_search_locations is not None
    assert Path(next(iter(spec.submodule_search_locations))).resolve() == (root / "app").resolve()
