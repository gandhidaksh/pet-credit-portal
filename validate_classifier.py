"""
Quantitative validation harness for geo_classifier.GeoClassifier.

WHAT THIS DOES
Builds a ~20-point ground-truth set across the classifier's 4 outcome classes and
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

from geo_classifier import GeoClassifier


def infer_method(category):
    if "Floating" in category:
        return "Floating"
    if "Ocean-bound" in category:
        return "Ocean-bound"
    return "Land-recovered"


def build_ground_truth(clf, n_per_class=5):
    cases = []

    # 1. ESZ interior points -> expect eco-sensitive True
    esz_sample = clf.esz.sample(n=min(n_per_class, len(clf.esz)), random_state=42)
    for _, row in esz_sample.iterrows():
        pt = row.geometry.representative_point()
        cases.append({
            "label": "ESZ (interior point)", "lat": pt.y, "lon": pt.x,
            "expect_eco": True, "source": row.get("Name") or row.get("Map_Name") or "unnamed ESZ",
        })

    # 2. Protected Area interior points that do NOT also fall inside an ESZ —
    #    per the report, PA alone is NOT a credit category, so these should come
    #    back non-eco-sensitive (E=1.0), confirming PA no longer leaks into scoring.
    pa_pool = clf.pa.sample(n=min(n_per_class * 4, len(clf.pa)), random_state=7)
    added = 0
    for _, row in pa_pool.iterrows():
        if added >= n_per_class:
            break
        pt = row.geometry.representative_point()
        if clf.esz[clf.esz.contains(pt)].empty:
            cases.append({
                "label": "Protected Area (non-scoring)", "lat": pt.y, "lon": pt.x,
                "expect_eco": False, "source": row.get("pa_name") or row.get("name") or "unnamed PA",
            })
            added += 1

    # 3. River vertices -> expect method == Floating
    river_sample = clf.rivers.sample(n=min(n_per_class, len(clf.rivers)), random_state=99)
    for _, row in river_sample.iterrows():
        geom = row.geometry
        line = geom if geom.geom_type == "LineString" else list(geom.geoms)[0]
        coords = list(line.coords)
        coord = coords[len(coords) // 2]
        cases.append({
            "label": "River (vertex)", "lat": coord[1], "lon": coord[0],
            "expect_method": "Floating",
            "source": row.get("rivname") or f"WRIS segment {row.get('objectid')}",
        })

    # 4. Remote interior control points -> expect Land-recovered, non-eco
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
