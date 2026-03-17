"""
Feature Engineering for G-Code Parse Results.

Produces three output levels:
  A) global_features  – dict with all hidden/derived metrics
  B) layer_features   – pandas DataFrame, one row per layer
  C) declared_settings– dict (passed through from parser)

New feature groups (v2):
  A) Thermal History Proxies
  B) Bonding Quality Proxies
  C) Structural Orientation Features
  D) Energy / Material Flow Proxies
  E) Robust Specimen-Level Aggregation  (specimen_features dict)
  F) Artifact Filtering (layer_id < 0, S0 temps, short segments)

Also provides:
  generate_manifest() – returns feature_manifest.md as a string
  segments_to_df()    – converts segment list to pandas DataFrame
"""

import io
import math
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from .parser import (
    ParseResult, MoveSegment, Event, LayerInfo,
    EVT_LAYER_CHANGE, EVT_TEMP_NOZZLE, EVT_TEMP_BED, EVT_FAN,
    EVT_PROGRESS, EVT_ACCEL_MAX, EVT_FEEDRATE_MAX, EVT_ACCEL_SET,
    EVT_JERK_LIMITS, EVT_LINEAR_ADVANCE, EVT_G92_RESET,
    EVT_WIPE_START, EVT_WIPE_END,
)


# ---------------------------------------------------------------------------
# Numeric helpers
# ---------------------------------------------------------------------------

def _mean(lst) -> float:
    return float(np.mean(lst)) if lst else 0.0


def _median(lst) -> float:
    return float(np.median(lst)) if lst else 0.0


def _pct(lst, p: float) -> float:
    return float(np.percentile(lst, p)) if lst else 0.0


def _std(lst) -> float:
    return float(np.std(lst)) if len(lst) > 1 else 0.0


def _r(val, n: int = 4) -> float:
    """Round a float to n decimal places, handling None."""
    if val is None:
        return None
    return round(float(val), n)


def _safe_div(num: float, denom: float, default: float = 0.0) -> float:
    """Division guarded against near-zero denominator."""
    return num / denom if abs(denom) > 1e-9 else default


# ---------------------------------------------------------------------------
# Anisotropy
# ---------------------------------------------------------------------------

def _compute_anisotropy(angles: List[float], n_bins: int = 18) -> float:
    """
    Compute directional anisotropy score from a list of move angles (degrees).

    Angles are folded into [0, 180) so that opposite directions are equivalent
    (line symmetry).  Returns 0.0 (isotropic/uniform) → 1.0 (all one direction).
    """
    if not angles:
        return 0.0
    folded = [a % 180.0 for a in angles]
    hist, _ = np.histogram(folded, bins=n_bins, range=(0.0, 180.0))
    total = hist.sum()
    if total == 0:
        return 0.0
    probs = hist / total
    probs = probs[probs > 0]
    entropy = float(-np.sum(probs * np.log(probs)))
    max_entropy = math.log(n_bins)
    return 0.0 if max_entropy == 0 else float(1.0 - entropy / max_entropy)


def _angle_histogram(angles: List[float], n_bins: int = 18) -> Dict[str, int]:
    if not angles:
        return {}
    folded = [a % 180.0 for a in angles]
    hist, edges = np.histogram(folded, bins=n_bins, range=(0.0, 180.0))
    return {
        f"{int(edges[i])}-{int(edges[i+1])}°": int(hist[i])
        for i in range(len(hist))
    }


# ---------------------------------------------------------------------------
# C) Structural orientation helpers
# ---------------------------------------------------------------------------

def _dominant_infill_angle(angles: List[float]) -> float:
    """Dominant angle (mode bin centre) for infill segments, folded to [0,180)."""
    if not angles:
        return 0.0
    folded = [a % 180.0 for a in angles]
    hist, edges = np.histogram(folded, bins=18, range=(0.0, 180.0))
    idx = int(np.argmax(hist))
    return float((edges[idx] + edges[idx + 1]) / 2.0)


def _angle_dispersion(angles: List[float]) -> float:
    """Circular standard deviation of folded [0,180) angles (in degrees)."""
    if len(angles) < 2:
        return 0.0
    folded = np.array([a % 180.0 for a in angles], dtype=float)
    rad = np.deg2rad(2 * folded)  # double angle to handle 180° periodicity
    mean_sin = np.mean(np.sin(rad))
    mean_cos = np.mean(np.cos(rad))
    R = math.sqrt(mean_sin**2 + mean_cos**2)
    R = min(R, 1.0)
    circ_std_rad = math.sqrt(-2.0 * math.log(R)) if R > 0 else math.pi
    return float(math.degrees(circ_std_rad) / 2.0)  # back to [0,180) scale


def _alignment_score_x(angles: List[float]) -> float:
    """
    Estimated load alignment score assuming tensile direction = X axis (0°/180°).
    Score = fraction of angle weight aligned within ±22.5° of X axis.
    Range [0,1]; 1 = perfect X alignment.
    """
    if not angles:
        return 0.0
    folded = np.array([a % 180.0 for a in angles], dtype=float)
    # distance from 0° (or 180°)
    dist = np.minimum(folded, 180.0 - folded)
    aligned = float(np.sum(dist <= 22.5)) / len(folded)
    return aligned


# ---------------------------------------------------------------------------
# Global feature extraction
# ---------------------------------------------------------------------------

def extract_global_features(result: ParseResult) -> Dict[str, Any]:
    segs   = result.segments
    events = result.events
    layers = result.layer_info

    extrude_segs = [s for s in segs if s.is_extrude]
    travel_segs  = [s for s in segs if s.is_travel]
    retract_segs = [s for s in segs if s.is_retract]
    wipe_segs    = [s for s in segs if s.in_wipe]

    # Print-phase segments only (layer_id >= 0)
    print_extrude = [s for s in extrude_segs if s.layer_id >= 0]
    print_travel  = [s for s in travel_segs  if s.layer_id >= 0]
    print_retract = [s for s in retract_segs if s.layer_id >= 0]

    # ----- Counts -----
    num_layers           = len(layers)
    num_segments_total   = len(segs)
    num_extrude_segments = len(extrude_segs)
    num_travel_segments  = len(travel_segs)
    num_retract_segments = len(retract_segs)
    num_wipe_blocks      = result.wipe_count
    num_layer_changes    = len([e for e in events if e.event_type == EVT_LAYER_CHANGE])
    num_g92_resets       = result.g92_reset_count

    # ----- Distances -----
    total_travel_mm      = sum(s.length_mm for s in travel_segs)
    total_extrude_path_mm = sum(s.length_mm for s in extrude_segs)
    travel_to_extrude_ratio = _safe_div(total_travel_mm, total_extrude_path_mm)
    total_z_travel_mm = sum(abs(s.delta_xyz[2]) for s in segs)

    # ----- Extrusion proxies -----
    total_e_pos = sum(s.e_delta for s in segs if s.e_delta > 0)
    total_e_neg = sum(abs(s.e_delta) for s in segs if s.e_delta < 0)

    e_per_mm_list = [
        s.e_delta / s.length_mm
        for s in extrude_segs if s.length_mm > 0.01
    ]
    mean_e_per_mm   = _mean(e_per_mm_list)
    median_e_per_mm = _median(e_per_mm_list)
    p95_e_per_mm    = _pct(e_per_mm_list, 95)

    # E per mm by section type
    types = sorted({s.section_type for s in extrude_segs if s.section_type})
    e_per_mm_by_type: Dict[str, Any] = {}
    for t in types:
        vals = [
            s.e_delta / s.length_mm
            for s in extrude_segs
            if s.section_type == t and s.length_mm > 0.01
        ]
        if vals:
            e_per_mm_by_type[t] = {
                "mean":   _r(_mean(vals), 6),
                "median": _r(_median(vals), 6),
                "p95":    _r(_pct(vals, 95), 6),
                "count":  len(vals),
            }

    # Short extrusion rate (>= 0.2 mm threshold for artifact filtering)
    n_ext = len(extrude_segs) or 1
    short_extrusion_rate_05mm = sum(1 for s in extrude_segs if s.length_mm < 0.5) / n_ext
    short_extrusion_rate_1mm  = sum(1 for s in extrude_segs if s.length_mm < 1.0) / n_ext

    # ----- Retraction -----
    retraction_count      = len(retract_segs)
    retract_lengths       = [abs(s.e_delta) for s in retract_segs]
    retract_speeds        = [s.f for s in retract_segs if s.f > 0]
    retraction_length_mean   = _mean(retract_lengths)
    retraction_length_median = _median(retract_lengths)
    retraction_length_p95    = _pct(retract_lengths, 95)
    retraction_speed_mean    = _mean(retract_speeds)
    retraction_speed_p95     = _pct(retract_speeds, 95)
    retracts_per_meter = _safe_div(retraction_count, total_extrude_path_mm / 1000.0)
    retract_in_wipe = sum(1 for s in retract_segs if s.in_wipe)
    retract_wipe_correlation = _safe_div(retract_in_wipe, retraction_count)

    # ----- Wipe -----
    wipe_path_segs        = [s for s in wipe_segs if not s.is_retract]
    wipe_total_path_mm    = sum(s.length_mm for s in wipe_path_segs)
    wipe_total_time_est_s = sum(s.time_est_s for s in wipe_segs)

    wipe_start_events    = [e for e in events if e.event_type == EVT_WIPE_START]
    wipe_per_layer: Dict[int, int] = {}
    for e in wipe_start_events:
        wipe_per_layer[e.layer_id] = wipe_per_layer.get(e.layer_id, 0) + 1
    wipe_blocks_per_layer_mean = _mean(list(wipe_per_layer.values()))
    wipe_extrusion_in_wipe_count = sum(1 for s in wipe_segs if s.is_extrude)

    # ----- Dynamics / motion constraints -----
    accel_set_events  = [e for e in events if e.event_type == EVT_ACCEL_SET]
    accel_all_vals    = [
        v for e in accel_set_events for k, v in e.data.items()
    ]
    accel_changes_count  = len(accel_set_events)
    accel_unique_values  = sorted(set(accel_all_vals))
    accel_last_value     = accel_all_vals[-1] if accel_all_vals else None

    jerk_events  = [e for e in events if e.event_type == EVT_JERK_LIMITS]
    jerk_last: Dict[str, Optional[float]] = {"X": None, "Y": None, "Z": None, "E": None}
    for e in jerk_events:
        for ax in ("X", "Y", "Z", "E"):
            if ax in e.data:
                jerk_last[ax] = e.data[ax]

    fr_max_events  = [e for e in events if e.event_type == EVT_FEEDRATE_MAX]
    feedrate_max_last: Dict[str, float] = {}
    for e in fr_max_events:
        feedrate_max_last.update({k: v for k, v in e.data.items()})

    accel_max_events  = [e for e in events if e.event_type == EVT_ACCEL_MAX]
    accel_max_last: Dict[str, float] = {}
    for e in accel_max_events:
        accel_max_last.update({k: v for k, v in e.data.items()})

    # Feedrate variability
    f_ext   = [s.f for s in extrude_segs if s.f > 0]
    f_trav  = [s.f for s in travel_segs  if s.f > 0]
    f_ext_mean = _mean(f_ext)
    feedrate_std_extrude = _std(f_ext)
    feedrate_cv_extrude  = _safe_div(feedrate_std_extrude, f_ext_mean)
    feedrate_std_travel  = _std(f_trav)

    # Speed-jump proxy: fraction of consecutive moves with |ΔF|/F_prev > 50 %
    all_f = [s.f for s in segs if s.f > 0]
    jumps = sum(
        1 for i in range(1, len(all_f))
        if all_f[i - 1] > 0 and abs(all_f[i] - all_f[i - 1]) / all_f[i - 1] > 0.5
    )
    speed_jump_rate = jumps / len(all_f) if all_f else 0.0

    # ----- Temperature (filter S=0 cooldown commands) -----
    nozzle_evts = [e for e in events if e.event_type == EVT_TEMP_NOZZLE]
    bed_evts    = [e for e in events if e.event_type == EVT_TEMP_BED]
    nozzle_seq  = [(e.layer_id, e.data.get("setpoint")) for e in nozzle_evts
                   if e.data.get("setpoint") is not None]
    bed_seq     = [(e.layer_id, e.data.get("setpoint")) for e in bed_evts
                   if e.data.get("setpoint") is not None]
    # Exclude S=0 (cooldown) for statistics
    nozzle_vals_nonzero = [v for _, v in nozzle_seq if v > 0]
    nozzle_vals = [v for _, v in nozzle_seq]
    num_temp_changes    = len(nozzle_evts)
    first_layer_temp    = nozzle_vals[0] if nozzle_vals else None
    mean_nozzle_setpoint = _mean(nozzle_vals_nonzero)
    last_nozzle_setpoint = nozzle_vals[-1] if nozzle_vals else None

    # ----- Progress / time -----
    prog_evts            = [e for e in events if e.event_type == EVT_PROGRESS]
    m73_count            = len(prog_evts)
    estimated_print_time_s = sum(s.time_est_s for s in segs)
    time_travel  = sum(s.time_est_s for s in travel_segs)
    time_extrude = sum(s.time_est_s for s in extrude_segs)
    time_share_travel  = _safe_div(time_travel, estimated_print_time_s)
    time_share_extrude = _safe_div(time_extrude, estimated_print_time_s)

    # ----- Infill anisotropy (global) -----
    infill_segs   = [
        s for s in extrude_segs
        if s.section_type and 'infill' in s.section_type.lower()
        and s.length_mm > 0.5
    ]
    infill_angles = [s.angle_deg for s in infill_segs]
    infill_anisotropy_score = _compute_anisotropy(infill_angles)
    infill_angle_bins       = _angle_histogram(infill_angles)

    # ----- Seam proxy -----
    seam_points = []
    for layer in layers:
        lid = layer.layer_id
        l_ext = [s for s in extrude_segs if s.layer_id == lid]
        if l_ext:
            seam_points.append(l_ext[0].start_xyz[:2])

    if len(seam_points) >= 2:
        pts      = np.array(seam_points, dtype=float)
        centroid = pts.mean(axis=0)
        dists    = np.sqrt(((pts - centroid) ** 2).sum(axis=1))
        seam_dispersion_mean_mm = float(dists.mean())
        seam_dispersion_std_mm  = float(dists.std())
    else:
        seam_dispersion_mean_mm = 0.0
        seam_dispersion_std_mm  = 0.0

    # ----- Linear advance summary -----
    la_vals  = result.declared_settings.get("linear_advance_values", [])
    la_k     = [v["K"] for v in la_vals if v.get("K") is not None]
    la_summary = {
        "count":        len(la_k),
        "unique_values": sorted(set(la_k)),
        "first_value":  la_k[0]  if la_k else None,
        "last_value":   la_k[-1] if la_k else None,
        "min_value":    min(la_k) if la_k else None,
        "max_value":    max(la_k) if la_k else None,
    }

    # ===========================================================================
    # A) Thermal History Proxies – global aggregates
    # ===========================================================================

    # Layer time list (print phase only: layer_id >= 0)
    layer_times_all = _layer_times_list(result)  # indexed by layer position

    mean_layer_time = _mean(layer_times_all)
    std_layer_time  = _std(layer_times_all)

    n_layers = len(layer_times_all)

    # Cooling time between layers: estimated from layer-end to layer-start.
    # We approximate it as the time from the last segment of layer i to the
    # first segment of layer i+1 using a fixed travel speed heuristic.
    # Since we only have G-code move times (no temperature sensor data),
    # we use the gap between cumulative print times at consecutive layer boundaries.
    cumulative_times = _cumulative_layer_times(layer_times_all)

    # Cooling time between consecutive layers (inter-layer travel/pause time)
    # In pure G-code without temperature waits between layers the cooling is
    # implicitly zero from the file perspective; we model it as 0 here and
    # leave the field populated for real multi-process slicers.
    cooling_times: List[float] = []
    for i in range(1, len(layer_times_all)):
        # Cooling = time not accounted for within layer (no explicit pause → 0)
        # Kept for future extension with temperature wait blocks.
        cooling_times.append(0.0)

    mean_cooling_time = _mean(cooling_times) if cooling_times else 0.0
    std_cooling_time  = _std(cooling_times) if cooling_times else 0.0

    # Early / mid / late layer time means
    early_layer_time_mean = _mean(layer_times_all[:3])
    if n_layers >= 6:
        mid_start = n_layers // 3
        mid_end   = 2 * n_layers // 3
        mid_layer_time_mean = _mean(layer_times_all[mid_start:mid_end])
    elif n_layers >= 3:
        mid_layer_time_mean = _mean(layer_times_all[1:-1])
    else:
        mid_layer_time_mean = mean_layer_time
    late_layer_time_mean = _mean(layer_times_all[-3:]) if n_layers >= 3 else mean_layer_time

    thermal_global = {
        "mean_layer_time":       _r(mean_layer_time, 3),
        "std_layer_time":        _r(std_layer_time, 3),
        "mean_cooling_time":     _r(mean_cooling_time, 3),
        "std_cooling_time":      _r(std_cooling_time, 3),
        "early_layer_time_mean": _r(early_layer_time_mean, 3),
        "mid_layer_time_mean":   _r(mid_layer_time_mean, 3),
        "late_layer_time_mean":  _r(late_layer_time_mean, 3),
    }

    # ===========================================================================
    # B) Bonding Quality Proxies – global
    # ===========================================================================

    # Use print-phase segments with minimum length filter (>= 0.2 mm)
    pe_segs = [s for s in print_extrude if s.length_mm >= 0.2]
    pt_segs = [s for s in print_travel  if s.length_mm >= 0.2]

    mean_ext_len  = _mean([s.length_mm for s in pe_segs])
    mean_trav_len = _mean([s.length_mm for s in pt_segs])
    extrusion_continuity_index = _safe_div(mean_ext_len, mean_trav_len)

    pr_extrude_path = sum(s.length_mm for s in pe_segs)
    interruption_density = _safe_div(len(print_retract), pr_extrude_path)

    n_pe = len(pe_segs) or 1
    short_ext_ratio = sum(1 for s in pe_segs if s.length_mm < 1.0) / n_pe

    # Perimeter-to-infill ratio (path length based)
    perim_mm  = sum(s.length_mm for s in pe_segs
                    if s.section_type and 'perimeter' in s.section_type.lower())
    infill_mm = sum(s.length_mm for s in pe_segs
                    if s.section_type and 'infill' in s.section_type.lower())
    perimeter_to_infill_ratio = _safe_div(perim_mm, infill_mm)

    # Bonding disruption score: weighted sum (normalised to [0,1] range)
    # = 0.5 * retracts_per_meter_norm + 0.3 * short_ext_ratio + 0.2 * wipe_freq_norm
    # We normalise retracts_per_meter by a reference of 20 ret/m
    # and wipe_freq by mean wipe blocks per layer / 2.
    rpm_norm  = min(retracts_per_meter / 20.0, 1.0)
    wf_norm   = min(wipe_blocks_per_layer_mean / 2.0, 1.0)
    bonding_disruption_score = (
        0.5 * rpm_norm + 0.3 * short_ext_ratio + 0.2 * wf_norm
    )

    bonding_global = {
        "extrusion_continuity_index":  _r(extrusion_continuity_index, 4),
        "interruption_density":        _r(interruption_density, 6),
        "short_extrusion_ratio":       _r(short_ext_ratio, 4),
        "perimeter_to_infill_ratio":   _r(perimeter_to_infill_ratio, 4),
        "bonding_disruption_score":    _r(bonding_disruption_score, 4),
    }

    # ===========================================================================
    # C) Structural Orientation – global
    # ===========================================================================

    # Use infill segments >= 0.5 mm in print phase
    inf_segs_p = [
        s for s in print_extrude
        if s.section_type and 'infill' in s.section_type.lower()
        and s.length_mm >= 0.5
    ]
    inf_angles = [s.angle_deg for s in inf_segs_p]

    dominant_infill_angle_val      = _dominant_infill_angle(inf_angles)
    angle_dispersion_index         = _angle_dispersion(inf_angles)
    angle_alignment_x              = float(abs(math.cos(math.radians(dominant_infill_angle_val % 180.0))))
    estimated_load_alignment_score = _alignment_score_x(inf_angles)

    # Per-layer orientation variance: std of dominant angles across layers
    layer_dominant_angles = []
    for layer in layers:
        lid = layer.layer_id
        la_inf = [
            s for s in extrude_segs
            if s.layer_id == lid
            and s.section_type and 'infill' in s.section_type.lower()
            and s.length_mm >= 0.5
        ]
        if la_inf:
            layer_dominant_angles.append(_dominant_infill_angle([s.angle_deg for s in la_inf]))
    layer_orientation_variance = float(np.var(layer_dominant_angles)) if len(layer_dominant_angles) > 1 else 0.0

    orientation_global = {
        "dominant_infill_angle":           _r(dominant_infill_angle_val, 2),
        "angle_dispersion_index":          _r(angle_dispersion_index, 3),
        "angle_alignment_with_x_axis":     _r(angle_alignment_x, 4),
        "estimated_load_alignment_score":  _r(estimated_load_alignment_score, 4),
        "layer_orientation_variance":      _r(layer_orientation_variance, 4),
        "mean_alignment_score":            _r(estimated_load_alignment_score, 4),  # specimen-level alias
        "alignment_std":                   _r(_std([_alignment_score_x([s.angle_deg for s in [
            s for s in extrude_segs
            if s.layer_id == layer.layer_id
            and s.section_type and 'infill' in s.section_type.lower()
            and s.length_mm >= 0.5
        ]]) for layer in layers if any(
            s.layer_id == layer.layer_id
            and s.section_type and 'infill' in s.section_type.lower()
            and s.length_mm >= 0.5
            for s in extrude_segs
        )]), 4),
    }

    # ===========================================================================
    # D) Energy / Material Flow Proxies – global
    # ===========================================================================

    # volumetric_flow_rate_estimate per segment = e_per_mm * feedrate (mm/min)
    # proxy for mm³/min (without actual filament diameter correction)
    flow_vals = [
        (s.e_delta / s.length_mm) * s.f
        for s in extrude_segs
        if s.length_mm > 0.01 and s.f > 0
    ]
    mean_volumetric_flow = _mean(flow_vals)
    peak_volumetric_flow = max(flow_vals) if flow_vals else 0.0
    flow_std             = _std(flow_vals)
    flow_cv              = _safe_div(flow_std, mean_volumetric_flow)

    energy_global = {
        "mean_volumetric_flow":  _r(mean_volumetric_flow, 4),
        "peak_volumetric_flow":  _r(peak_volumetric_flow, 4),
        "flow_std":              _r(flow_std, 4),
        "flow_variability_index": _r(flow_cv, 4),
    }

    # ===== Assemble global feature dict =====
    return {
        # --- Counts ---
        "num_layers":           num_layers,
        "num_segments_total":   num_segments_total,
        "num_extrude_segments": num_extrude_segments,
        "num_travel_segments":  num_travel_segments,
        "num_retract_segments": num_retract_segments,
        "num_wipe_blocks":      num_wipe_blocks,
        "num_layer_changes":    num_layer_changes,
        "num_g92_resets":       num_g92_resets,

        # --- Distances ---
        "total_travel_mm":          _r(total_travel_mm, 3),
        "total_extrude_path_mm":    _r(total_extrude_path_mm, 3),
        "travel_to_extrude_ratio":  _r(travel_to_extrude_ratio, 4),
        "total_z_travel_mm":        _r(total_z_travel_mm, 4),

        # --- Extrusion ---
        "total_e_pos":                _r(total_e_pos, 4),
        "total_e_neg":                _r(total_e_neg, 4),
        "mean_e_per_mm":              _r(mean_e_per_mm, 6),
        "median_e_per_mm":            _r(median_e_per_mm, 6),
        "p95_e_per_mm":               _r(p95_e_per_mm, 6),
        "e_per_mm_by_type":           e_per_mm_by_type,
        "short_extrusion_rate_05mm":  _r(short_extrusion_rate_05mm, 4),
        "short_extrusion_rate_1mm":   _r(short_extrusion_rate_1mm, 4),

        # --- Retraction ---
        "retraction_count":           retraction_count,
        "retraction_length_mean":     _r(retraction_length_mean, 5),
        "retraction_length_median":   _r(retraction_length_median, 5),
        "retraction_length_p95":      _r(retraction_length_p95, 5),
        "retraction_speed_mean":      _r(retraction_speed_mean, 2),
        "retraction_speed_p95":       _r(retraction_speed_p95, 2),
        "retracts_per_meter":         _r(retracts_per_meter, 3),
        "retract_wipe_correlation":   _r(retract_wipe_correlation, 4),

        # --- Wipe ---
        "wipe_total_path_mm":           _r(wipe_total_path_mm, 3),
        "wipe_total_time_est_s":        _r(wipe_total_time_est_s, 3),
        "wipe_blocks_per_layer_mean":   _r(wipe_blocks_per_layer_mean, 3),
        "wipe_extrusion_in_wipe_count": wipe_extrusion_in_wipe_count,

        # --- Dynamics ---
        "accel_changes_count":  accel_changes_count,
        "accel_unique_values":  accel_unique_values,
        "accel_last_value":     accel_last_value,
        "jerk_limits_last":     jerk_last,
        "feedrate_max_last":    feedrate_max_last,
        "accel_max_last":       accel_max_last,
        "feedrate_std_extrude": _r(feedrate_std_extrude, 2),
        "feedrate_cv_extrude":  _r(feedrate_cv_extrude, 4),
        "feedrate_std_travel":  _r(feedrate_std_travel, 2),
        "speed_jump_rate":      _r(speed_jump_rate, 4),

        # --- Temperature ---
        "nozzle_setpoints_sequence": nozzle_seq,
        "bed_setpoints_sequence":    bed_seq,
        "num_temp_changes":          num_temp_changes,
        "first_layer_temp":          first_layer_temp,
        "mean_nozzle_setpoint":      _r(mean_nozzle_setpoint, 2),
        "last_nozzle_setpoint":      last_nozzle_setpoint,

        # --- Progress / time ---
        "m73_count":               m73_count,
        "estimated_print_time_s":  _r(estimated_print_time_s, 2),
        "time_share_travel":       _r(time_share_travel, 4),
        "time_share_extrude":      _r(time_share_extrude, 4),

        # --- Directionality ---
        "infill_anisotropy_score": _r(infill_anisotropy_score, 4),
        "infill_angle_bins":       infill_angle_bins,

        # --- Seam ---
        "seam_dispersion_mean_mm": _r(seam_dispersion_mean_mm, 3),
        "seam_dispersion_std_mm":  _r(seam_dispersion_std_mm, 3),

        # --- Linear advance ---
        "linear_advance_summary":  la_summary,

        # --- A) Thermal history (global) ---
        "thermal_history": thermal_global,

        # --- B) Bonding quality (global) ---
        "bonding_quality": bonding_global,

        # --- C) Structural orientation (global) ---
        "structural_orientation": orientation_global,

        # --- D) Energy / flow (global) ---
        "energy_flow": energy_global,
    }


# ---------------------------------------------------------------------------
# Internal helpers for layer time sequences
# ---------------------------------------------------------------------------

def _layer_times_list(result: ParseResult) -> List[float]:
    """Return estimated print time per layer, for layer_id >= 0 only."""
    segs   = result.segments
    layers = result.layer_info
    times  = []
    for layer in layers:
        lid = layer.layer_id
        if lid < 0:
            continue
        t = sum(s.time_est_s for s in segs if s.layer_id == lid)
        times.append(t)
    return times


def _cumulative_layer_times(layer_times: List[float]) -> List[float]:
    """Return cumulative sum of layer times."""
    cum = []
    total = 0.0
    for t in layer_times:
        total += t
        cum.append(total)
    return cum


# ---------------------------------------------------------------------------
# Layer feature extraction
# ---------------------------------------------------------------------------

def extract_layer_features(result: ParseResult) -> pd.DataFrame:
    """Return one row per layer with all per-layer metrics."""
    segs   = result.segments
    events = result.events
    layers = result.layer_info

    if not layers:
        return pd.DataFrame()

    # Index events by layer for fast lookup
    wipe_start_by_layer: Dict[int, int] = {}
    for e in events:
        if e.event_type == EVT_WIPE_START:
            wipe_start_by_layer[e.layer_id] = (
                wipe_start_by_layer.get(e.layer_id, 0) + 1
            )

    # Pre-compute layer times for thermal features
    layer_times_all = _layer_times_list(result)
    mean_lt = _mean(layer_times_all) if layer_times_all else 1.0
    cumulative_times = _cumulative_layer_times(layer_times_all)

    rows = []
    for idx, layer in enumerate(layers):
        lid = layer.layer_id
        if lid < 0:
            # Still include pre-print layer with zeros so layer_id is preserved
            rows.append(_empty_layer_row(lid, layer))
            continue

        l_segs   = [s for s in segs if s.layer_id == lid]
        l_ext    = [s for s in l_segs if s.is_extrude]
        l_trav   = [s for s in l_segs if s.is_travel]
        l_ret    = [s for s in l_segs if s.is_retract]

        extrude_path_mm = sum(s.length_mm for s in l_ext)
        travel_mm       = sum(s.length_mm for s in l_trav)
        ratio           = _safe_div(extrude_path_mm, travel_mm)

        total_e_pos = sum(s.e_delta for s in l_segs if s.e_delta > 0)
        total_e_neg = sum(abs(s.e_delta) for s in l_segs if s.e_delta < 0)

        retract_lens   = [abs(s.e_delta) for s in l_ret]
        mean_ret_len   = _mean(retract_lens)

        f_ext  = [s.f for s in l_ext  if s.f > 0]
        f_trav = [s.f for s in l_trav if s.f > 0]
        mean_F_extrude = _mean(f_ext)
        p95_F_extrude  = _pct(f_ext, 95)
        mean_F_travel  = _mean(f_trav)

        layer_time_est_s = sum(s.time_est_s for s in l_segs)

        # Infill anisotropy
        inf_segs  = [s for s in l_ext
                     if s.section_type and 'infill' in s.section_type.lower()
                     and s.length_mm > 0.5]
        anisotropy = _compute_anisotropy([s.angle_deg for s in inf_segs])

        # Seam proxy: distance of first extrusion start from layer centroid
        if l_ext:
            first_pt = np.array(l_ext[0].start_xyz[:2], dtype=float)
            all_pts  = np.array([s.start_xyz[:2] for s in l_ext], dtype=float)
            centroid = all_pts.mean(axis=0)
            startpoint_dispersion = float(np.linalg.norm(first_pt - centroid))
        else:
            startpoint_dispersion = 0.0

        # ===========================================================
        # A) Thermal history per layer
        # ===========================================================
        # idx in layer_times_all corresponds to layer position (lid >= 0)
        lt_idx = lid  # since layer_id == sequential index for lid >= 0
        lt_idx = min(lt_idx, len(layer_times_all) - 1)

        cumulative_print_time = cumulative_times[lt_idx] if lt_idx < len(cumulative_times) else 0.0
        relative_layer_time   = _safe_div(layer_time_est_s, mean_lt if mean_lt > 0 else 1.0)

        # Rolling mean (window=3) of layer times up to this layer
        win_start = max(0, lt_idx - 2)
        rolling_mean_lt = _mean(layer_times_all[win_start: lt_idx + 1])

        # Layer time gradient vs previous
        if lt_idx > 0 and lt_idx - 1 < len(layer_times_all):
            lt_gradient = layer_time_est_s - layer_times_all[lt_idx - 1]
        else:
            lt_gradient = 0.0

        # Extrusion time share within this layer
        ext_time = sum(s.time_est_s for s in l_ext)
        norm_ext_time_share = _safe_div(ext_time, layer_time_est_s)

        # ===========================================================
        # B) Bonding quality per layer
        # ===========================================================
        # Use >= 0.2 mm segments to avoid artifact noise
        pe_segs_l = [s for s in l_ext  if s.length_mm >= 0.2]
        pt_segs_l = [s for s in l_trav if s.length_mm >= 0.2]

        me_l = _mean([s.length_mm for s in pe_segs_l])
        mt_l = _mean([s.length_mm for s in pt_segs_l])
        ext_cont_idx_l = _safe_div(me_l, mt_l)

        pr_ext_mm_l = sum(s.length_mm for s in pe_segs_l)
        interr_density_l = _safe_div(len(l_ret), pr_ext_mm_l)

        n_pe_l = len(pe_segs_l) or 1
        short_ext_ratio_l = sum(1 for s in pe_segs_l if s.length_mm < 1.0) / n_pe_l

        # Interface density: count TYPE transitions in this layer
        types_seq = [s.section_type for s in l_segs if s.section_type]
        interface_density_l = sum(
            1 for i in range(1, len(types_seq)) if types_seq[i] != types_seq[i - 1]
        )

        # ===========================================================
        # C) Structural orientation per layer
        # ===========================================================
        inf_angles_l = [s.angle_deg for s in inf_segs]
        dom_angle_l     = _dominant_infill_angle(inf_angles_l)
        align_score_l   = _alignment_score_x(inf_angles_l)

        # ===========================================================
        # D) Energy / flow per layer
        # ===========================================================
        flow_vals_l = [
            (s.e_delta / s.length_mm) * s.f
            for s in l_ext if s.length_mm > 0.01 and s.f > 0
        ]
        vol_flow_l     = _mean(flow_vals_l)
        layer_energy_l = vol_flow_l * layer_time_est_s
        flow_var_l     = _safe_div(_std(flow_vals_l), _mean(flow_vals_l) if flow_vals_l else 1.0)

        rows.append({
            # ---- existing features ----
            "layer_id":              lid,
            "z":                     layer.z,
            "height":                layer.height,
            "layer_time_est_s":      _r(layer_time_est_s, 3),
            "extrude_path_mm":       _r(extrude_path_mm, 3),
            "travel_mm":             _r(travel_mm, 3),
            "extrude_travel_ratio":  _r(ratio, 4),
            "total_e_pos":           _r(total_e_pos, 5),
            "total_e_neg":           _r(total_e_neg, 5),
            "retract_count":         len(l_ret),
            "mean_retract_len":      _r(mean_ret_len, 5),
            "wipe_blocks_count":     wipe_start_by_layer.get(lid, 0),
            "mean_F_extrude":        _r(mean_F_extrude, 2),
            "p95_F_extrude":         _r(p95_F_extrude, 2),
            "mean_F_travel":         _r(mean_F_travel, 2),
            "anisotropy_score_infill": _r(anisotropy, 4),
            "startpoint_dispersion": _r(startpoint_dispersion, 3),

            # ---- A) Thermal history ----
            "cumulative_print_time_s":    _r(cumulative_print_time, 3),
            "relative_layer_time":        _r(relative_layer_time, 4),
            "rolling_mean_layer_time":    _r(rolling_mean_lt, 3),
            "layer_time_gradient":        _r(lt_gradient, 4),
            "norm_extrusion_time_share":  _r(norm_ext_time_share, 4),

            # ---- B) Bonding quality ----
            "extrusion_continuity_index": _r(ext_cont_idx_l, 4),
            "interruption_density":       _r(interr_density_l, 6),
            "short_extrusion_ratio":      _r(short_ext_ratio_l, 4),
            "interface_density":          interface_density_l,

            # ---- C) Structural orientation ----
            "dominant_infill_angle":      _r(dom_angle_l, 2),
            "load_alignment_score":       _r(align_score_l, 4),

            # ---- D) Energy / flow ----
            "volumetric_flow_rate_est":   _r(vol_flow_l, 4),
            "layer_energy_proxy":         _r(layer_energy_l, 4),
            "flow_variability_index":     _r(flow_var_l, 4),
        })

    return pd.DataFrame(rows)


def _empty_layer_row(lid: int, layer: "LayerInfo") -> Dict[str, Any]:
    """Return a zero-filled row for pre-print layers (layer_id < 0)."""
    return {
        "layer_id": lid, "z": layer.z, "height": layer.height,
        "layer_time_est_s": 0.0, "extrude_path_mm": 0.0, "travel_mm": 0.0,
        "extrude_travel_ratio": 0.0, "total_e_pos": 0.0, "total_e_neg": 0.0,
        "retract_count": 0, "mean_retract_len": 0.0, "wipe_blocks_count": 0,
        "mean_F_extrude": 0.0, "p95_F_extrude": 0.0, "mean_F_travel": 0.0,
        "anisotropy_score_infill": 0.0, "startpoint_dispersion": 0.0,
        "cumulative_print_time_s": 0.0, "relative_layer_time": 0.0,
        "rolling_mean_layer_time": 0.0, "layer_time_gradient": 0.0,
        "norm_extrusion_time_share": 0.0, "extrusion_continuity_index": 0.0,
        "interruption_density": 0.0, "short_extrusion_ratio": 0.0,
        "interface_density": 0, "dominant_infill_angle": 0.0,
        "load_alignment_score": 0.0, "volumetric_flow_rate_est": 0.0,
        "layer_energy_proxy": 0.0, "flow_variability_index": 0.0,
    }


# ---------------------------------------------------------------------------
# E) Specimen-level aggregation
# ---------------------------------------------------------------------------

_LAYER_NUMERIC_FEATURES = [
    "layer_time_est_s", "extrude_path_mm", "travel_mm", "extrude_travel_ratio",
    "total_e_pos", "total_e_neg", "retract_count", "mean_retract_len",
    "wipe_blocks_count", "mean_F_extrude", "p95_F_extrude", "mean_F_travel",
    "anisotropy_score_infill", "startpoint_dispersion",
    "relative_layer_time", "rolling_mean_layer_time", "layer_time_gradient",
    "norm_extrusion_time_share", "extrusion_continuity_index",
    "interruption_density", "short_extrusion_ratio", "interface_density",
    "dominant_infill_angle", "load_alignment_score",
    "volumetric_flow_rate_est", "layer_energy_proxy", "flow_variability_index",
]


def extract_specimen_features(layer_df: pd.DataFrame) -> Dict[str, Any]:
    """
    Aggregate layer-level features into specimen-level statistics.

    For each numeric layer feature compute:
      mean, std, p90, p10, early_mean (layers 0-2), mid_mean, late_mean (last 3).

    Pre-print layers (layer_id < 0) are excluded.
    Returns a flat dict: {feature_name__stat: value, ...}
    """
    # Filter to print phase
    if layer_df.empty or "layer_id" not in layer_df.columns:
        return {}
    df = layer_df[layer_df["layer_id"] >= 0].copy()
    if df.empty:
        return {}

    n = len(df)
    early_mask = df.index[:min(3, n)]
    late_mask  = df.index[max(0, n - 3):]
    if n >= 6:
        mid_mask = df.index[n // 3: 2 * n // 3]
    elif n >= 3:
        mid_mask = df.index[1:-1]
    else:
        mid_mask = df.index

    specimen: Dict[str, Any] = {}
    for feat in _LAYER_NUMERIC_FEATURES:
        if feat not in df.columns:
            continue
        col = df[feat].dropna()
        if col.empty:
            continue
        vals = col.values.astype(float)
        early_vals = df.loc[early_mask, feat].dropna().values.astype(float)
        mid_vals   = df.loc[mid_mask,   feat].dropna().values.astype(float)
        late_vals  = df.loc[late_mask,  feat].dropna().values.astype(float)

        specimen[f"{feat}__mean"]       = _r(float(np.mean(vals)), 4)
        specimen[f"{feat}__std"]        = _r(float(np.std(vals)), 4)
        specimen[f"{feat}__p90"]        = _r(float(np.percentile(vals, 90)), 4)
        specimen[f"{feat}__p10"]        = _r(float(np.percentile(vals, 10)), 4)
        specimen[f"{feat}__early_mean"] = _r(float(np.mean(early_vals)) if len(early_vals) else 0.0, 4)
        specimen[f"{feat}__mid_mean"]   = _r(float(np.mean(mid_vals))   if len(mid_vals)   else 0.0, 4)
        specimen[f"{feat}__late_mean"]  = _r(float(np.mean(late_vals))  if len(late_vals)  else 0.0, 4)

    return specimen


# ---------------------------------------------------------------------------
# Segments → DataFrame
# ---------------------------------------------------------------------------

def segments_to_df(result: ParseResult) -> pd.DataFrame:
    """Flatten all MoveSegment fields into a tidy DataFrame."""
    rows = []
    for s in result.segments:
        rows.append({
            "line_no":        s.line_no,
            "layer_id":       s.layer_id,
            "section_type":   s.section_type,
            "width_mm":       s.width_mm,
            "start_x":        s.start_xyz[0],
            "start_y":        s.start_xyz[1],
            "start_z":        s.start_xyz[2],
            "end_x":          s.end_xyz[0],
            "end_y":          s.end_xyz[1],
            "end_z":          s.end_xyz[2],
            "e_delta":        s.e_delta,
            "f":              s.f,
            "length_mm":      s.length_mm,
            "length_xyz_mm":  s.length_xyz_mm,
            "angle_deg":      s.angle_deg,
            "is_travel":      s.is_travel,
            "is_extrude":     s.is_extrude,
            "is_retract":     s.is_retract,
            "is_z_hop":       s.is_z_hop,
            "in_wipe":        s.in_wipe,
            "time_est_s":     s.time_est_s,
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Feature manifest
# ---------------------------------------------------------------------------

MANIFEST_ROWS = [
    # (name, level, unit, definition, dependencies)
    # --- declared settings ---
    ("generated_by",         "declared", "string", "Slicer software and version",                "Header comment"),
    ("timestamp",            "declared", "string", "Timestamp from slicer header",               "Header comment"),
    ("printer_model",        "declared", "string", "Printer model from M862.3 P check",         "M862.3"),
    ("nozzle_diameter",      "declared", "mm",     "Nozzle diameter from M862.1 P check",       "M862.1"),
    ("filament_type",        "declared", "string", "Filament material type",                     "Header key=value"),
    ("header_settings",      "declared", "dict",   "All key=value pairs from header comments",  "Header comments"),
    ("linear_advance_values","declared", "list",   "All M900 K values with line_no and layer_id","M900"),

    # --- global counts ---
    ("num_layers",           "global", "count", "Number of distinct print layers (from ;LAYER_CHANGE)", ";LAYER_CHANGE"),
    ("num_segments_total",   "global", "count", "Total G0/G1 move segments parsed",             "G0/G1"),
    ("num_extrude_segments", "global", "count", "Segments with E_delta > 0.001 mm",             "M83 + G1 E"),
    ("num_travel_segments",  "global", "count", "Segments with no extrusion and XY movement",   "G0/G1"),
    ("num_retract_segments", "global", "count", "Segments with E_delta < -0.001 mm",            "M83 + G1 E"),
    ("num_wipe_blocks",      "global", "count", "Counted ;WIPE_START / ;WIPE_END pairs",        ";WIPE_START ;WIPE_END"),
    ("num_layer_changes",    "global", "count", "Counted ;LAYER_CHANGE markers",                ";LAYER_CHANGE"),
    ("num_g92_resets",       "global", "count", "Counted G92 E... resets",                      "G92"),

    # --- global distances ---
    ("total_travel_mm",         "global", "mm",  "Sum of XY length of all travel moves",         "G0/G1 classification"),
    ("total_extrude_path_mm",   "global", "mm",  "Sum of XY length of all extrusion moves",      "G0/G1 classification"),
    ("travel_to_extrude_ratio", "global", "–",   "total_travel_mm / total_extrude_path_mm",      "Derived"),
    ("total_z_travel_mm",       "global", "mm",  "Sum of absolute Z delta across all moves",     "G0/G1 Z"),

    # --- global extrusion ---
    ("total_e_pos",               "global", "mm", "Sum of all positive E deltas (filament pushed)", "M83"),
    ("total_e_neg",               "global", "mm", "Sum of absolute values of negative E deltas",   "M83"),
    ("mean_e_per_mm",             "global", "mm/mm", "Mean E/path_mm across extrusion segments",   "M83"),
    ("median_e_per_mm",           "global", "mm/mm", "Median E/path_mm",                           "M83"),
    ("p95_e_per_mm",              "global", "mm/mm", "95th percentile E/path_mm",                  "M83"),
    ("e_per_mm_by_type",          "global", "dict",  "E/path_mm stats grouped by ;TYPE: tag",       ";TYPE"),
    ("short_extrusion_rate_05mm", "global", "ratio", "Fraction of extrusion segs with XY < 0.5 mm","Derived"),
    ("short_extrusion_rate_1mm",  "global", "ratio", "Fraction of extrusion segs with XY < 1.0 mm","Derived"),

    # --- global retraction ---
    ("retraction_count",         "global", "count", "Number of retract moves",                    "M83"),
    ("retraction_length_mean",   "global", "mm",    "Mean |E_delta| for retract moves",            "M83"),
    ("retraction_length_median", "global", "mm",    "Median |E_delta| for retract moves",          "M83"),
    ("retraction_length_p95",    "global", "mm",    "95th pct |E_delta| for retract moves",        "M83"),
    ("retraction_speed_mean",    "global", "mm/min","Mean feedrate during retract moves",           "F param"),
    ("retraction_speed_p95",     "global", "mm/min","95th pct feedrate during retract moves",      "F param"),
    ("retracts_per_meter",       "global", "1/m",   "Retraction events per meter of extrusion",    "Derived"),
    ("retract_wipe_correlation", "global", "ratio", "Fraction of retracts occurring inside a wipe block", ";WIPE_START/END"),

    # --- global wipe ---
    ("wipe_total_path_mm",         "global", "mm",   "Total XY path during wipe blocks (excl. retract)", ";WIPE_START/END"),
    ("wipe_total_time_est_s",      "global", "s",    "Estimated time inside wipe blocks",           "time_est_s"),
    ("wipe_blocks_per_layer_mean", "global", "count","Mean wipe blocks per layer",                   ";WIPE_START"),
    ("wipe_extrusion_in_wipe_count","global","count","Count of extrude segments inside wipe blocks", "M83 + wipe"),

    # --- dynamics ---
    ("accel_changes_count",  "global", "count",   "Number of M204 (set accel) commands",          "M204"),
    ("accel_unique_values",  "global", "list",    "Unique acceleration values from M204",          "M204"),
    ("accel_last_value",     "global", "mm/s²",   "Last M204 acceleration value",                 "M204"),
    ("jerk_limits_last",     "global", "dict",    "Last M205 X/Y/Z/E jerk limits",               "M205"),
    ("feedrate_max_last",    "global", "dict",    "Last M203 max feedrate per axis",              "M203"),
    ("accel_max_last",       "global", "dict",    "Last M201 max acceleration per axis",          "M201"),
    ("feedrate_std_extrude", "global", "mm/min",  "Std dev of feedrate across extrusion moves",   "F param"),
    ("feedrate_cv_extrude",  "global", "–",       "Coefficient of variation of extrusion feedrate","Derived"),
    ("feedrate_std_travel",  "global", "mm/min",  "Std dev of feedrate across travel moves",      "F param"),
    ("speed_jump_rate",      "global", "ratio",   "Fraction of consecutive moves with |ΔF|/F>50%","Derived"),

    # --- temperature ---
    ("nozzle_setpoints_sequence","global","list", "Ordered list of (layer_id, °C) nozzle setpoints","M104/M109"),
    ("bed_setpoints_sequence",   "global","list", "Ordered list of (layer_id, °C) bed setpoints",   "M140/M190"),
    ("num_temp_changes",         "global","count","Number of M104/M109 commands",                    "M104/M109"),
    ("first_layer_temp",         "global","°C",   "First nozzle setpoint in file",                   "M104/M109"),
    ("mean_nozzle_setpoint",     "global","°C",   "Mean of all non-zero nozzle setpoint values",     "M104/M109"),
    ("last_nozzle_setpoint",     "global","°C",   "Last nozzle setpoint value in file",              "M104/M109"),

    # --- time ---
    ("m73_count",              "global","count", "Number of M73 progress/remaining-time updates",  "M73"),
    ("estimated_print_time_s", "global","s",     "Sum of segment time estimates (dist/feedrate)",  "F param"),
    ("time_share_travel",      "global","ratio", "Fraction of est. time spent in travel moves",    "Derived"),
    ("time_share_extrude",     "global","ratio", "Fraction of est. time spent in extrusion moves", "Derived"),

    # --- directionality ---
    ("infill_anisotropy_score","global","0–1",  "1=fully anisotropic, 0=uniform; entropy-based measure", ";TYPE:*infill*"),
    ("infill_angle_bins",      "global","dict", "Histogram of folded [0,180°) infill angles in 10° bins",";TYPE:*infill*"),

    # --- seam proxy ---
    ("seam_dispersion_mean_mm","global","mm",  "Mean XY distance from seam-point centroid (per-layer first extrusion start)", "Derived"),
    ("seam_dispersion_std_mm", "global","mm",  "Std dev of seam-point distances from centroid", "Derived"),

    # --- linear advance ---
    ("linear_advance_summary", "global","dict","Summary stats for all M900 K values (count/unique/min/max/first/last)","M900"),

    # --- A) Thermal history (global sub-dict) ---
    ("thermal_history.mean_layer_time",       "global", "s",     "Mean estimated time per layer (print phase)",          "Derived"),
    ("thermal_history.std_layer_time",        "global", "s",     "Std dev of estimated time per layer",                  "Derived"),
    ("thermal_history.mean_cooling_time",     "global", "s",     "Mean estimated cooling time between layers",           "Derived"),
    ("thermal_history.std_cooling_time",      "global", "s",     "Std dev of cooling time between layers",               "Derived"),
    ("thermal_history.early_layer_time_mean", "global", "s",     "Mean layer time for first 3 layers",                   "Derived"),
    ("thermal_history.mid_layer_time_mean",   "global", "s",     "Mean layer time for middle third of layers",           "Derived"),
    ("thermal_history.late_layer_time_mean",  "global", "s",     "Mean layer time for last 3 layers",                    "Derived"),

    # --- B) Bonding quality (global sub-dict) ---
    ("bonding_quality.extrusion_continuity_index", "global", "–",      "mean_extrude_len / mean_travel_len (print phase, ≥0.2mm)", "Derived"),
    ("bonding_quality.interruption_density",       "global", "1/mm",   "retract_count / extrude_path_mm (print phase, ≥0.2mm)",    "Derived"),
    ("bonding_quality.short_extrusion_ratio",      "global", "ratio",  "Fraction of print-phase extrude segs with length < 1 mm",  "Derived"),
    ("bonding_quality.perimeter_to_infill_ratio",  "global", "–",      "Perimeter path length / infill path length",               "Derived ;TYPE"),
    ("bonding_quality.bonding_disruption_score",   "global", "0–1",    "0.5·rpm_norm + 0.3·short_ext_ratio + 0.2·wipe_freq_norm",  "Derived"),

    # --- C) Structural orientation (global sub-dict) ---
    ("structural_orientation.dominant_infill_angle",          "global", "°",    "Mode bin centre of folded [0,180°) infill angles",        ";TYPE:*infill*"),
    ("structural_orientation.angle_dispersion_index",         "global", "°",    "Circular std dev of infill angles (folded to [0,180°))",  "Derived"),
    ("structural_orientation.angle_alignment_with_x_axis",    "global", "0–1",  "|cos(dominant_infill_angle)|; 1=X-axis aligned",          "Derived"),
    ("structural_orientation.estimated_load_alignment_score", "global", "0–1",  "Fraction of infill angles within ±22.5° of X axis",       "Derived"),
    ("structural_orientation.layer_orientation_variance",     "global", "°²",   "Variance of dominant infill angles across layers",        "Derived"),
    ("structural_orientation.mean_alignment_score",           "global", "0–1",  "Specimen-level mean load alignment (= estimated_load_alignment_score)", "Derived"),
    ("structural_orientation.alignment_std",                  "global", "0–1",  "Std dev of per-layer load alignment scores",              "Derived"),

    # --- D) Energy / flow (global sub-dict) ---
    ("energy_flow.mean_volumetric_flow",   "global", "mm²/min", "Mean (e_delta/length_mm)·feedrate across extrusion segs",  "M83 + F"),
    ("energy_flow.peak_volumetric_flow",   "global", "mm²/min", "Max (e_delta/length_mm)·feedrate across extrusion segs",   "M83 + F"),
    ("energy_flow.flow_std",               "global", "mm²/min", "Std dev of volumetric flow proxy",                         "Derived"),
    ("energy_flow.flow_variability_index", "global", "–",       "flow_std / mean_volumetric_flow (CV of flow)",             "Derived"),

    # --- layer features (existing) ---
    ("z",                    "layer", "mm",    "Z height of layer from ;Z: marker",               ";Z"),
    ("height",               "layer", "mm",    "Layer height from ;HEIGHT: marker",               ";HEIGHT"),
    ("layer_time_est_s",     "layer", "s",     "Sum of segment time estimates for this layer",    "time_est_s"),
    ("extrude_path_mm",      "layer", "mm",    "Total XY extrusion path in this layer",           "G1 E>0"),
    ("travel_mm",            "layer", "mm",    "Total XY travel path in this layer",              "G0/G1 travel"),
    ("extrude_travel_ratio", "layer", "–",     "extrude_path_mm / travel_mm",                     "Derived"),
    ("total_e_pos",          "layer", "mm",    "Sum of positive E deltas in this layer",          "M83"),
    ("total_e_neg",          "layer", "mm",    "Sum of |negative E deltas| in this layer",        "M83"),
    ("retract_count",        "layer", "count", "Number of retract moves in this layer",           "M83"),
    ("mean_retract_len",     "layer", "mm",    "Mean |E_delta| of retract moves in this layer",   "M83"),
    ("wipe_blocks_count",    "layer", "count", "Number of wipe blocks starting in this layer",    ";WIPE_START"),
    ("mean_F_extrude",       "layer", "mm/min","Mean feedrate during extrusion in this layer",    "F param"),
    ("p95_F_extrude",        "layer", "mm/min","95th pct feedrate during extrusion in this layer","F param"),
    ("mean_F_travel",        "layer", "mm/min","Mean feedrate during travel in this layer",       "F param"),
    ("anisotropy_score_infill","layer","0–1",  "Infill angle anisotropy for this layer",          ";TYPE:*infill*"),
    ("startpoint_dispersion","layer", "mm",    "Distance of first extrusion start from layer centroid (seam proxy)","Derived"),

    # --- A) Thermal history (layer) ---
    ("cumulative_print_time_s",   "layer", "s",     "Cumulative estimated print time up to end of this layer",   "Derived"),
    ("relative_layer_time",       "layer", "–",     "layer_time_est_s / mean_layer_time",                        "Derived"),
    ("rolling_mean_layer_time",   "layer", "s",     "Mean layer time over 3-layer rolling window ending here",   "Derived"),
    ("layer_time_gradient",       "layer", "s",     "layer_time_est_s[i] – layer_time_est_s[i-1]",              "Derived"),
    ("norm_extrusion_time_share", "layer", "ratio", "Fraction of layer time spent extruding",                    "Derived"),

    # --- B) Bonding quality (layer) ---
    ("extrusion_continuity_index","layer", "–",     "mean_extrude_seg_len / mean_travel_seg_len (≥0.2mm segs)",  "Derived"),
    ("interruption_density",      "layer", "1/mm",  "retract_count / extrude_path_mm for this layer",           "Derived"),
    ("short_extrusion_ratio",     "layer", "ratio", "Fraction of extrude segs < 1 mm in this layer",            "Derived"),
    ("interface_density",         "layer", "count", "Number of ;TYPE transitions within this layer",            ";TYPE"),

    # --- C) Structural orientation (layer) ---
    ("dominant_infill_angle",     "layer", "°",     "Mode bin centre of infill angles in this layer",           ";TYPE:*infill*"),
    ("load_alignment_score",      "layer", "0–1",   "Fraction of infill angles within ±22.5° of X axis",        "Derived"),

    # --- D) Energy / flow (layer) ---
    ("volumetric_flow_rate_est",  "layer", "mm²/min","Mean (e/length)·F for this layer",                        "M83 + F"),
    ("layer_energy_proxy",        "layer", "mm²",   "volumetric_flow_rate_est × layer_time_est_s",              "Derived"),
    ("flow_variability_index",    "layer", "–",     "CV of per-segment volumetric flow in this layer",          "Derived"),

    # --- E) Specimen features (representative keys) ---
    ("specimen_features",        "specimen", "dict",  "Flat dict of layer-feature aggregations: mean/std/p90/p10/early_mean/mid_mean/late_mean for each layer metric", "Derived"),
]


def generate_manifest() -> str:
    lines = [
        "# G-Code Feature Manifest",
        "",
        "Auto-generated by `gcode-feature-extractor`.",
        "",
        "| Name | Level | Unit | Definition | Dependencies |",
        "|------|-------|------|------------|--------------|",
    ]
    for row in MANIFEST_ROWS:
        name, level, unit, definition, deps = row
        lines.append(f"| `{name}` | {level} | {unit} | {definition} | {deps} |")

    lines += [
        "",
        "---",
        "",
        "## Notes",
        "",
        "- **declared** features come directly from header comments or M-code checks.",
        "- **global** features are computed across the entire file.",
        "- **layer** features appear as columns in `features_layers.csv`.",
        "- **specimen** features are flat aggregations of layer features for ML regression.",
        "- All time estimates assume constant feedrate within each segment.",
        "- Anisotropy score: `1 – H(angle_histogram) / log(n_bins)` where angles are folded to [0°, 180°).",
        "- Seam proxy: per-layer first extrusion start-point; `seam_dispersion_*` measures cluster spread.",
        "- Artifact filtering: layer_id < 0 excluded from thermal/bonding/orientation/flow stats;",
        "  temperature S=0 commands excluded from mean_nozzle_setpoint;",
        "  segments < 0.2 mm excluded from bonding ratio calculations.",
        "- Load alignment score: fraction of infill angles within ±22.5° of X axis (tensile direction).",
        "- Volumetric flow proxy: (E_delta / length_mm) × feedrate_mm_min — proportional to actual flow rate.",
        "- specimen_features keys follow pattern: `{layer_feature}__{stat}` where stat ∈ {mean, std, p90, p10, early_mean, mid_mean, late_mean}.",
    ]
    return "\n".join(lines)
