"""Pydantic models for FastAPI request / response."""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel


class DownloadUrls(BaseModel):
    features_global_json: str
    features_layers_csv:  str
    feature_manifest_md:  str
    segments_csv:         str


class ExtractResponse(BaseModel):
    session_id:              str
    filename:                str
    total_lines:             int
    global_features:         Dict[str, Any]
    declared_settings:       Dict[str, Any]
    layer_features_preview:  List[Dict[str, Any]]   # first 50 rows
    layer_count:             int
    download_urls:           DownloadUrls


class ErrorResponse(BaseModel):
    detail: str
