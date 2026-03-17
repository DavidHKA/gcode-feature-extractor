"""
Pytest tests for G-code parser and feature extractor.

All tests are calibrated against sample_data/mini_test.gcode,
which is a synthetic PrusaSlicer 2.7.2 snippet covering all
important markers present in the real target file.
"""

import pytest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from app.parser import parse_gcode, EVT_LAYER_CHANGE, EVT_WIPE_START, EVT_WIPE_END
from app.features import extract_global_features, extract_layer_features, generate_manifest


# ---------------------------------------------------------------------------
# Helper – parse the mini gcode
# ---------------------------------------------------------------------------

MINI_PATH = Path(__file__).parent.parent / "sample_data" / "mini_test.gcode"


@pytest.fixture(scope="module")
def result():
    content = MINI_PATH.read_text(encoding="utf-8")
    return parse_gcode(content)


@pytest.fixture(scope="module")
def gf(result):
    return extract_global_features(result)


@pytest.fixture(scope="module")
def layer_df(result):
    return extract_layer_features(result)


# ===========================================================================
# Parser tests
# ===========================================================================

class TestRelativeExtrusion:
    """M83 → relative extrusion mode."""

    def test_m83_detected(self, result):
        """Parser must recognise M83 and set relative extrusion mode correctly.
        In relative mode every extrude segment's e_delta is the raw E from G1."""
        extrude_segs = [s for s in result.segments if s.is_extrude]
        assert len(extrude_segs) > 0, "Must have extrude segments"
        # In relative mode e_delta == raw E param; all should be positive small numbers
        for s in extrude_segs:
            assert s.e_delta > 0, f"Extrude e_delta must be >0 in relative mode, got {s.e_delta}"

    def test_retract_has_negative_e(self, result):
        """Retract moves must have negative e_delta."""
        retract_segs = [s for s in result.segments if s.is_retract]
        assert len(retract_segs) > 0, "Must have retract segments"
        for s in retract_segs:
            assert s.e_delta < 0, f"Retract e_delta must be <0, got {s.e_delta}"


class TestLayerDetection:
    """Layer counting from ;LAYER_CHANGE markers."""

    def test_layer_count(self, result):
        """Mini gcode has exactly 3 ;LAYER_CHANGE markers → 3 layers (IDs 0, 1, 2)."""
        assert len(result.layer_info) == 3

    def test_layer_ids_sequential(self, result):
        ids = [l.layer_id for l in result.layer_info]
        assert ids == list(range(len(ids))), f"Layer IDs not sequential: {ids}"

    def test_layer_z_values(self, result):
        expected_z = [0.200, 0.500, 0.800]
        actual_z   = [round(l.z, 3) for l in result.layer_info]
        assert actual_z == expected_z, f"Z values wrong: {actual_z}"

    def test_layer_heights(self, result):
        expected_h = [0.200, 0.300, 0.300]
        actual_h   = [round(l.height, 3) for l in result.layer_info]
        assert actual_h == expected_h, f"Heights wrong: {actual_h}"

    def test_layer_change_events_count(self, result):
        lc_events = [e for e in result.events if e.event_type == EVT_LAYER_CHANGE]
        assert len(lc_events) == 3


class TestWipeDetection:
    """WIPE_START / WIPE_END parsing."""

    def test_wipe_count_positive(self, result):
        assert result.wipe_count > 0, "Must detect at least one wipe block"

    def test_wipe_count_exact(self, result):
        """Mini gcode has exactly 2 wipe blocks."""
        assert result.wipe_count == 2

    def test_wipe_start_events(self, result):
        ws = [e for e in result.events if e.event_type == EVT_WIPE_START]
        assert len(ws) == 2

    def test_wipe_end_events(self, result):
        we = [e for e in result.events if e.event_type == EVT_WIPE_END]
        assert len(we) == 2

    def test_segments_in_wipe_are_flagged(self, result):
        wipe_segs = [s for s in result.segments if s.in_wipe]
        assert len(wipe_segs) > 0, "Segments inside wipe blocks must be flagged"


class TestWidthExtraction:
    """WIDTH: tag extraction."""

    def test_width_values_extracted(self, result):
        widths = {s.width_mm for s in result.segments if s.width_mm != 0}
        assert len(widths) > 0, "At least one WIDTH value must be extracted"

    def test_first_layer_width(self, result):
        """First layer uses 0.42 mm width (Skirt/Brim)."""
        first_layer_segs = [s for s in result.segments if s.layer_id == 0 and s.width_mm > 0]
        assert any(abs(s.width_mm - 0.42) < 0.001 for s in first_layer_segs), \
            "First layer must have width ≈ 0.42 mm"


class TestRetractCount:
    """Retract moves (E < 0)."""

    def test_retract_count_positive(self, result):
        retract_segs = [s for s in result.segments if s.is_retract]
        assert len(retract_segs) > 0

    def test_retract_count_exact(self, result):
        """Mini gcode: 2 retracts (one per WIPE_START)."""
        retract_segs = [s for s in result.segments if s.is_retract]
        assert len(retract_segs) == 2

    def test_retract_in_wipe(self, result):
        """Both retracts should be inside wipe blocks."""
        retracts_in_wipe = [s for s in result.segments if s.is_retract and s.in_wipe]
        assert len(retracts_in_wipe) == 2


class TestDynamicsExtraction:
    """M204 + M900 parsing."""

    def test_m204_detected(self, result):
        from app.parser import EVT_ACCEL_SET
        accel_evts = [e for e in result.events if e.event_type == EVT_ACCEL_SET]
        assert len(accel_evts) >= 1

    def test_m204_multiple_values(self, result):
        """Mini gcode has M204 S1250 and M204 S1500 → 2 events."""
        from app.parser import EVT_ACCEL_SET
        accel_evts = [e for e in result.events if e.event_type == EVT_ACCEL_SET]
        assert len(accel_evts) == 2

    def test_m900_k_values(self, result):
        la_vals = result.declared_settings.get("linear_advance_values", [])
        assert len(la_vals) >= 1

    def test_m900_both_values(self, result):
        """Mini gcode: K=0.05 and K=0.04 → 2 M900 events."""
        la_vals = result.declared_settings.get("linear_advance_values", [])
        k_vals  = sorted(v["K"] for v in la_vals)
        assert len(k_vals) == 2
        assert abs(k_vals[0] - 0.04) < 1e-6
        assert abs(k_vals[1] - 0.05) < 1e-6


class TestDeclaredSettings:
    """Header parsing and printer model detection."""

    def test_generated_by(self, result):
        gby = result.declared_settings.get("generated_by", "")
        assert "PrusaSlicer" in str(gby)

    def test_printer_model(self, result):
        assert result.declared_settings.get("printer_model") == "MK3S"

    def test_nozzle_diameter(self, result):
        nd = result.declared_settings.get("nozzle_diameter")
        assert nd is not None
        assert abs(nd - 0.4) < 1e-6

    def test_filament_type(self, result):
        ft = result.declared_settings.get("filament_type")
        assert ft == "PETG"

    def test_header_settings_populated(self, result):
        hs = result.declared_settings.get("header_settings", {})
        assert len(hs) > 0


class TestG92Resets:
    def test_g92_count(self, result):
        """Mini gcode has 5 G92 E0.0 resets."""
        assert result.g92_reset_count == 5

    def test_g92_events_logged(self, result):
        g92_evts = [e for e in result.events if e.event_type == "g92_reset"]
        assert len(g92_evts) == result.g92_reset_count


class TestSegmentClassification:
    def test_travel_has_no_extrusion(self, result):
        for s in result.segments:
            if s.is_travel:
                assert abs(s.e_delta) < 0.001

    def test_extrude_and_retract_mutually_exclusive(self, result):
        for s in result.segments:
            assert not (s.is_extrude and s.is_retract), \
                f"Segment at line {s.line_no} is both extrude and retract"

    def test_xy_distance_positive_for_moves(self, result):
        for s in result.segments:
            if s.is_extrude or s.is_travel:
                assert s.length_mm >= 0


# ===========================================================================
# Feature extraction tests
# ===========================================================================

class TestGlobalFeatures:
    def test_num_layers(self, gf):
        assert gf["num_layers"] == 3

    def test_num_wipe_blocks(self, gf):
        assert gf["num_wipe_blocks"] == 2

    def test_num_retract_segments(self, gf):
        assert gf["num_retract_segments"] == 2

    def test_total_e_pos_positive(self, gf):
        assert gf["total_e_pos"] > 0

    def test_total_e_neg_positive(self, gf):
        assert gf["total_e_neg"] > 0

    def test_travel_extrude_ratio_positive(self, gf):
        assert gf["travel_to_extrude_ratio"] > 0

    def test_retract_wipe_correlation_one(self, gf):
        """All retracts are inside wipe blocks → correlation = 1.0."""
        assert abs(gf["retract_wipe_correlation"] - 1.0) < 1e-6

    def test_linear_advance_summary(self, gf):
        la = gf["linear_advance_summary"]
        assert la["count"] == 2
        assert len(la["unique_values"]) == 2

    def test_e_per_mm_by_type_has_keys(self, gf):
        by_type = gf["e_per_mm_by_type"]
        assert len(by_type) > 0

    def test_accel_changes_count(self, gf):
        assert gf["accel_changes_count"] == 2

    def test_num_temp_changes(self, gf):
        assert gf["num_temp_changes"] >= 1  # M104 / M109

    def test_first_layer_temp(self, gf):
        assert gf["first_layer_temp"] == 230.0

    def test_estimated_time_positive(self, gf):
        assert gf["estimated_print_time_s"] > 0


class TestLayerFeatures:
    def test_layer_df_shape(self, layer_df):
        assert len(layer_df) == 3
        assert "z" in layer_df.columns

    def test_z_values(self, layer_df):
        zs = list(layer_df["z"].round(3))
        assert zs == [0.200, 0.500, 0.800]

    def test_retract_count_per_layer(self, layer_df):
        """Layer 0 and 1 each have 1 retract; layer 2 has 0."""
        counts = list(layer_df["retract_count"])
        assert counts[0] == 1
        assert counts[1] == 1
        assert counts[2] == 0

    def test_wipe_blocks_per_layer(self, layer_df):
        wipes = list(layer_df["wipe_blocks_count"])
        assert wipes[0] == 1
        assert wipes[1] == 1
        assert wipes[2] == 0

    def test_extrude_path_positive(self, layer_df):
        assert (layer_df["extrude_path_mm"] > 0).all()


# ===========================================================================
# Manifest test
# ===========================================================================

class TestManifest:
    def test_manifest_contains_table(self):
        m = generate_manifest()
        assert "| Name |" in m
        assert "num_layers" in m
        assert "seam_dispersion" in m
        assert "linear_advance" in m

    def test_manifest_has_all_levels(self):
        m = generate_manifest()
        assert "| declared |" in m
        assert "| global |" in m
        assert "| layer |" in m
