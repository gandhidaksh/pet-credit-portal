# Indian PET Plastic Credit Framework — Portal

Interactive portal for calculating PET Collection Credits (PCC) and Processing Credits (PPC) based on the IIT Delhi framework (December 2025).

**Developed by Daksh Gandhi**  
IIT Delhi — Prof Sovik Das · Prof A K Nema · Prof Sudip K. Pattanayek · Dr Anil Dhanda

---

## Project Structure

```
pet-plastic-credit/
├── app.py                  ← Flask backend
├── geo_classifier.py       ← Lat/lon -> collection category classifier (ESZ/river/coastline/flood)
├── validate_classifier.py  ← 20-point accuracy test for geo_classifier.py
├── preprocess_geo_data.py  ← Dev-only: regenerate the small committed geo files from raw sources
├── download_geo_data.py    ← Dev-only: download the raw sources (input to preprocess_geo_data.py)
├── requirements.txt        ← Python dependencies
├── database.db             ← SQLite database (auto-created on first run)
├── migrations/              ← SQL migrations to run against Supabase, in order (001, 002, 003)
├── templates/
│   ├── login.html          ← Login & Register page
│   ├── dashboard.html      ← Company dashboard (map-based location entry, bulk CSV upload)
│   └── admin.html          ← Admin overview
└── README.md
```

Note: `geo_classifier.py` reads small, pre-simplified/pre-reprojected copies of the 5 geospatial
datasets (~40MB total, committed directly to this repo — see **Geospatial Data Setup** below). The
original raw government files (~230MB combined, one alone over GitHub's 100MB limit) are NOT
committed and are only needed if you want to regenerate the small files from scratch.

---

## Setup & Run (VS Code / Local)

### 1. Install Python dependencies
```bash
pip install -r requirements.txt
```

### 2. Geospatial data
Nothing to download — the small pre-processed files `geo_classifier.py` needs are already in this
repo. See **Geospatial Data Setup** below for details, or if you need to regenerate them.

### 3. Run the database migrations
In the Supabase SQL editor, run each file in `migrations/` **in order** (001, then 002, then 003).

### 4. Run the app
```bash
python app.py
```

### 5. Open in browser
```
http://localhost:5000
```

---

## Geospatial Data Setup

`geo_classifier.py` loads 5 small, pre-simplified files that are already committed to this repo
(same level as `app.py`) — nothing to download for normal use or deployment:

| Folder | File (committed, ~40MB total) | Source |
|---|---|---|
| `Ecosensitive zone/` | `esz_reprojected.parquet` | MoEFCC-notified ESZs, Parivesh 2024 (full precision, not simplified) |
| `Coastline/` | `india_boundary_simplified.parquet` | National boundary (coastline proxy — see limitations below) |
| `Rivers+ Streams/` | `wris_rivers_simplified.parquet` | CWC WRIS river/stream line segments |
| `Flood+ Innundation/` | `ndem_floods_1998_2022_simplified.parquet` | NDEM/NRSC historical flood extents |
| `Protected Areas/` | `GatiShakti_Wildlife_Sanctuaries_and_National_Parks_simplified.parquet` | Wildlife sanctuaries & national parks |

Verify they load correctly:
```bash
python geo_classifier.py       # runs 3 sanity-check points
python validate_classifier.py  # runs the full 20-point accuracy test
```

### Why "pre-simplified", and how to regenerate

Render's free/Starter instance (512MB RAM) was getting OOM-killed the first time
`/api/classify-location` ran, because just reading the *raw* `wris_rivers.parquet` (150MB on disk,
17.6 million vertices) into memory costs ~1.3GB by itself — before any of our own processing runs.
`preprocess_geo_data.py` fixes this by doing the simplification and CRS reprojection **once,
offline**, and saving the small result — so Render only ever reads an already-small file. Peak
memory for the whole app went from ~1.5GB to ~400MB.

You only need to touch the raw files if the source government datasets change:

1. Download the 5 raw files (CC0, no signup, from [bharatlas.com](https://bharatlas.com)) into
   `Ecosensitive zone/Bharatmaps_Parivesh_Eco_Sensitive_Zones.parquet`,
   `Coastline/india_boundary.geojson`, `Rivers+ Streams/wris_rivers.parquet`,
   `Flood+ Innundation/ndem_floods_1998_2022.parquet`,
   `Protected Areas/GatiShakti_Wildlife_Sanctuaries_and_National_Parks.parquet`.
2. Run `python preprocess_geo_data.py` — it reads the raw files and writes the 5 small files above.
3. Commit the new small files. The raw originals stay gitignored (too large / not needed at runtime).

**Known limitation:** the coastline check uses India's national boundary outline as a proxy for
the actual High Tide Line / CRZ boundary, since no dedicated coastline layer has been sourced yet.
This also picks up land borders (Nepal/Pakistan/Bangladesh), so it's flagged `heuristic` (not
`regulatory`) in the classifier's confidence output. See the docstring in `geo_classifier.py` for
the full breakdown of what's report-verified vs. still a proxy.

---

## Default Admin Login

```
Email:    gandhijidaksh@gmail.com
Password: admin123
```

This password is only set **once** — the first time `app.py` runs against a fresh database
(`init_db()` seeds the admin row only if it doesn't already exist yet). If you've since changed
it — via **Forgot password?** on the login page, or by resetting it another way — this is no
longer your real password, and the app has no way to show you the current one back (it's stored
as a one-way hash, not recoverable). Use "Forgot password?" if you need to reset it.

> ⚠️ Change the admin password and `app.secret_key` in `app.py` before deploying publicly.

---

## How it works

### For Companies
1. Go to `http://localhost:5000`
2. Click **Create Account** — enter company name, email, password
3. After login, add PCC (collection) and PPC (processing) entries manually
4. All data is saved to the database and persists between sessions
5. Each company only sees their own data

### For Admin (IIT Delhi)
1. Login with `gandhijidaksh@gmail.com`
2. See all registered companies, their credit totals, and entry counts
3. View full access log — who logged in, when, from which IP

---

## Deploy to Render (free hosting)

1. Push to GitHub
2. Go to [render.com](https://render.com) → New Web Service
3. Connect your GitHub repo
4. Build command: `pip install -r requirements.txt`
5. Start command: `gunicorn app:app`
6. Add to requirements.txt: `gunicorn`

---

## Formulas Used

### PCC (Collection Credits)
```
PCC = Weight (t) × Location Factor (F) × Eco Factor (E) × ESG Multiplier (G)
```

### PPC (Processing Credits)
```
W   = 0.85 × log₁₀(min(15, max(1, service_life))) × Exposure Factor (P)
Net Weight = PET Fed to Process (gross) − Processing Loss/Waste
PPC = Net Weight (t) × W × ESG Multiplier (G)
```
Gross and waste are entered as two separate fields (not one ambiguous "weight processed" figure) —
matches the report's `PPC = (M_processed − M_wasted) × W × P × G` exactly.

### ESG Tiers
| Tier | Score | Multiplier |
|------|-------|------------|
| Tier I | > 80 | 1.10 |
| Tier II | 65–80 | 1.05 |
| Tier III | 50–65 | 1.00 |
| Ineligible | < 50 | 0 |
