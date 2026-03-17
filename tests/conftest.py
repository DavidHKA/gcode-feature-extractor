"""Shared pytest fixtures."""

import os
import pytest
from pathlib import Path

SAMPLE_DIR = Path(__file__).parent.parent / "sample_data"
MINI_GCODE = SAMPLE_DIR / "mini_test.gcode"


@pytest.fixture(scope="session")
def mini_gcode_content() -> str:
    return MINI_GCODE.read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def mini_result(mini_gcode_content):
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))
    from app.parser import parse_gcode
    return parse_gcode(mini_gcode_content)


@pytest.fixture(scope="session")
def mini_features(mini_result):
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))
    from app.features import extract_global_features, extract_layer_features
    return {
        "global":  extract_global_features(mini_result),
        "layers":  extract_layer_features(mini_result),
    }
