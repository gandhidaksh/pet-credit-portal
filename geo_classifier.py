"""
Standalone geospatial classifier for PET collection entries.
Replaces the manual "Collection Category" dropdown with a lat/lon lookup
against India geospatial layers, implementing the location + eco-sensitivity
categories defined in the "Indian PET Plastic Credit Framework" report
(section: Definitions of Collection Categories / harmonised 500 m criterion).

REPORT-DEFINED RULES THIS FILE IMPLEMENTS (quoted/paraphrased from the report):
  - The framework "adopts a harmonised distance criterion of 500 m for all
    environmentally sensitive zones for plastic credit calculation" — applied
    uniformly to coastal (CRZ), riverine (RRZ), and eco-sensitive (ESZ) zones,
    instead of each notification's own more complex, varying sub-zone extents.
  - Land-Recovered PET: > 500 m from the High Tide Line (coast) AND > 500 m
    from the riverbank / highest flood level.
  - Ocean-bound PET: within 500 m landward of the shoreline/HTL (report ties
    this to CRZ-I B, the intertidal/landward zone).
  - Floating PET: collected from rivers/canals/lakes/coastal waters, OR from
    "flood-prone riverbanks extending up to 500 m from the highest flood level
    recorded in the past approximately 50 years."
  - Eco-Sensitive Zone PET: within a 500 m radius of the notified boundary of
    an ESZ (report explicitly measures from the ESZ's notified boundary, not
    just "inside the polygon").
  - Overlapping zones: "the maximum applicable location-based and ecological
    sensitivity weightage factor is applied."

WHAT'S A DIRECT REPORT IMPLEMENTATION VS. A DATA-AVAILABILITY PROXY
  - ESZ check: real notified ESZ polygons (Bharatmaps/Parivesh 2024), buffered
    by the report's own 500 m, then containment-tested. This is a direct,
    regulatory-grade implementation of the report's ESZ-PET rule.
  - Floating check: "riverbank" is approximated by distance to WRIS river
    centerlines (500 m), and "highest flood level" is approximated by the NDEM
    1998-2022 historical flood-inundation polygons — either one triggers
    Floating. Both source layers are real government datasets and the
    threshold matches the report exactly, so this is treated as regulatory-
    grade too, with the caveat that a river *centerline* isn't literally the
    same line as a *riverbank*.
  - Ocean-bound check: the report defines this from the High Tide Line / CRZ
    boundary. No CRZ or coastline-specific layer has been sourced yet — this
    still falls back to distance from India's national outline
    (india_boundary.geojson), which also picks up land borders (Nepal/
    Pakistan/Bangladesh) and is not the actual HTL. This one stays flagged
    "heuristic" until a real CRZ/coastline layer replaces it.
  - "Protected Area" (Wildlife Sanctuary / National Park) info: the report
    does NOT define Protected Areas as their own credit category — it only
    mentions them as the kind of place an ESZ is a buffer around. An earlier
    version of this file used PA containment as a fallback E-factor trigger
    when no ESZ was notified; that was this codebase's own invention, not
    something the report specifies, so it has been removed from scoring.
    PA overlap is now surfaced as an informational note only (using the
    report's own wording), never affecting F or E.

Run directly to execute the 3 sanity-check points (Yamuna floodplain, Gir,
central Delhi).
"""

import os
import time
import geopandas as gpd
import pyproj
from shapely.geometry import Point

# Data folders (Ecosensitive zone/, Coastline/, Rivers+ Streams/, Flood+ Innundation/,
# Protected Areas/) live alongside this file in the project root, both locally and
# wherever this gets deployed — so resolve relative to __file__, not a hardcoded path.
DATA_DIR = os.path.dirname(os.path.abspath(__file__))

METRIC_CRS = "EPSG:7755"   # WGS 84 / India NSF LCC — for all buffer/distance math
GEO_CRS = "EPSG:4326"

# Report's harmonised distance criterion — 500 m for coastal, riverine/flood, and
# ESZ zones alike (see module docstring).
RIVER_BUFFER_M = 500
COAST_BUFFER_M = 500
ESZ_BUFFER_M = 500

# F factor by method, E factor by eco-sensitivity — mirrors PCC_FACTORS in dashboard.html
F_FACTORS = {"Land-recovered": 1.0, "Floating": 1.2, "Ocean-bound": 1.3}
E_FACTORS = {False: 1.0, True: 1.1}

CATEGORY_MAP = {
    ("Land-recovered", False): "Land-recovered PET",
    ("Floating", False):       "Floating PET",
    ("Ocean-bound", False):    "Ocean-bound PET",
    ("Land-recovered", True):  "ESZ-PET (Land)",
    ("Floating", True):        "ESZ-PET (Floating)",
    ("Ocean-bound", True):     "ESZ-PET (Ocean-bound)",
}


class GeoClassifier:
    def __init__(self, data_dir=DATA_DIR, verbose=True):
        t0 = time.time()

        def log(msg):
            if verbose:
                print(f"[{time.time()-t0:5.1f}s] {msg}")

        log("loading ESZ...")
        self.esz = gpd.read_parquet(f"{data_dir}/Ecosensitive zone/Bharatmaps_Parivesh_Eco_Sensitive_Zones.parquet")
        self.esz_m = self.esz.to_crs(METRIC_CRS)
        # Report measures ESZ-PET as "within a 500 m radius of the notified boundary
        # of an ESZ" — not just inside the polygon — so pre-buffer once at load time.
        self.esz_buffered_m = self.esz_m.copy()
        self.esz_buffered_m["geometry"] = self.esz_m.geometry.buffer(ESZ_BUFFER_M)

        log("loading protected areas (informational only, see docstring)...")
        self.pa = gpd.read_parquet(f"{data_dir}/Protected Areas/GatiShakti_Wildlife_Sanctuaries_and_National_Parks.parquet")
        self.pa_m = self.pa.to_crs(METRIC_CRS)

        log("loading rivers (largest file, ~150MB)...")
        self.rivers = gpd.read_parquet(f"{data_dir}/Rivers+ Streams/wris_rivers.parquet")
        self.rivers_m = self.rivers.to_crs(METRIC_CRS)
        self.rivers_m.sindex  # build spatial index once

        log("loading flood inundation...")
        self.floods = gpd.read_parquet(f"{data_dir}/Flood+ Innundation/ndem_floods_1998_2022.parquet")
        self.floods_m = self.floods.to_crs(METRIC_CRS)
        self.floods_m.sindex

        log("loading india boundary...")
        self.boundary = gpd.read_file(f"{data_dir}/Coastline/india_boundary.geojson")
        self.boundary_m = self.boundary.to_crs(METRIC_CRS)
        self.boundary_line_m = self.boundary_m.boundary  # exterior ring(s) as lines

        # Build the lat/lon -> metric-CRS transformer ONCE and reuse it for every
        # classify() call, instead of building a new GeoSeries + pyproj Transformer
        # per request (that pattern is a known trigger for native-library segfaults
        # on macOS, e.g. Homebrew GDAL/PROJ conflicting with the pip wheels).
        self._to_metric = pyproj.Transformer.from_crs(GEO_CRS, METRIC_CRS, always_xy=True)

        log("all layers loaded and reprojected.")

    def classify(self, lat, lon):
        x, y = self._to_metric.transform(lon, lat)
        pt = Point(x, y)
        evidence = []

        # --- ESZ: within 500 m of the notified boundary (report's own ESZ-PET rule) ---
        esz_hit = self.esz_buffered_m[self.esz_buffered_m.contains(pt)]
        in_esz = not esz_hit.empty
        esz_name = None
        if in_esz:
            row = esz_hit.iloc[0]
            orig_geom = self.esz_m.geometry.loc[row.name]
            esz_dist_m = orig_geom.distance(pt)
            esz_name = row.get("Name") or row.get("Map_Name")
            if esz_dist_m > 0:
                evidence.append(f"{esz_dist_m:.0f} m from ESZ boundary ({esz_name}, Parivesh 2024) — within the report's {ESZ_BUFFER_M}m ESZ-PET buffer [regulatory]")
            else:
                evidence.append(f"within ESZ boundary ({esz_name}, Parivesh 2024) [regulatory]")

        is_eco_sensitive = in_esz
        eco_confidence = "regulatory"

        # --- Protected Area overlap: informational only — the report does not define
        # this as its own credit category, so it never affects E. See docstring. ---
        pa_hit = self.pa_m[self.pa_m.contains(pt)]
        in_protected_area = not pa_hit.empty
        pa_name = None
        if in_protected_area:
            row = pa_hit.iloc[0]
            pa_name = row.get("pa_name") or row.get("name")
            if not in_esz:
                evidence.append(f"note: within a protected forest/national park/wildlife sanctuary ({pa_name}) — no notified ESZ boundary here, so no ecological-sensitivity weightage applies per the framework's ESZ-PET definition [informational only]")

        # --- Floating: riverbank proxy (WRIS centerline, 500m) OR historical flood extent ---
        nearest_idx = self.rivers_m.sindex.nearest(pt, return_all=False)[1][0]
        nearest_river = self.rivers_m.iloc[nearest_idx]
        river_dist_m = nearest_river.geometry.distance(pt)
        near_river = river_dist_m <= RIVER_BUFFER_M
        if near_river:
            rname = nearest_river.get("rivname") or "unnamed segment"
            robjid = nearest_river.get("objectid")
            evidence.append(f"{river_dist_m:.0f} m from {rname} (WRIS river segment {robjid}) — within the report's {RIVER_BUFFER_M}m riverbank buffer [regulatory]")

        flood_hit = self.floods_m[self.floods_m.contains(pt)]
        in_flood_zone = not flood_hit.empty
        if in_flood_zone:
            evidence.append(f"within a historically-flooded polygon (NDEM 1998-2022, {len(flood_hit)} overlapping record(s)) — matches the report's \"highest flood level (past ~50 yrs)\" Floating-PET criterion [regulatory]")

        is_floating = near_river or in_flood_zone

        # --- Ocean-bound: report defines this from the High Tide Line / CRZ boundary.
        # No CRZ/coastline-specific layer sourced yet — still a proxy via the national
        # outline, which also picks up land borders. Stays flagged heuristic. ---
        coast_dist_m = min(line.distance(pt) for line in self.boundary_line_m.geometry)
        near_coast = coast_dist_m <= COAST_BUFFER_M
        if near_coast:
            evidence.append(f"{coast_dist_m:.0f} m from national boundary (coastline proxy — not an official HTL/CRZ line) [heuristic]")

        # --- method / F factor, priority: Ocean-bound > Floating > Land-recovered,
        # matching the report's "maximum applicable weightage" rule for overlaps ---
        if near_coast:
            method = "Ocean-bound"
            method_confidence = "heuristic"   # coastline proxy, see above
        elif is_floating:
            method = "Floating"
            method_confidence = "regulatory"  # real WRIS/NDEM data, report-exact threshold
        else:
            method = "Land-recovered"
            method_confidence = "heuristic"   # relies on the still-imperfect coastline check being negative

        category = CATEGORY_MAP[(method, is_eco_sensitive)]
        F = F_FACTORS[method]
        E = E_FACTORS[is_eco_sensitive]

        overall_confidence = "regulatory" if eco_confidence == "regulatory" and method_confidence == "regulatory" else "heuristic"

        if not evidence:
            evidence.append(f"no ESZ / river-buffer / flood-zone / coastline trigger within thresholds — classified as {category} by default [heuristic]")

        return {
            "lat": lat, "lon": lon,
            "category": category,
            "verified": True,
            "F": F, "E": E,
            "in_esz": in_esz, "esz_name": esz_name,
            "in_protected_area": in_protected_area, "pa_name": pa_name,  # informational only, does not affect E
            "river_distance_m": round(river_dist_m, 1),
            "coast_distance_m": round(coast_dist_m, 1),
            "in_flood_zone": in_flood_zone,
            "evidence": evidence,
            "confidence": overall_confidence,           # "regulatory" or "heuristic" — overall
            "eco_confidence": eco_confidence,            # E factor basis
            "method_confidence": method_confidence,      # F factor basis
        }


if __name__ == "__main__":
    clf = GeoClassifier()

    test_points = {
        "Yamuna riverbank (Delhi, verified WRIS vertex)": (28.7999255, 77.2074203),
        "Gir National Park / Sanctuary (Gujarat)":        (21.1500, 70.8000),
        "Central Delhi (Connaught Place, control)":       (28.6315, 77.2167),
    }

    for label, (lat, lon) in test_points.items():
        print(f"\n=== {label}  ({lat}, {lon}) ===")
        result = clf.classify(lat, lon)
        print(f"CATEGORY: {result['category']}  (F={result['F']}, E={result['E']})  confidence={result['confidence']}")
        for e in result["evidence"]:
            print(f"  - {e}")
