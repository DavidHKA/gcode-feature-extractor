"""
FastAPI backend for G-Code Feature Extractor.

Endpoints:
  POST /api/extract-features   – upload .gcode, returns JSON + session ID
  GET  /api/download/{sid}/{filename}  – download one of four artefacts
  GET  /api/health             – liveness probe
"""

import io
import json
import math
import uuid
from typing import Any, Dict

import pandas as pd
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse

from .features import (
    extract_global_features,
    extract_layer_features,
    extract_specimen_features,
    generate_manifest,
    segments_to_df,
)
from .models import DownloadUrls, ExtractResponse
from .parser import parse_gcode

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(title="G-Code Feature Extractor", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory session store  {session_id: {"global": dict, "layers_csv": str, ...}}
_sessions: Dict[str, Dict[str, Any]] = {}

MAX_FILE_SIZE_MB = 200


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _sanitize(obj: Any) -> Any:
    """Make an object JSON-serialisable (handle numpy/nan/inf)."""
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    if isinstance(obj, tuple):
        return [_sanitize(v) for v in obj]
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    return obj


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/api/health")
async def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.post("/api/extract-features", response_model=ExtractResponse)
async def extract_features(file: UploadFile = File(...)) -> ExtractResponse:
    # ---- validate file ----
    if not file.filename or not file.filename.lower().endswith(".gcode"):
        raise HTTPException(400, "Only .gcode files are supported.")

    raw = await file.read()
    if len(raw) > MAX_FILE_SIZE_MB * 1024 * 1024:
        raise HTTPException(413, f"File exceeds {MAX_FILE_SIZE_MB} MB limit.")

    try:
        content = raw.decode("utf-8", errors="replace")
    except Exception as exc:
        raise HTTPException(400, f"Could not decode file: {exc}") from exc

    # ---- parse ----
    try:
        result = parse_gcode(content)
    except Exception as exc:
        raise HTTPException(500, f"Parse error: {exc}") from exc

    # ---- feature extraction ----
    try:
        global_feats     = extract_global_features(result)
        layer_df         = extract_layer_features(result)
        specimen_feats   = extract_specimen_features(layer_df)
        seg_df           = segments_to_df(result)
        manifest_text    = generate_manifest()
    except Exception as exc:
        raise HTTPException(500, f"Feature extraction error: {exc}") from exc

    # ---- serialise artefacts ----
    global_feats["specimen_features"] = specimen_feats
    global_json    = json.dumps(_sanitize(global_feats), indent=2)
    layers_csv     = layer_df.to_csv(index=False)
    segments_csv   = seg_df.to_csv(index=False)
    declared_clean = _sanitize(result.declared_settings)

    # ---- store session ----
    sid = str(uuid.uuid4())
    _sessions[sid] = {
        "filename":     file.filename,
        "global_json":  global_json,
        "layers_csv":   layers_csv,
        "manifest_md":  manifest_text,
        "segments_csv": segments_csv,
    }

    # ---- layer preview (first 50 rows) ----
    preview_rows = _sanitize(
        layer_df.head(50).replace({float("nan"): None}).to_dict(orient="records")
    )

    base = f"/api/download/{sid}"
    return ExtractResponse(
        session_id=sid,
        filename=file.filename,
        total_lines=result.total_lines,
        global_features=_sanitize(global_feats),
        declared_settings=declared_clean,
        layer_features_preview=preview_rows,
        layer_count=len(result.layer_info),
        download_urls=DownloadUrls(
            features_global_json=f"{base}/features_global.json",
            features_layers_csv =f"{base}/features_layers.csv",
            feature_manifest_md =f"{base}/feature_manifest.md",
            segments_csv        =f"{base}/segments.csv",
        ),
    )


@app.get("/api/download/{session_id}/{filename}")
async def download(session_id: str, filename: str) -> Response:
    session = _sessions.get(session_id)
    if session is None:
        raise HTTPException(404, "Session not found (server may have restarted).")

    if filename == "features_global.json":
        return Response(
            content=session["global_json"],
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    elif filename == "features_layers.csv":
        return Response(
            content=session["layers_csv"],
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    elif filename == "feature_manifest.md":
        return Response(
            content=session["manifest_md"],
            media_type="text/markdown",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    elif filename == "segments.csv":
        return Response(
            content=session["segments_csv"],
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    else:
        raise HTTPException(404, f"Unknown file: {filename}")
