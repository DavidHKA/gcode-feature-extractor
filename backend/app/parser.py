"""
G-Code Parser for FFF/FDM 3D Printers
Tuned for PrusaSlicer 2.7.x output (MK3S profile).

Key assumptions for target file:
  - G90  → absolute XYZ coordinates
  - M83  → relative extrusion (E is a delta per move)
  - G92 E0 / G92 E0.0 → reset E accumulator
  - Units: G21 (mm)

Layer detection priority:
  ;LAYER_CHANGE  → open new layer entry
  ;Z:<float>     → set Z for current layer
  ;HEIGHT:<float>→ set height for current layer
"""

import re
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# Matches G-code word parameters like  X100.5  Y-3  E0.012  F1800
PARAM_RE = re.compile(r'([A-Z])([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)', re.IGNORECASE)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class MoveSegment:
    line_no: int
    raw: str
    start_xyz: Tuple[float, float, float]
    end_xyz: Tuple[float, float, float]
    delta_xyz: Tuple[float, float, float]
    e_delta: float          # signed E value (rel mode) or computed delta (abs mode)
    f: float                # feedrate [mm/min] at time of move
    length_mm: float        # XY planar distance
    length_xyz_mm: float    # full 3-D distance
    angle_deg: float        # XY direction [0, 360)
    layer_id: int           # -1 = before first ;LAYER_CHANGE
    section_type: str       # from ;TYPE:
    width_mm: float         # from ;WIDTH:
    is_travel: bool
    is_extrude: bool
    is_retract: bool
    is_z_hop: bool
    in_wipe: bool
    time_est_s: float       # estimated move duration


@dataclass
class Event:
    line_no: int
    event_type: str   # see constants below
    data: Dict[str, Any]
    layer_id: int


# event_type constants
EVT_LAYER_CHANGE    = "layer_change"
EVT_TEMP_NOZZLE     = "temp_nozzle"
EVT_TEMP_BED        = "temp_bed"
EVT_FAN             = "fan"
EVT_PROGRESS        = "progress"
EVT_ACCEL_MAX       = "accel_max"
EVT_FEEDRATE_MAX    = "feedrate_max"
EVT_ACCEL_SET       = "accel_set"
EVT_JERK_LIMITS     = "jerk_limits"
EVT_LINEAR_ADVANCE  = "linear_advance"
EVT_G92_RESET       = "g92_reset"
EVT_WIPE_START      = "wipe_start"
EVT_WIPE_END        = "wipe_end"
EVT_BEFORE_LAYER    = "before_layer_change"
EVT_AFTER_LAYER     = "after_layer_change"


@dataclass
class LayerInfo:
    layer_id: int
    z: float
    height: float
    start_line: int
    end_line: int = -1


@dataclass
class ParseResult:
    segments: List[MoveSegment]
    events: List[Event]
    layer_info: List[LayerInfo]
    declared_settings: Dict[str, Any]
    g92_reset_count: int
    wipe_count: int
    total_lines: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_params(cmd_str: str) -> Dict[str, float]:
    """Return dict of letter→float for every word parameter in *cmd_str*."""
    result: Dict[str, float] = {}
    for m in PARAM_RE.finditer(cmd_str):
        result[m.group(1).upper()] = float(m.group(2))
    return result


def _split_line(raw: str) -> Tuple[str, str]:
    """Return (command_part, comment_part) from a raw G-code line."""
    idx = raw.find(';')
    if idx == -1:
        return raw.strip(), ""
    return raw[:idx].strip(), raw[idx + 1:].strip()


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------

def parse_gcode(content: str) -> ParseResult:
    """
    Parse a complete G-code file and return a :class:`ParseResult`.

    The parser is a single-pass state machine.  It never seeks backward.
    """
    lines = content.splitlines()

    # --- Machine state ---
    x = y = z = 0.0
    e = 0.0          # absolute E accumulator (used only in M82 mode)
    f = 0.0          # current feedrate [mm/min]
    is_abs_xyz = True   # G90 default
    is_rel_e   = False  # will be set to True when M83 is seen

    # --- Layer / section state ---
    current_layer_id   = -1
    current_z          = 0.0
    current_height     = 0.0
    current_type       = ""
    current_width      = 0.0
    layer_change_pending = False   # set on ;LAYER_CHANGE, cleared on ;Z:

    # --- Wipe state ---
    in_wipe    = False
    wipe_open  = False   # tracks unmatched WIPE_START

    # --- Output collections ---
    segments:       List[MoveSegment] = []
    events:         List[Event]       = []
    layer_info:     List[LayerInfo]   = []

    # declared_settings populated from header comments and M-code checks
    declared_settings: Dict[str, Any] = {
        "generated_by":         None,
        "timestamp":            None,
        "printer_model":        None,
        "nozzle_diameter":      None,
        "filament_type":        None,
        "header_settings":      {},
        "linear_advance_values": [],
    }

    g92_reset_count = 0
    wipe_count      = 0
    in_header       = True   # stop aggressive header parsing after first move

    # -----------------------------------------------------------------------
    for line_no, raw_line in enumerate(lines, 1):
        line = raw_line.strip()
        if not line:
            continue

        cmd_part, comment = _split_line(line)

        # ===== COMMENT PROCESSING =====
        if comment:
            _handle_comment(
                comment, line_no, current_layer_id,
                declared_settings, events, layer_info,
                in_header,
            )

            # --- PrusaSlicer structural markers ---
            if comment == "LAYER_CHANGE":
                in_header = False
                layer_change_pending = True
                current_layer_id += 1
                # Create a placeholder; Z + height filled in by ;Z: / ;HEIGHT:
                layer_info.append(LayerInfo(
                    layer_id=current_layer_id,
                    z=current_z,
                    height=current_height,
                    start_line=line_no,
                ))
                if len(layer_info) > 1:
                    layer_info[-2].end_line = line_no - 1
                events.append(Event(
                    line_no=line_no,
                    event_type=EVT_LAYER_CHANGE,
                    data={"layer_id": current_layer_id},
                    layer_id=current_layer_id,
                ))

            elif comment.startswith("Z:"):
                try:
                    new_z = float(comment[2:])
                    current_z = new_z
                    # z-position sync (real Z moves still parsed from G1)
                    z = new_z
                    if layer_info:
                        layer_info[-1].z = new_z
                    layer_change_pending = False
                except ValueError:
                    pass

            elif comment.startswith("HEIGHT:"):
                try:
                    current_height = float(comment[7:])
                    if layer_info:
                        layer_info[-1].height = current_height
                except ValueError:
                    pass

            elif comment.startswith("TYPE:"):
                current_type = comment[5:].strip()

            elif comment.startswith("WIDTH:"):
                try:
                    current_width = float(comment[6:])
                except ValueError:
                    pass

            elif comment == "WIPE_START":
                in_wipe   = True
                wipe_open = True
                events.append(Event(
                    line_no=line_no,
                    event_type=EVT_WIPE_START,
                    data={"layer_id": current_layer_id},
                    layer_id=current_layer_id,
                ))

            elif comment == "WIPE_END":
                in_wipe = False
                if wipe_open:
                    wipe_count += 1
                    wipe_open = False
                events.append(Event(
                    line_no=line_no,
                    event_type=EVT_WIPE_END,
                    data={"layer_id": current_layer_id},
                    layer_id=current_layer_id,
                ))

            elif comment == "BEFORE_LAYER_CHANGE":
                events.append(Event(
                    line_no=line_no,
                    event_type=EVT_BEFORE_LAYER,
                    data={},
                    layer_id=current_layer_id,
                ))

            elif comment == "AFTER_LAYER_CHANGE":
                events.append(Event(
                    line_no=line_no,
                    event_type=EVT_AFTER_LAYER,
                    data={},
                    layer_id=current_layer_id,
                ))

        if not cmd_part:
            continue

        # ===== COMMAND PROCESSING =====
        cmd_upper = cmd_part.upper()
        first_letter = cmd_upper[0] if cmd_upper else ""

        if first_letter == 'G':
            params = _parse_params(cmd_part)
            g_key = cmd_upper.split()[0]   # e.g. "G1", "G28"

            # Normalize: some slicers write "G00" etc.
            try:
                g_num = int(float(g_key[1:]))
            except (ValueError, IndexError):
                g_num = -1

            if g_num in (0, 1):
                in_header = False
                # --- Compute new position ---
                if is_abs_xyz:
                    new_x = params.get('X', x)
                    new_y = params.get('Y', y)
                    new_z = params.get('Z', z)
                else:
                    new_x = x + params.get('X', 0.0)
                    new_y = y + params.get('Y', 0.0)
                    new_z = z + params.get('Z', 0.0)

                # --- Extrusion delta ---
                if is_rel_e:
                    e_delta = params.get('E', 0.0)
                else:
                    raw_e  = params.get('E', e)
                    e_delta = raw_e - e
                    e       = raw_e

                # --- Feedrate ---
                if 'F' in params:
                    f = params['F']

                # --- Geometry ---
                dx = new_x - x
                dy = new_y - y
                dz = new_z - z
                xy_dist  = math.sqrt(dx * dx + dy * dy)
                xyz_dist = math.sqrt(dx * dx + dy * dy + dz * dz)
                angle    = math.degrees(math.atan2(dy, dx)) % 360.0

                # --- Classification ---
                EPS = 0.001
                is_retract = e_delta < -EPS
                is_extrude = e_delta > EPS
                is_z_hop   = (dz > EPS
                              and abs(e_delta) < EPS
                              and xy_dist < EPS)
                is_travel  = (not is_retract
                              and not is_extrude
                              and not is_z_hop
                              and (xy_dist > EPS or dz < -EPS))

                # --- Time estimate ---
                time_est = (xyz_dist / f * 60.0) if f > 0 else 0.0

                seg = MoveSegment(
                    line_no=line_no,
                    raw=raw_line,
                    start_xyz=(x, y, z),
                    end_xyz=(new_x, new_y, new_z),
                    delta_xyz=(dx, dy, dz),
                    e_delta=e_delta,
                    f=f,
                    length_mm=xy_dist,
                    length_xyz_mm=xyz_dist,
                    angle_deg=angle,
                    layer_id=current_layer_id,
                    section_type=current_type,
                    width_mm=current_width,
                    is_travel=is_travel,
                    is_extrude=is_extrude,
                    is_retract=is_retract,
                    is_z_hop=is_z_hop,
                    in_wipe=in_wipe,
                    time_est_s=time_est,
                )
                segments.append(seg)

                # Update position
                x, y, z = new_x, new_y, new_z
                if is_rel_e:
                    e += e_delta   # keep cumulative for reference

            elif g_num == 20:
                pass  # inches – unexpected in this file
            elif g_num == 21:
                pass  # mm – already assumed
            elif g_num == 90:
                is_abs_xyz = True
            elif g_num == 91:
                is_abs_xyz = False
            elif g_num == 92:
                params = _parse_params(cmd_part)
                if 'E' in params:
                    e = params['E']
                    g92_reset_count += 1
                    events.append(Event(
                        line_no=line_no,
                        event_type=EVT_G92_RESET,
                        data={"e_value": e},
                        layer_id=current_layer_id,
                    ))

        elif first_letter == 'M':
            # Detect M-code number robustly (handles M862.3 etc.)
            m_match = re.match(r'M(\d+(?:\.\d+)?)', cmd_upper)
            if not m_match:
                continue
            m_code_str = m_match.group(1)
            params = _parse_params(cmd_part)

            if m_code_str == '82':
                is_rel_e = False
            elif m_code_str == '83':
                is_rel_e = True

            elif m_code_str in ('104', '109'):
                s_val = params.get('S')
                events.append(Event(
                    line_no=line_no,
                    event_type=EVT_TEMP_NOZZLE,
                    data={"setpoint": s_val, "wait": m_code_str == '109',
                          "cmd": int(m_code_str)},
                    layer_id=current_layer_id,
                ))

            elif m_code_str in ('140', '190'):
                s_val = params.get('S')
                events.append(Event(
                    line_no=line_no,
                    event_type=EVT_TEMP_BED,
                    data={"setpoint": s_val, "wait": m_code_str == '190',
                          "cmd": int(m_code_str)},
                    layer_id=current_layer_id,
                ))

            elif m_code_str == '106':
                events.append(Event(
                    line_no=line_no,
                    event_type=EVT_FAN,
                    data={"speed": params.get('S', 255), "on": True},
                    layer_id=current_layer_id,
                ))
            elif m_code_str == '107':
                events.append(Event(
                    line_no=line_no,
                    event_type=EVT_FAN,
                    data={"speed": 0, "on": False},
                    layer_id=current_layer_id,
                ))

            elif m_code_str == '73':
                events.append(Event(
                    line_no=line_no,
                    event_type=EVT_PROGRESS,
                    data={
                        "P": params.get('P'),
                        "R": params.get('R'),
                        "Q": params.get('Q'),
                        "S": params.get('S'),
                    },
                    layer_id=current_layer_id,
                ))

            elif m_code_str == '201':
                events.append(Event(
                    line_no=line_no,
                    event_type=EVT_ACCEL_MAX,
                    data={k: v for k, v in params.items() if k != 'M'},
                    layer_id=current_layer_id,
                ))
            elif m_code_str == '203':
                events.append(Event(
                    line_no=line_no,
                    event_type=EVT_FEEDRATE_MAX,
                    data={k: v for k, v in params.items() if k != 'M'},
                    layer_id=current_layer_id,
                ))
            elif m_code_str == '204':
                events.append(Event(
                    line_no=line_no,
                    event_type=EVT_ACCEL_SET,
                    data={k: v for k, v in params.items() if k != 'M'},
                    layer_id=current_layer_id,
                ))
            elif m_code_str == '205':
                events.append(Event(
                    line_no=line_no,
                    event_type=EVT_JERK_LIMITS,
                    data={k: v for k, v in params.items() if k != 'M'},
                    layer_id=current_layer_id,
                ))

            elif m_code_str == '900':
                k_val = params.get('K')
                if k_val is not None:
                    declared_settings["linear_advance_values"].append({
                        "line_no":  line_no,
                        "K":        k_val,
                        "layer_id": current_layer_id,
                    })
                events.append(Event(
                    line_no=line_no,
                    event_type=EVT_LINEAR_ADVANCE,
                    data={"K": k_val},
                    layer_id=current_layer_id,
                ))

            elif m_code_str == '862.3':
                # Printer model check: M862.3 P "MK3S"
                p_match = re.search(r'P\s*"([^"]+)"', cmd_part, re.IGNORECASE)
                if p_match:
                    declared_settings["printer_model"] = p_match.group(1)

            elif m_code_str in ('862.1', '862.2'):
                # Nozzle diameter check: M862.1 P0.4
                p_val = params.get('P')
                if p_val is not None and declared_settings["nozzle_diameter"] is None:
                    declared_settings["nozzle_diameter"] = p_val

    # Close last layer
    if layer_info:
        layer_info[-1].end_line = len(lines)

    return ParseResult(
        segments=segments,
        events=events,
        layer_info=layer_info,
        declared_settings=declared_settings,
        g92_reset_count=g92_reset_count,
        wipe_count=wipe_count,
        total_lines=len(lines),
    )


# ---------------------------------------------------------------------------
# Comment handler (header key=value extraction)
# ---------------------------------------------------------------------------

_KV_RE = re.compile(r'^([^=]+?)\s*=\s*(.+)$')


def _handle_comment(
    comment: str,
    line_no: int,
    layer_id: int,
    declared_settings: dict,
    events: list,
    layer_info: list,
    in_header: bool,
) -> None:
    """Extract declared settings from free-form comment lines."""

    # "generated by PrusaSlicer X.Y.Z+win64 on YYYY-MM-DD ..."
    if comment.lower().startswith("generated by"):
        parts = comment.split(" on ", 1)
        declared_settings["generated_by"] = (
            parts[0].replace("generated by ", "", 1).strip()
        )
        if len(parts) > 1:
            declared_settings["timestamp"] = parts[1].strip()
        return

    # Key = value pairs in the header (width settings, filament, etc.)
    m = _KV_RE.match(comment)
    if m:
        key = m.group(1).strip()
        val = m.group(2).strip()
        declared_settings["header_settings"][key] = val

        # Promote a few specific keys
        if "filament_type" in key.lower():
            declared_settings["filament_type"] = val
        return
