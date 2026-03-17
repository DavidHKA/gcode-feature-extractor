# G-Code Feature Extractor

A local MVP that parses FFF/FDM `.gcode` files (PrusaSlicer 2.7.x) and extracts **declared settings**, **hidden/derived global features**, and **per-layer metrics** — all visualised in a browser UI.

---

## Prerequisites

| Tool       | Version tested | Install |
|------------|---------------|---------|
| Python     | 3.11          | [python.org](https://python.org) |
| Node.js    | 20 LTS        | [nodejs.org](https://nodejs.org) |
| npm        | 10+           | bundled with Node |

> Windows users: use **PowerShell** or **Git Bash**. All commands below use forward slashes.

---

## Quick Start (< 10 minutes)

### 1 — Clone / open the project

```bash
cd C:/Users/<you>/gcode-feature-extractor
```

### 2 — Backend setup

```bash
cd backend
python -m venv .venv

# Windows PowerShell
.venv\Scripts\Activate.ps1

# Git Bash / Linux / macOS
source .venv/bin/activate

pip install -r requirements.txt
```

Start the API server:

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The API is now at `http://localhost:8000`.
Interactive docs: `http://localhost:8000/docs`

### 3 — Frontend setup

Open a **second terminal**:

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173` in your browser.

---

## Usage

1. Drag & drop a `.gcode` file (or click to browse).
2. Click **Extract Features**.
3. Explore the four tabs:
   - **Summary** — KPI cards, E/mm by section type, raw JSON
   - **Layer Features** — 6 Plotly charts + scrollable table
   - **Events & Settings** — temperatures, linear advance, dynamics, declared settings
   - **Downloads** — four artefact files

### Download artefacts

| File | Contents |
|------|----------|
| `features_global.json` | All global & derived features |
| `features_layers.csv`  | Per-layer feature table (all layers) |
| `feature_manifest.md`  | Feature definitions, units, dependencies |
| `segments.csv`         | Raw segment data (every G0/G1 move) |

---

## Running tests

```bash
cd backend
pip install pytest   # only needed once
pytest ../tests -v
```

Expected output: **all tests pass** against `sample_data/mini_test.gcode`.

---

## Project Structure

```
gcode-feature-extractor/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── parser.py      # State-machine G-code parser
│   │   ├── features.py    # Feature engineering (global + layer + manifest)
│   │   ├── models.py      # Pydantic API models
│   │   └── main.py        # FastAPI endpoints
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── App.tsx                          # Main layout + tabs
│   │   ├── components/
│   │   │   ├── UploadArea.tsx               # Drag & drop
│   │   │   ├── KPICards.tsx                 # Summary KPI grid
│   │   │   ├── LayerChart.tsx               # 6 Plotly charts
│   │   │   ├── LayerTable.tsx               # Layer data table
│   │   │   ├── EventsView.tsx               # Events & settings panels
│   │   │   └── DownloadSection.tsx          # Download buttons
│   │   ├── api.ts                           # axios API client
│   │   └── types.ts                         # TypeScript interfaces
│   ├── package.json
│   └── vite.config.ts                       # Dev proxy → :8000
├── tests/
│   ├── conftest.py
│   └── test_parser.py   # ~40 test cases
├── sample_data/
│   └── mini_test.gcode  # Synthetic PrusaSlicer 2.7 snippet
└── README.md
```

---

## API Reference

### `POST /api/extract-features`

Upload a `.gcode` file.

```bash
curl -F "file=@myprint.gcode" http://localhost:8000/api/extract-features
```

Response JSON:

```json
{
  "session_id": "uuid",
  "filename": "myprint.gcode",
  "total_lines": 123456,
  "layer_count": 259,
  "global_features": { ... },
  "declared_settings": { ... },
  "layer_features_preview": [ ... ],
  "download_urls": {
    "features_global_json": "/api/download/<sid>/features_global.json",
    "features_layers_csv":  "/api/download/<sid>/features_layers.csv",
    "feature_manifest_md":  "/api/download/<sid>/feature_manifest.md",
    "segments_csv":         "/api/download/<sid>/segments.csv"
  }
}
```

### `GET /api/download/{session_id}/{filename}`

Download one of the four artefacts.

---

## Feature Engineering Overview

### Declared Settings
Extracted from header comments and M-code printer checks (M862.3, M862.1, M900 K…).

### Global Hidden / Derived Features
| Category | Key features |
|----------|-------------|
| Counts | layers, segments, retracts, wipes, G92 resets |
| Distances | total travel/extrude path, travel-to-extrude ratio |
| Extrusion | E/mm ratio by type, short-segment rate |
| Retraction | mean/p95 length & speed, retracts/meter, wipe correlation |
| Wipe | path length, time, extrusion signature |
| Dynamics | M204 accel changes, M205 jerk, M203 max feedrate, speed-jump rate |
| Temperature | nozzle/bed setpoint sequences, first-layer temp |
| Directionality | infill angle histogram, anisotropy score (0=isotropic, 1=anisotropic) |
| Seam proxy | per-layer first-extrusion start-point dispersion |
| Linear Advance | M900 K value count, unique values, min/max/first/last |

### Layer Features (CSV columns)
`layer_id · z · height · layer_time_est_s · extrude_path_mm · travel_mm · extrude_travel_ratio · total_e_pos · total_e_neg · retract_count · mean_retract_len · wipe_blocks_count · mean_F_extrude · p95_F_extrude · mean_F_travel · anisotropy_score_infill · startpoint_dispersion`

---

## Compatibility

- **Slicer**: PrusaSlicer 2.x (tested with 2.7.2+win64, MK3S profile)
- **Coordinate mode**: G90 absolute XY, M83 relative extrusion
- **Units**: G21 (mm)
- Other slicers may work but are untested. Adapt comment-marker detection in `parser.py` as needed.

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `uvicorn: command not found` | Activate venv first |
| `CORS error` in browser | Ensure backend runs on port 8000 and frontend on 5173 |
| `413 Request Entity Too Large` | Default limit is 200 MB; change `MAX_FILE_SIZE_MB` in `main.py` |
| Charts not rendering | Run `npm install` again; check browser console |
| Session not found on download | Server restarted; re-upload the file |
