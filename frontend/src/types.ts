export interface DownloadUrls {
  features_global_json: string
  features_layers_csv:  string
  feature_manifest_md:  string
  segments_csv:         string
}

export interface LayerRow {
  layer_id:               number
  z:                      number
  height:                 number
  layer_time_est_s:       number
  extrude_path_mm:        number
  travel_mm:              number
  extrude_travel_ratio:   number
  total_e_pos:            number
  total_e_neg:            number
  retract_count:          number
  mean_retract_len:       number
  wipe_blocks_count:      number
  mean_F_extrude:         number
  p95_F_extrude:          number
  mean_F_travel:          number
  anisotropy_score_infill:number
  startpoint_dispersion:  number
}

export interface ExtractResponse {
  session_id:              string
  filename:                string
  total_lines:             number
  global_features:         Record<string, unknown>
  declared_settings:       Record<string, unknown>
  layer_features_preview:  LayerRow[]
  layer_count:             number
  download_urls:           DownloadUrls
}
