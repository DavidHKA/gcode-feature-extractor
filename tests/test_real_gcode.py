"""
Integration tests against a real PrusaSlicer G-code file (sample_data/Nr. 1.gcode).

These complement the synthetic mini_test.gcode unit tests by verifying the full
pipeline on an actual PETG tensile-specimen file from the training dataset.

Known ground-truth values extracted from the file header:
  layer_height      = 0.1
  perimeters        = 2
  fill_density      = 20%  → 0.20 as fraction
  infill_speed      = 80   → used as print_speed fallback
  temperature       = 230  → nozzle temp
"""

import pytest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from app.parser import parse_gcode
from app.features import (
    extract_global_features,
    extract_layer_features,
    extract_slicer_params,
    build_training_vector,
)

REAL_PATH = Path(__file__).parent.parent / "sample_data" / "Nr. 1.gcode"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def result():
    return parse_gcode(REAL_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def gf(result):
    return extract_global_features(result)


@pytest.fixture(scope="module")
def layer_df(result):
    return extract_layer_features(result)


@pytest.fixture(scope="module")
def slicer_params(result):
    return extract_slicer_params(result.declared_settings)


@pytest.fixture(scope="module")
def tv(result, gf):
    return build_training_vector(gf, result.declared_settings)


# ===========================================================================
# Slicer parameter extraction
# ===========================================================================

class TestSlicerParams:
    def test_layer_height(self, slicer_params):
        assert slicer_params["sp__layer_height"] == pytest.approx(0.1, abs=1e-6)

    def test_perimeters(self, slicer_params):
        assert slicer_params["sp__perimeters"] == pytest.approx(2.0, abs=1e-6)

    def test_fill_density(self, slicer_params):
        """20% → stored as 0.20 fraction."""
        assert slicer_params["sp__fill_density"] == pytest.approx(0.20, abs=1e-6)

    def test_nozzle_temp(self, slicer_params):
        assert slicer_params["sp__nozzle_temp"] == pytest.approx(230.0, abs=1e-6)

    def test_print_speed_from_infill_speed(self, slicer_params):
        """No print_speed key in header → falls back to infill_speed = 80."""
        assert slicer_params["sp__infill_speed"] == pytest.approx(80.0, abs=1e-6)

    def test_no_missing_critical_params(self, slicer_params):
        for key in ("sp__layer_height", "sp__perimeters", "sp__fill_density",
                    "sp__nozzle_temp"):
            assert slicer_params[key] is not None, f"{key} must not be None"

    def test_filament_type_petg(self, result):
        ft = result.declared_settings.get("filament_type")
        assert ft == "PETG"


# ===========================================================================
# Training vector
# ===========================================================================

class TestTrainingVector:
    def test_has_15_features(self, tv):
        assert tv["n_features"] == 15

    def test_feature_names_length(self, tv):
        assert len(tv["feature_names"]) == 15

    def test_values_length(self, tv):
        assert len(tv["values"]) == 15

    def test_slicer_params_in_tv(self, tv):
        for key in ("sp__layer_height", "sp__nozzle_temp",
                    "sp__fill_density", "sp__perimeters"):
            assert key in tv["feature_names"], f"{key} missing from TV"

    def test_slicer_params_not_null(self, tv):
        idx = {name: i for i, name in enumerate(tv["feature_names"])}
        for key in ("sp__layer_height", "sp__nozzle_temp",
                    "sp__fill_density", "sp__perimeters"):
            val = tv["values"][idx[key]]
            assert val is not None, f"{key} value is None in TV"

    def test_layer_height_value_in_tv(self, tv):
        idx = tv["feature_names"].index("sp__layer_height")
        assert tv["values"][idx] == pytest.approx(0.1, abs=1e-6)

    def test_nozzle_temp_value_in_tv(self, tv):
        idx = tv["feature_names"].index("sp__nozzle_temp")
        assert tv["values"][idx] == pytest.approx(230.0, abs=1e-6)

    def test_fill_density_value_in_tv(self, tv):
        """Stored as fraction 0–1, not percentage."""
        idx = tv["feature_names"].index("sp__fill_density")
        assert tv["values"][idx] == pytest.approx(0.20, abs=1e-6)

    def test_thermal_bonding_positive(self, tv):
        idx = tv["feature_names"].index("thermal_bonding_proxy")
        assert tv["values"][idx] > 0

    def test_no_nan_values(self, tv):
        import math
        for name, val in zip(tv["feature_names"], tv["values"]):
            if val is not None:
                assert not math.isnan(val), f"{name} is NaN"


# ===========================================================================
# Parser plausibility
# ===========================================================================

class TestParserPlausibility:
    def test_many_layers(self, result):
        """Real PETG specimen at 0.1 mm layer height → many layers (39 in Nr. 1.gcode)."""
        assert len(result.layer_info) > 30

    def test_many_segments(self, result):
        assert len(result.segments) > 1000

    def test_retracts_present(self, result):
        retracts = [s for s in result.segments if s.is_retract]
        assert len(retracts) > 0

    def test_nozzle_temp_detected(self, gf):
        assert gf["first_layer_temp"] == pytest.approx(230.0, abs=1.0)

    def test_layer_df_rows_match_layer_count(self, result, layer_df):
        assert len(layer_df) == len(result.layer_info)

    def test_extrude_path_positive(self, layer_df):
        assert (layer_df["extrude_path_mm"] > 0).all()
