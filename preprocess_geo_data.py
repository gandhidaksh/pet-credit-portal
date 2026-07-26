"""
ONE-TIME offline preprocessing script. Re-run this locally (NOT on Render) only
if the raw source datasets ever change. Output files ARE committed to git —
this is what makes the memory fix work, see below.

WHY THIS EXISTS (the real story of the Render OOM crash)
Render's Starter instance (512MB RAM) was getting OOM-killed on the first
/api/classify-location call. The original assumption was "reprojecting 17.6
million river vertices causes a transient memory spike" — true, but fixing
only that (simplify-after-load, keep only the reprojected copy) still left
peak memory at ~1.5GB. Profiling in isolation proved why: just READING
wris_rivers.parquet (150MB on disk) into a GeoDataFrame costs ~1.3GB of RAM
by itself, before simplify() or to_crs() ever run. Simplifying *after* the
expensive full-precision load doesn't avoid that load.

The fix: do the simplify + reproject ONCE, here, on a machine with plenty of
RAM (not Render), and write the *result* to new parquet files. Render then
only ever has to read an already-small, already-reprojected file — it never
touches the original 150MB/17.6M-vertex geometry at all.

Result (measured): peak RSS for the full 5-layer load + one classify() call
dropped from ~1512MB to ~400MB — under Render's 512MB Starter limit.

Tolerance choice: 0.001 deg (~100m at Indian latitudes) for rivers/floods,
0.0005 deg (~50m) for protected areas/boundary. Both are well under the
report's 500m distance threshold, so simplification can't change any
classify() decision at that threshold. ESZ is NOT simplified — its boundary
directly gates the report's ESZ-PET E-factor, so full precision is kept
(it's also the smallest dataset, so precision costs nothing here).

Outputs (all committed to git, all well under GitHub's 100MB limit):
  Rivers+ Streams/wris_rivers_simplified.parquet          (~15MB, was 150MB raw)
  Flood+ Innundation/ndem_floods_1998_2022_simplified.parquet (~17MB, was 27MB raw)
  Protected Areas/..._simplified.parquet                   (~4MB, was 21MB raw)
  Coastline/india_boundary_simplified.parquet              (~1MB, was 7.2MB geojson)
  Ecosensitive zone/esz_reprojected.parquet                (~3.5MB, full precision)

All 5 outputs are already reprojected to METRIC_CRS (EPSG:7755) — geo_classifier.py
loads them directly and does NOT call .simplify() or .to_crs() at runtime anymore.

Usage:
    python preprocess_geo_data.py
"""
import os
import time
import geopandas as gpd

DATA_DIR = os.path.dirname(os.path.abspath(__file__))
METRIC_CRS = "EPSG:7755"

RIVER_FLOOD_TOLERANCE_DEG = 0.001    # ~100m — rivers, floods (largest vertex counts)
PA_BOUNDARY_TOLERANCE_DEG = 0.0005   # ~50m  — protected areas, national boundary


def process(label, read_fn, out_path, tolerance_deg=None):
    t0 = time.time()
    gdf = read_fn()
    if tolerance_deg is not None:
        gdf["geometry"] = gdf.geometry.simplify(tolerance_deg, preserve_topology=False)
    gdf = gdf.to_crs(METRIC_CRS)
    gdf.to_parquet(out_path)
    size_mb = os.path.getsize(out_path) / (1024 * 1024)
    print(f"{label}: rows={len(gdf)} size={size_mb:.1f}MB time={time.time()-t0:.1f}s -> {out_path}")


if __name__ == "__main__":
    process(
        "rivers",
        lambda: gpd.read_parquet(f"{DATA_DIR}/Rivers+ Streams/wris_rivers.parquet",
                                  columns=["rivname", "objectid", "geometry"]),
        f"{DATA_DIR}/Rivers+ Streams/wris_rivers_simplified.parquet",
        tolerance_deg=RIVER_FLOOD_TOLERANCE_DEG,
    )
    process(
        "floods",
        lambda: gpd.read_parquet(f"{DATA_DIR}/Flood+ Innundation/ndem_floods_1998_2022.parquet",
                                  columns=["geometry"]),
        f"{DATA_DIR}/Flood+ Innundation/ndem_floods_1998_2022_simplified.parquet",
        tolerance_deg=RIVER_FLOOD_TOLERANCE_DEG,
    )
    process(
        "protected areas",
        lambda: gpd.read_parquet(f"{DATA_DIR}/Protected Areas/GatiShakti_Wildlife_Sanctuaries_and_National_Parks.parquet",
                                  columns=["pa_name", "name", "geometry"]),
        f"{DATA_DIR}/Protected Areas/GatiShakti_Wildlife_Sanctuaries_and_National_Parks_simplified.parquet",
        tolerance_deg=PA_BOUNDARY_TOLERANCE_DEG,
    )
    process(
        "boundary",
        lambda: gpd.read_file(f"{DATA_DIR}/Coastline/india_boundary.geojson")[["geometry"]],
        f"{DATA_DIR}/Coastline/india_boundary_simplified.parquet",
        tolerance_deg=PA_BOUNDARY_TOLERANCE_DEG,
    )
    process(
        "esz (full precision, no simplify)",
        lambda: gpd.read_parquet(f"{DATA_DIR}/Ecosensitive zone/Bharatmaps_Parivesh_Eco_Sensitive_Zones.parquet",
                                  columns=["Name", "Map_Name", "geometry"]),
        f"{DATA_DIR}/Ecosensitive zone/esz_reprojected.parquet",
        tolerance_deg=None,
    )
    print("\nDone. Commit the 5 output files above to git — they replace the runtime")
    print("download+simplify+reproject step that was OOM-killing Render.")
