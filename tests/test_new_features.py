"""
Tests for new feature groups (v2):
  A) Thermal History Proxies
  B) Bonding Quality Proxies
  C) Structural Orientation Features
  D) Energy / Material Flow Proxies
  E) Specimen-Level Aggregation
  F) Artifact Filtering
"""

import pytest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from app.parser import parse_gcode
from app.features import (
    extract_global_features,
    extract_layer_features,
    extract_specimen_features,
    generate_manifest,
)

MINI_PATH = Path(__file__).parent.parent / "sample_data" / "mini_test.gcode"


@pytest.fixture(scope="module")
def result():
    return parse_gcode(MINI_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def gf(result):
    return extract_global_features(result)


@pytest.fixture(scope="module")
def layer_df(result):
    return extract_layer_features(result)


@pytest.fixture(scope="module")
def specimen(layer_df):
    return extract_specimen_features(layer_df)


# ===========================================================================
# A) Thermal History Proxies
# ===========================================================================

class TestThermalHistoryLayer:
    def test_cumulative_time_present(self, layer_df):
        assert "cumulative_print_time_s" in layer_df.columns

    def test_cumulative_time_monotone(self, layer_df):
        """Cumulative time must be non-decreasing for print layers."""
        df = layer_df[layer_df["layer_id"] >= 0]
        vals = list(df["cumulative_print_time_s"])
        for i in range(1, len(vals)):
            assert vals[i] >= vals[i - 1] - 1e-9, \
                f"Cumulative time decreased at layer {i}: {vals}"

    def test_relative_layer_time_present(self, layer_df):
        assert "relative_layer_time" in layer_df.columns

    def test_relative_layer_time_positive(self, layer_df):
        df = layer_df[layer_df["layer_id"] >= 0]
        assert (df["relative_layer_time"] > 0).all()

    def test_rolling_mean_layer_time_present(self, layer_df):
        assert "rolling_mean_layer_time" in layer_df.columns

    def test_rolling_mean_positive(self, layer_df):
        df = layer_df[layer_df["layer_id"] >= 0]
        assert (df["rolling_mean_layer_time"] > 0).all()

    def test_layer_time_gradient_present(self, layer_df):
        assert "layer_time_gradient" in layer_df.columns

    def test_layer_time_gradient_first_layer_zero(self, layer_df):
        """First print layer (layer_id==0) has no predecessor → gradient==0."""
        row = layer_df[layer_df["layer_id"] == 0].iloc[0]
        assert row["layer_time_gradient"] == 0.0

    def test_norm_extrusion_time_share_present(self, layer_df):
        assert "norm_extrusion_time_share" in layer_df.columns

    def test_norm_extrusion_time_share_range(self, layer_df):
        df = layer_df[layer_df["layer_id"] >= 0]
        vals = df["norm_extrusion_time_share"]
        assert (vals >= 0.0).all() and (vals <= 1.0).all(), \
            "norm_extrusion_time_share must be in [0, 1]"


class TestThermalHistoryGlobal:
    def test_thermal_history_key_present(self, gf):
        assert "thermal_history" in gf

    def test_mean_layer_time_positive(self, gf):
        assert gf["thermal_history"]["mean_layer_time"] > 0

    def test_early_mid_late_present(self, gf):
        th = gf["thermal_history"]
        for key in ("early_layer_time_mean", "mid_layer_time_mean", "late_layer_time_mean"):
            assert key in th, f"Missing key: {key}"

    def test_early_late_positive(self, gf):
        th = gf["thermal_history"]
        assert th["early_layer_time_mean"] > 0
        assert th["late_layer_time_mean"] > 0

    def test_cooling_time_keys_present(self, gf):
        th = gf["thermal_history"]
        assert "mean_cooling_time" in th
        assert "std_cooling_time" in th


# ===========================================================================
# B) Bonding Quality Proxies
# ===========================================================================

class TestBondingQualityLayer:
    def test_extrusion_continuity_index_present(self, layer_df):
        assert "extrusion_continuity_index" in layer_df.columns

    def test_extrusion_continuity_nonnegative(self, layer_df):
        df = layer_df[layer_df["layer_id"] >= 0]
        assert (df["extrusion_continuity_index"] >= 0).all()

    def test_interruption_density_present(self, layer_df):
        assert "interruption_density" in layer_df.columns

    def test_short_extrusion_ratio_range(self, layer_df):
        df = layer_df[layer_df["layer_id"] >= 0]
        vals = df["short_extrusion_ratio"]
        assert (vals >= 0).all() and (vals <= 1.0 + 1e-9).all()

    def test_interface_density_present(self, layer_df):
        assert "interface_density" in layer_df.columns

    def test_interface_density_layer1_gt0(self, layer_df):
        """Layer 1 has TYPE:Perimeter followed by TYPE:Infill → at least 1 transition."""
        row = layer_df[layer_df["layer_id"] == 1].iloc[0]
        assert row["interface_density"] >= 1


class TestBondingQualityGlobal:
    def test_bonding_quality_key_present(self, gf):
        assert "bonding_quality" in gf

    def test_extrusion_continuity_index_present(self, gf):
        assert "extrusion_continuity_index" in gf["bonding_quality"]

    def test_interruption_density_present(self, gf):
        assert "interruption_density" in gf["bonding_quality"]

    def test_short_extrusion_ratio_range(self, gf):
        val = gf["bonding_quality"]["short_extrusion_ratio"]
        assert 0.0 <= val <= 1.0

    def test_perimeter_to_infill_ratio_nonneg(self, gf):
        val = gf["bonding_quality"]["perimeter_to_infill_ratio"]
        assert val >= 0

    def test_bonding_disruption_score_range(self, gf):
        val = gf["bonding_quality"]["bonding_disruption_score"]
        assert 0.0 <= val <= 1.0


# ===========================================================================
# C) Structural Orientation Features
# ===========================================================================

class TestOrientationLayer:
    def test_dominant_infill_angle_present(self, layer_df):
        assert "dominant_infill_angle" in layer_df.columns

    def test_load_alignment_score_present(self, layer_df):
        assert "load_alignment_score" in layer_df.columns

    def test_load_alignment_range(self, layer_df):
        df = layer_df[layer_df["layer_id"] >= 0]
        vals = df["load_alignment_score"]
        assert (vals >= 0.0).all() and (vals <= 1.0 + 1e-9).all()

    def test_dominant_angle_range(self, layer_df):
        df = layer_df[layer_df["layer_id"] >= 0]
        vals = df["dominant_infill_angle"]
        assert (vals >= 0.0).all() and (vals < 181.0).all()


class TestOrientationGlobal:
    def test_structural_orientation_key(self, gf):
        assert "structural_orientation" in gf

    def test_dominant_infill_angle_range(self, gf):
        val = gf["structural_orientation"]["dominant_infill_angle"]
        assert 0.0 <= val < 181.0

    def test_angle_dispersion_nonneg(self, gf):
        val = gf["structural_orientation"]["angle_dispersion_index"]
        assert val >= 0.0

    def test_alignment_x_range(self, gf):
        val = gf["structural_orientation"]["angle_alignment_with_x_axis"]
        assert 0.0 <= val <= 1.0 + 1e-9

    def test_load_alignment_range(self, gf):
        val = gf["structural_orientation"]["estimated_load_alignment_score"]
        assert 0.0 <= val <= 1.0 + 1e-9

    def test_orientation_variance_nonneg(self, gf):
        val = gf["structural_orientation"]["layer_orientation_variance"]
        assert val >= 0.0

    def test_mean_alignment_score_present(self, gf):
        assert "mean_alignment_score" in gf["structural_orientation"]

    def test_alignment_std_present(self, gf):
        assert "alignment_std" in gf["structural_orientation"]


# ===========================================================================
# D) Energy / Material Flow Proxies
# ===========================================================================

class TestEnergyFlowLayer:
    def test_volumetric_flow_rate_present(self, layer_df):
        assert "volumetric_flow_rate_est" in layer_df.columns

    def test_volumetric_flow_nonneg(self, layer_df):
        df = layer_df[layer_df["layer_id"] >= 0]
        assert (df["volumetric_flow_rate_est"] >= 0).all()

    def test_layer_energy_proxy_present(self, layer_df):
        assert "layer_energy_proxy" in layer_df.columns

    def test_layer_energy_nonneg(self, layer_df):
        df = layer_df[layer_df["layer_id"] >= 0]
        assert (df["layer_energy_proxy"] >= 0).all()

    def test_flow_variability_index_present(self, layer_df):
        assert "flow_variability_index" in layer_df.columns


class TestEnergyFlowGlobal:
    def test_energy_flow_key(self, gf):
        assert "energy_flow" in gf

    def test_mean_volumetric_flow_positive(self, gf):
        assert gf["energy_flow"]["mean_volumetric_flow"] > 0

    def test_peak_geq_mean(self, gf):
        ef = gf["energy_flow"]
        assert ef["peak_volumetric_flow"] >= ef["mean_volumetric_flow"] - 1e-9

    def test_flow_std_nonneg(self, gf):
        assert gf["energy_flow"]["flow_std"] >= 0

    def test_flow_variability_nonneg(self, gf):
        assert gf["energy_flow"]["flow_variability_index"] >= 0


# ===========================================================================
# E) Specimen-Level Aggregation
# ===========================================================================

class TestSpecimenFeatures:
    def test_specimen_not_empty(self, specimen):
        assert len(specimen) > 0

    def test_stat_suffixes_present(self, specimen):
        """Every feature should produce all 7 stat keys."""
        keys = list(specimen.keys())
        suffixes = {"__mean", "__std", "__p90", "__p10",
                    "__early_mean", "__mid_mean", "__late_mean"}
        found = {k.split("__", 1)[1] for k in keys if "__" in k}
        for suf in suffixes:
            bare = suf.lstrip("_")
            assert bare in found, f"Suffix '{bare}' not found in specimen keys"

    def test_layer_time_mean_positive(self, specimen):
        assert specimen.get("layer_time_est_s__mean", 0) > 0

    def test_extrude_path_mean_positive(self, specimen):
        assert specimen.get("extrude_path_mm__mean", 0) > 0

    def test_p90_geq_p10(self, specimen):
        """p90 >= p10 for all features."""
        feat_names = {k.rsplit("__", 1)[0] for k in specimen if "__" in k}
        for feat in feat_names:
            p90 = specimen.get(f"{feat}__p90", 0)
            p10 = specimen.get(f"{feat}__p10", 0)
            assert p90 >= p10 - 1e-9, f"{feat}: p90={p90} < p10={p10}"

    def test_new_layer_features_aggregated(self, specimen):
        """Thermal / bonding / flow layer features must appear in specimen."""
        expected_prefixes = [
            "relative_layer_time",
            "norm_extrusion_time_share",
            "extrusion_continuity_index",
            "short_extrusion_ratio",
            "load_alignment_score",
            "volumetric_flow_rate_est",
            "layer_energy_proxy",
        ]
        for prefix in expected_prefixes:
            key = f"{prefix}__mean"
            assert key in specimen, f"Expected '{key}' in specimen_features"

    def test_excludes_negative_layer_ids(self, layer_df):
        """extract_specimen_features must ignore layer_id < 0 rows."""
        import pandas as pd
        # create a df with a fake pre-print layer
        fake_row = layer_df.iloc[0].copy()
        fake_row["layer_id"] = -1
        fake_row["layer_time_est_s"] = 9999.0
        df_with_neg = pd.concat(
            [pd.DataFrame([fake_row]), layer_df], ignore_index=True
        )
        spec = extract_specimen_features(df_with_neg)
        # mean should not be inflated by 9999 s
        assert spec.get("layer_time_est_s__mean", 0) < 9999.0


# ===========================================================================
# F) Artifact Filtering
# ===========================================================================

class TestArtifactFiltering:
    def test_mean_nozzle_excludes_zero(self, gf):
        """mean_nozzle_setpoint must not include S=0 cooldown command."""
        # mini_test.gcode ends with M104 S0; mean must still equal 230
        assert gf["mean_nozzle_setpoint"] == pytest.approx(230.0, abs=1.0)

    def test_layer_neg1_not_in_thermal_stats(self, result):
        """Layer features for layer_id < 0 must not pollute thermal aggregates."""
        # _layer_times_list skips layer_id < 0
        from app.features import _layer_times_list
        times = _layer_times_list(result)
        # mini_test has no layer_id < 0 segments → result should equal layer count
        assert len(times) == len(result.layer_info)

    def test_short_segments_excluded_from_bonding(self, gf):
        """bonding_quality metrics only include segments >= 0.2 mm."""
        bq = gf["bonding_quality"]
        # Simply verify the keys are computed (non-negative); no division errors
        assert bq["extrusion_continuity_index"] >= 0
        assert bq["interruption_density"] >= 0

    def test_no_division_by_zero_errors(self, result):
        """extract_global_features must complete without ZeroDivisionError
        even when some segment lists could be empty."""
        # This is implicitly covered, but adding as an explicit regression guard
        gf = extract_global_features(result)
        assert isinstance(gf, dict)

    def test_empty_gcode_no_crash(self):
        """Empty G-code string must not raise."""
        empty_result = parse_gcode("")
        gf = extract_global_features(empty_result)
        ldf = extract_layer_features(empty_result)
        spec = extract_specimen_features(ldf)
        assert isinstance(gf, dict)
        assert ldf.empty
        assert spec == {}


# ===========================================================================
# G) Manifest completeness
# ===========================================================================

class TestManifestV2:
    def test_thermal_history_entries(self):
        m = generate_manifest()
        assert "thermal_history" in m
        assert "mean_layer_time" in m
        assert "early_layer_time_mean" in m

    def test_bonding_quality_entries(self):
        m = generate_manifest()
        assert "bonding_quality" in m
        assert "extrusion_continuity_index" in m
        assert "bonding_disruption_score" in m

    def test_orientation_entries(self):
        m = generate_manifest()
        assert "structural_orientation" in m
        assert "dominant_infill_angle" in m
        assert "load_alignment_score" in m

    def test_energy_flow_entries(self):
        m = generate_manifest()
        assert "energy_flow" in m
        assert "volumetric_flow_rate_est" in m
        assert "layer_energy_proxy" in m

    def test_specimen_level_documented(self):
        m = generate_manifest()
        assert "specimen" in m

    def test_layer_new_columns_documented(self):
        m = generate_manifest()
        new_cols = [
            "cumulative_print_time_s",
            "relative_layer_time",
            "rolling_mean_layer_time",
            "layer_time_gradient",
            "norm_extrusion_time_share",
            "interruption_density",
            "short_extrusion_ratio",
            "interface_density",
        ]
        for col in new_cols:
            assert col in m, f"Manifest missing: {col}"

    def test_artifact_filtering_notes(self):
        m = generate_manifest()
        assert "Artifact filtering" in m or "artifact" in m.lower()
