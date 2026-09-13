"""
Quantitative validation harness for geo_classifier.GeoClassifier.

WHAT THIS DOES
Builds a ~27-point ground-truth set across the classifier's outcome classes and
reports per-class and overall accuracy. Use the printed table/summary directly in
the report or demo as the "quantitative evaluation" evidence.

METHODOLOGY, AND ITS HONEST LIMITS (read before citing these numbers)
- ESZ positive cases are sampled as interior points taken directly FROM the
  notified ESZ boundary polygons themselves (via .representative_point()).
  A point generated this way is inside that polygon by construction, independent
  of anything geo_classifier.py does — so this is a genuine, non-circular test of
  whether classify() correctly implements CRS reprojection + polygon containment.
  It is NOT testing against independently field-collected GPS records.
- Protected Area (sanctuary/national park) cases are sampled the same way, but
  per the report, Protected Areas are NOT their own credit category — only ESZ
  is. So these cases test the opposite of what an earlier version of this script
  checked: a point inside a Protected Area with no notified ESZ overlap should
  come back NOT eco-sensitive (informational note only, E stays 1.0).
- River positive cases are sampled as vertices taken directly FROM the river
  line geometries — same logic: distance-to-self is 0 by construction, so this
  tests whether the buffer/distance logic is implemented correctly.
- Ocean-bound positive cases are sampled the same way, as vertices taken
  directly FROM the national-boundary line geo_classifier.py itself measures
  coast_distance_m against, restricted to bounding boxes along the actual sea
  coast so a land-border vertex (Pakistan/Nepal/Bangladesh side) of that same
  boundary layer isn't picked instead. This was previously untested — there
  was no way to hit the classifier's 500 m coastline threshold by clicking a
  point on a map by eye, since that boundary layer is a *simplified* national
  outline, not a precise, official HTL/CRZ line; this class replaces "guess a
  beach's coordinates" with "sample the exact line the code checks against."
- The report's Table 5 defines six category labels (Land-recovered, Floating,
  Ocean-bound, and their three ESZ-overlap counterparts), but the classifier
  computes them as CATEGORY_MAP[(method, is_eco_sensitive)] — a static lookup
  over two INDEPENDENTLY determined values, not six separate code paths. So
  the ESZ/PA/River/Coastline/Land-control cases above, which each test one
  axis at a time, already logically cover all six combinations. Two explicit
  combined cases are included anyway (ESZ x river overlap, ESZ x coastline
  overlap, below) to show combined categories firing on real points rather
  than resting on that lookup-table argument alone. The sixth and last
  category, ESZ-PET (Land), isn't listed as its own explicit case only because
  it already turns up, unlabelled, among the plain ESZ cases above (e.g. Gaga
  Bird Sanctuary resolves to ESZ-PET (Land)).
- Both ESZ-overlap cases independently re-check — against the raw river/
  coastline layers directly, NOT by calling classify() first — that a real
  notified ESZ polygon's point is also within the report's 500 m river or
  coastline buffer, then confirm classify() agrees on both axes at once.
- Land-control negative cases are picked from genuinely remote interior points
  (deep Thar Desert, central Deccan plateau) chosen for known geographic reasons
  (arid, non-riverine, no notified sensitive zones), not by pre-running the
  classifier and cherry-picking favorable output.
- Bottom line: this validates that the implementation correctly recovers cases
  that are true by construction / by independent geographic reasoning — i.e. it
  is a correctness/regression test, not a substitute for validating against real,
  field-verified collection-site GPS records. Say exactly that if asked "how was
  this validated" — overclaiming it as field-validated accuracy would be a much
  weaker position to defend than being precise about what it actually shows.
"""

import pyproj
from geo_classifier import GeoClassifier, METRIC_CRS, GEO_CRS

# geo_classifier.py only keeps the metric-CRS (reprojected) copy of each dataset in
# memory now — an earlier version kept both the raw lat/lon copy AND the metric copy
# of everything, which (combined with loading every unused source column) was enough
# to exceed a 512MB Render instance's memory limit on the first real classify() call.
# This script needs lat/lon points for its test cases, so it reprojects the handful
# of sampled geometries back to degrees itself, rather than the classifier keeping a
# second full copy of every dataset just for this one dev/test script's benefit.
_to_geo = pyproj.Transformer.from_crs(METRIC_CRS, GEO_CRS, always_xy=True)


def to_lat_lon(point_m):
    lon, lat = _to_geo.transform(point_m.x, point_m.y)
    return lat, lon


def infer_method(category):
    if "Floating" in category:
        return "Floating"
    if "Ocean-bound" in category:
        return "Ocean-bound"
    return "Land-recovered"


def build_ground_truth(clf, n_per_class=5):
    cases = []

    # 1. ESZ interior points -> expect eco-sensitive True
    esz_sample = clf.esz_m.sample(n=min(n_per_class, len(clf.esz_m)), random_state=42)
    for _, row in esz_sample.iterrows():
        pt_m = row.geometry.representative_point()
        lat, lon = to_lat_lon(pt_m)
        cases.append({
            "label": "ESZ (interior point)", "lat": lat, "lon": lon,
            "expect_eco": True, "source": row.get("Name") or row.get("Map_Name") or "unnamed ESZ",
        })

    # 2. Protected Area interior points that do NOT also fall inside an ESZ —
    #    per the report, PA alone is NOT a credit category, so these should come
    #    back non-eco-sensitive (E=1.0), confirming PA no longer leaks into scoring.
    pa_pool = clf.pa_m.sample(n=min(n_per_class * 4, len(clf.pa_m)), random_state=7)
    added = 0
    for _, row in pa_pool.iterrows():
        if added >= n_per_class:
            break
        pt_m = row.geometry.representative_point()
        if clf.esz_m[clf.esz_m.contains(pt_m)].empty:
            lat, lon = to_lat_lon(pt_m)
            cases.append({
                "label": "Protected Area (non-scoring)", "lat": lat, "lon": lon,
                "expect_eco": False, "source": row.get("pa_name") or row.get("name") or "unnamed PA",
            })
            added += 1

    # 3. River vertices -> expect method == Floating
    river_sample = clf.rivers_m.sample(n=min(n_per_class, len(clf.rivers_m)), random_state=99)
    for _, row in river_sample.iterrows():
        geom = row.geometry
        line = geom if geom.geom_type == "LineString" else list(geom.geoms)[0]
        coords = list(line.coords)
        coord_m = coords[len(coords) // 2]
        lon, lat = _to_geo.transform(coord_m[0], coord_m[1])
        cases.append({
            "label": "River (vertex)", "lat": lat, "lon": lon,
            "expect_method": "Floating",
            "source": row.get("rivname") or f"WRIS segment {row.get('objectid')}",
        })

    # 4. Coastline vertices -> expect method == Ocean-bound
    #    Sampled directly FROM the same national-boundary line geo_classifier.py
    #    measures coast_distance_m against (india_boundary_simplified.parquet) —
    #    same logic as the River-vertex cases above: distance-to-self is 0 by
    #    construction, so this tests whether the buffer/distance logic for the
    #    Ocean-bound branch is implemented correctly. Restricted to bounding
    #    boxes along the actual sea coast (west coast south of the Pakistan
    #    border latitude band; east coast south of the Bangladesh border
    #    latitude band) so a land-border vertex of the same boundary layer
    #    isn't picked by mistake — see geo_classifier.py's own docstring note
    #    that this proxy "also picks up land borders."
    coastal_vertices = []
    for geom in clf.boundary_line_m.geometry:
        lines = [geom] if geom.geom_type == "LineString" else list(geom.geoms)
        for line in lines:
            for x, y in line.coords:
                lon, lat = _to_geo.transform(x, y)
                west_coast = 68 <= lon <= 77.5 and lat <= 23.5
                east_coast = 77.5 <= lon <= 87.5 and lat <= 21.5
                if west_coast or east_coast:
                    coastal_vertices.append((lat, lon))
    step = max(1, len(coastal_vertices) // n_per_class)
    for lat, lon in coastal_vertices[::step][:n_per_class]:
        cases.append({
            "label": "Coastline (vertex)", "lat": lat, "lon": lon,
            "expect_method": "Ocean-bound",
            "source": "india_boundary_simplified.parquet vertex",
        })

    # 5. ESZ x Floating overlap, and ESZ x Ocean-bound overlap -> expect
    #    eco=True AND method=Floating / Ocean-bound (the combined "ESZ-PET
    #    (Floating)" and "ESZ-PET (Ocean-bound)" categories from the report's
    #    Table 5). The other test groups above deliberately validate the ESZ
    #    axis and the method axis SEPARATELY, because the final category label
    #    is just CATEGORY_MAP[(method, is_eco_sensitive)] — a static two-key
    #    lookup, not a separate computation — so proving each axis correct
    #    already logically covers all six combinations in the lookup table.
    #    Both cases below exist anyway, as an explicit, labelled demonstration
    #    of a combined category firing on real data rather than resting on
    #    that lookup-table argument alone: each independently re-checks (using
    #    the raw river/coastline layers directly, NOT by calling classify()
    #    first) that a real notified ESZ polygon's point is also within the
    #    report's 500 m river or coastline buffer, then confirms classify()
    #    agrees on both axes at once. (ESZ-PET (Land) — the sixth and last
    #    category — already turns up unlabelled among the plain "ESZ (interior
    #    point)" cases above, e.g. Gaga Bird Sanctuary, so between the two
    #    explicit cases here and that one, all six of the report's category
    #    labels are exercised somewhere in this test set.)
    esz_x_river = None
    for _, row in clf.esz_m.iterrows():
        pt_m = row.geometry.representative_point()
        nearest_idx = clf.rivers_m.sindex.nearest(pt_m, return_all=False)[1][0]
        river_dist_m = clf.rivers_m.iloc[nearest_idx].geometry.distance(pt_m)
        if river_dist_m <= 500:
            lat, lon = to_lat_lon(pt_m)
            esz_x_river = {
                "label": "ESZ x river overlap (ESZ-PET Floating)", "lat": lat, "lon": lon,
                "expect_eco": True, "expect_method": "Floating",
                "source": row.get("Name") or row.get("Map_Name") or "unnamed ESZ",
            }
            break
    if esz_x_river:
        cases.append(esz_x_river)

    esz_x_coast = None
    for _, row in clf.esz_m.iterrows():
        pt_m = row.geometry.representative_point()
        coast_dist_m = min(line.distance(pt_m) for line in clf.boundary_line_m.geometry)
        if coast_dist_m <= 500:
            lat, lon = to_lat_lon(pt_m)
            esz_x_coast = {
                "label": "ESZ x coastline overlap (ESZ-PET Ocean-bound)", "lat": lat, "lon": lon,
                "expect_eco": True, "expect_method": "Ocean-bound",
                "source": row.get("Name") or row.get("Map_Name") or "unnamed ESZ",
            }
            break
    if esz_x_coast:
        cases.append(esz_x_coast)

    # 6. Remote interior control points -> expect Land-recovered, non-eco
    #    Chosen for independent geographic reasons (arid/non-riverine interior),
    #    not by pre-checking against the classifier.
    #    Note: an earlier candidate near Jaisalmer (26.85, 70.55) was dropped after
    #    the classifier correctly flagged it as inside Desert National Park — a real
    #    notified Protected Area that the original "empty desert" assumption missed.
    #    That's worth citing directly: it's a case of the software catching a wrong
    #    human assumption, not a false positive.
    controls = {
        "Central Thar Desert (Rajasthan)": (27.0, 71.0),
        "Nagaur rural interior (Rajasthan)": (27.2, 73.5),
        "Interior Deccan plateau (Karnataka)": (16.5, 76.5),
        "Bundelkhand plateau (MP/UP border)":  (25.0, 79.5),
        "Interior Telangana plateau":       (18.0, 79.0),
    }
    for name, (lat, lon) in list(controls.items())[:n_per_class]:
        cases.append({
            "label": "Land control", "lat": lat, "lon": lon,
            "expect_method": "Land-recovered", "expect_eco": False, "source": name,
        })

    return cases


def run_validation():
    clf = GeoClassifier(verbose=False)
    cases = build_ground_truth(clf)

    total, correct = 0, 0
    print(f"{'label':<26} {'source':<32} {'expected':<28} {'actual':<28} {'ok'}")
    print("-" * 120)
    for case in cases:
        r = clf.classify(case["lat"], case["lon"])
        actual_eco = r["in_esz"]  # E factor is ESZ-only per the report — PA is informational only
        actual_method = infer_method(r["category"])

        checks = []
        if "expect_eco" in case:
            checks.append(("eco", case["expect_eco"], actual_eco))
        if "expect_method" in case:
            checks.append(("method", case["expect_method"], actual_method))

        row_ok = all(exp == act for _, exp, act in checks)
        total += 1
        correct += 1 if row_ok else 0

        expected_str = ", ".join(f"{k}={v}" for k, v, _ in checks)
        actual_str = ", ".join(f"{k}={a}" for k, _, a in checks)
        mark = "PASS" if row_ok else "FAIL"
        print(f"{case['label']:<26} {str(case['source'])[:31]:<32} {expected_str:<28} {actual_str:<28} {mark}")

    print("-" * 120)
    print(f"Overall: {correct}/{total} correct ({100*correct/total:.1f}%)")


if __name__ == "__main__":
    run_validation()
