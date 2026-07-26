"""
Downloads the 5 geospatial datasets geo_classifier.py needs, into the exact
folder structure it expects. Safe to run repeatedly — skips any file that
already exists and is a reasonable size (so it won't re-download ~200MB on
every Render deploy once cached, though Render's disk is ephemeral so it will
still re-download on a fresh build).

Usage:
    python download_geo_data.py

All 5 files are CC0, direct-download, no signup required, from bharatlas.com.
"""

import os
import urllib.request

FILES = [
    (
        "https://bharatlas.com/api/dl/environment/forests/Bharatmaps_Parivesh_Eco_Sensitive_Zones.parquet",
        "Ecosensitive zone/Bharatmaps_Parivesh_Eco_Sensitive_Zones.parquet",
    ),
    (
        "https://bharatlas.com/api/dl/reference/india_boundary.geojson",
        "Coastline/india_boundary.geojson",
    ),
    (
        "https://bharatlas.com/api/dl/water/rivers/WRIS_Rivers.parquet",
        "Rivers+ Streams/wris_rivers.parquet",
    ),
    (
        "https://bharatlas.com/api/dl/environment/ndem-floods-1998-2022/NDEM_All_India_Flood_Innundation_1998_to_2022.parquet",
        "Flood+ Innundation/ndem_floods_1998_2022.parquet",
    ),
    (
        "https://bharatlas.com/api/dl/environment/forests/GatiShakti_Wildlife_Sanctuaries_and_National_Parks.parquet",
        "Protected Areas/GatiShakti_Wildlife_Sanctuaries_and_National_Parks.parquet",
    ),
]

MIN_EXPECTED_BYTES = 10_000  # sanity floor — a truncated/failed download will be far smaller than this


def download_all():
    base_dir = os.path.dirname(os.path.abspath(__file__))

    for url, rel_path in FILES:
        dest = os.path.join(base_dir, rel_path)
        os.makedirs(os.path.dirname(dest), exist_ok=True)

        if os.path.exists(dest) and os.path.getsize(dest) > MIN_EXPECTED_BYTES:
            print(f"skip (already present): {rel_path}")
            continue

        print(f"downloading: {rel_path} ...")
        try:
            urllib.request.urlretrieve(url, dest)
            size_mb = os.path.getsize(dest) / (1024 * 1024)
            print(f"  done ({size_mb:.1f} MB)")
        except Exception as e:
            print(f"  FAILED: {e}")
            raise


if __name__ == "__main__":
    download_all()
    print("\nAll geospatial datasets ready.")
