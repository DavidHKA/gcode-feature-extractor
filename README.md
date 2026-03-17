# G-Code Feature Extractor

A local web app that parses FFF/FDM `.gcode` files (PrusaSlicer) and extracts a **15-feature ML training vector** — 5 slicer input parameters + 10 hidden G-code-derived features — visualised in a browser UI.

Built to generate training data for a neural network predicting tensile strength of PETG specimens (DIN EN ISO 3167).

---

## Prerequisites

| Tool       | Version tested | Install |
|------------|---------------|---------|
| Python     | 3.11          | [python.org](https://python.org) |
| Node.js    | 20 LTS        | [nodejs.org](https://nodejs.org) |
| npm        | 10+           | bundled with Node |

> Windows users: use **PowerShell** or **Git Bash**.

---

## Quick Start

### 1 — Backend

```bash
cd backend
python -m venv .venv

# Windows PowerShell
.venv\Scripts\Activate.ps1

# Git Bash / Linux / macOS
source .venv/bin/activate

pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8001
```

API: `http://localhost:8001` · Docs: `http://localhost:8001/docs`

### 2 — Frontend

Open a **second terminal**:

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`.

> Shortcut on Windows: double-click `start_project.bat` to launch both servers at once.

---

## Usage

### Single-file mode

1. Drag & drop a `.gcode` file (or click to browse).
2. Click **Extract Features**.
3. Explore the four tabs:
   - **Summary** — Training Vector (5 slicer params + 10 G-code KPIs), raw JSON
   - **Layer Features** — Plotly charts + scrollable per-layer table
   - **Events & Settings** — temperatures, linear advance, dynamics, declared settings
   - **Downloads** — four artefact files

### Batch mode

1. Switch to **Batch** in the top navigation.
2. Select multiple `.gcode` files.
3. Click **Alle extrahieren** — a progress bar shows per-file status.
4. The preview table shows layers, nozzle temp, thermal bonding, and feature count per file.
5. Click any filename to open its full single-file analysis in an overlay.
6. Download `training_data.csv` — one row per file, ready for NN training (add a `tensile_strength_mpa` column with measured values).

---

## Training Vector

The 15-feature vector is the core output for ML. Missing slicer parameters are `null` (empty cell in CSV = NaN in the ML pipeline) rather than `0.0`.

### 5 Slicer Input Parameters

| Key | Header field | Unit |
|-----|-------------|------|
| `sp__layer_height` | `layer_height` | mm |
| `sp__nozzle_temp` | `temperature` | °C |
| `sp__fill_density` | `fill_density` | fraction 0–1 |
| `sp__print_speed` | `print_speed` / `infill_speed` | mm/s |
| `sp__perimeters` | `perimeters` | count |

### 10 G-Code-Derived Features

| Key | Description |
|-----|-------------|
| `thermal_bonding_proxy` | T_nozzle × exp(−mean_layer_time / 30 s) |
| `e_per_mm_cv__mean` | Flow consistency (CV of E/mm per layer) |
| `interruption_density` | Retracts per metre of extrusion |
| `short_extrusion_ratio` | Fraction of segments < 1 mm |
| `estimated_load_alignment_score` | Infill fraction within ±22.5° of X-axis |
| `alternating_infill_score` | Layer pairs with ~90° angle flip |
| `layer_extrusion_uniformity` | 1 − CV(extrusion per layer) |
| `perimeter_to_infill_ratio` | Wall vs. core path length |
| `section_type_count__mean` | Mean distinct ;TYPE sections per layer |
| `retract_wipe_correlation` | Fraction of retracts inside wipe blocks |

---

## Download Artefacts (single-file mode)

| File | Contents |
|------|----------|
| `training_data.csv` | 15-feature training vector (1 row) |
| `features_global.json` | All global & derived features |
| `features_layers.csv` | Per-layer feature table |
| `feature_manifest.md` | Feature definitions, units, formulas |

---

## Running Tests

```bash
# from the project root
backend/.venv/Scripts/python -m pytest tests/ -v   # Windows
# or
backend/.venv/bin/python -m pytest tests/ -v       # Linux / macOS
```

**142 tests** across three files:

| File | What it tests |
|------|--------------|
| `test_parser.py` | Parser logic: layers, retracts, wipe blocks, dynamics, headers — calibrated to synthetic `mini_test.gcode` |
| `test_new_features.py` | Feature groups: thermal history, bonding quality, orientation, energy flow, specimen aggregation |
| `test_real_gcode.py` | Integration tests on `sample_data/Nr. 1.gcode` (real PETG tensile specimen) — verifies all 5 slicer params with known ground-truth values |

---

## Project Structure

```
gcode-feature-extractor/
├── backend/
│   ├── app/
│   │   ├── parser.py        # State-machine G-code parser
│   │   ├── features.py      # Feature engineering + training vector builder
│   │   ├── models.py        # Pydantic API models
│   │   └── main.py          # FastAPI endpoints (port 8001)
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── App.tsx                       # Main layout, single + batch mode
│   │   ├── types.ts                      # TypeScript interfaces
│   │   ├── api.ts                        # axios API client
│   │   └── components/
│   │       ├── UploadArea.tsx            # Drag & drop
│   │       ├── KPICards.tsx              # Training vector KPI grid
│   │       ├── BatchResults.tsx          # Batch preview table
│   │       ├── LayerChart.tsx            # Plotly charts
│   │       ├── LayerTable.tsx            # Per-layer table
│   │       ├── EventsView.tsx            # Events & settings panels
│   │       └── DownloadSection.tsx       # Download buttons
│   ├── package.json
│   └── vite.config.ts                    # Dev proxy → :8001
├── tests/
│   ├── conftest.py
│   ├── test_parser.py
│   ├── test_new_features.py
│   └── test_real_gcode.py
├── sample_data/
│   ├── mini_test.gcode      # Synthetic PrusaSlicer snippet (unit tests)
│   └── Nr. 1.gcode          # Real PETG tensile specimen (integration tests)
└── start_project.bat        # Launches backend + frontend (Windows)
```

---

## API Reference

### `POST /api/extract-features`

```bash
curl -F "file=@myprint.gcode" http://localhost:8001/api/extract-features
```

Key response fields:

```json
{
  "session_id": "uuid",
  "filename": "myprint.gcode",
  "layer_count": 39,
  "training_vector": {
    "feature_names": ["sp__layer_height", "sp__nozzle_temp", "..."],
    "values":        [0.1, 230.0, "..."],
    "n_features":    15
  },
  "global_features": { "..." : "..." },
  "declared_settings": { "..." : "..." },
  "download_urls": { "..." : "..." }
}
```

### `POST /api/batch-extract`

Upload multiple files, returns a list of per-file `ExtractResponse` objects.

### `GET /api/download/{session_id}/{filename}`

Download one of the four artefacts.

---

## Compatibility

- **Slicer**: PrusaSlicer 2.x (tested with 2.7.x and 2.9.4, MK3S profile)
- **Coordinate mode**: G90 absolute XY, M83 relative extrusion
- **Units**: G21 (mm)
- Other slicers may work but are untested.

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `uvicorn: command not found` | Activate venv first |
| `CORS error` in browser | Ensure backend runs on port **8001** and frontend on 5173 |
| `413 Request Entity Too Large` | Default limit is 200 MB; change `MAX_FILE_SIZE_MB` in `main.py` |
| Charts not rendering | Run `npm install` again; check browser console |
| Session not found on download | Server restarted; re-upload the file |
