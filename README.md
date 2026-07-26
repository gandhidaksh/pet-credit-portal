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
├── requirements.txt        ← Python dependencies
├── database.db             ← SQLite database (auto-created on first run)
├── migrations/              ← SQL migrations to run against Supabase, in order (001, 002, 003)
├── templates/
│   ├── login.html          ← Login & Register page
│   ├── dashboard.html      ← Company dashboard (map-based location entry, bulk CSV upload)
│   └── admin.html          ← Admin overview
└── README.md
```

Note: the 5 geospatial datasets (Eco-Sensitive Zones, Protected Areas, Rivers, Flood Inundation,
India Boundary) are NOT committed to this repo — the rivers file alone is ~150MB, over GitHub's
100MB per-file limit. See **Geospatial Data Setup** below to download them.

---

## Setup & Run (VS Code / Local)

### 1. Install Python dependencies
```bash
pip install -r requirements.txt
```

### 2. Download the geospatial datasets
See **Geospatial Data Setup** below — `geo_classifier.py` won't run without these 5 folders present
alongside it.

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

`geo_classifier.py` needs these 5 folders to exist in the project root (same level as `app.py`).
All are CC0, direct-download, no signup required, from [bharatlas.com](https://bharatlas.com):

| Folder | File | Source |
|---|---|---|
| `Ecosensitive zone/` | `Bharatmaps_Parivesh_Eco_Sensitive_Zones.parquet` | MoEFCC-notified ESZs, Parivesh 2024 |
| `Coastline/` | `india_boundary.geojson` | National boundary (coastline proxy — see limitations below) |
| `Rivers+ Streams/` | `wris_rivers.parquet` | CWC WRIS river/stream line segments (~150MB) |
| `Flood+ Innundation/` | `ndem_floods_1998_2022.parquet` | NDEM/NRSC historical flood extents |
| `Protected Areas/` | `GatiShakti_Wildlife_Sanctuaries_and_National_Parks.parquet` | Wildlife sanctuaries & national parks |

Verify they load correctly:
```bash
python geo_classifier.py       # runs 3 sanity-check points
python validate_classifier.py  # runs the full 20-point accuracy test
```

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
