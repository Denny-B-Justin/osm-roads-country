"""
dev/make_mock_data.py
---------------------
Builds a local stand-in for the Volume folder so the app runs without Databricks:

    dev/mock_volume/manifest.json
    dev/mock_volume/<iso2>_roads.zip      random road lines, same layout as the real files

Then run the app on it:

    python dev/make_mock_data.py
    ROADS_LOCAL_DIR=dev/mock_volume python app.py        (Windows: set ROADS_LOCAL_DIR=dev\\mock_volume)

The rows are random lines, not real roads. Vietnam gets 420,000 rows so the
multi-part case (3 CSV files) is exercised; every other country gets a few
hundred to a few thousand rows.
"""

import csv
import io
import json
import os
import random
import sys
import zipfile
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, os.pardir))

import countries as cc  # noqa: E402

OUT = os.path.join(HERE, "mock_volume")
ROWS_PER_PART = 200_000
COLUMNS = ["osm_id", "name", "kind", "ref", "surface", "surface_class", "oneway", "bridge", "tunnel",
           "geometry", "source_year"]
KINDS = ["residential"] * 30 + ["service"] * 18 + ["track"] * 12 + ["unclassified"] * 12 + \
        ["tertiary"] * 8 + ["secondary"] * 6 + ["primary"] * 4 + ["trunk"] * 2 + ["motorway"] + \
        ["living_street", "road", "motorway_link", "trunk_link", "primary_link"]
SURFACES = [("", "")] * 6 + [("asphalt", "paved"), ("paved", "paved"), ("concrete", "paved"),
                             ("gravel", "unpaved"), ("dirt", "unpaved"), ("unpaved", "unpaved")]

# The 28 codes that failed in the extraction run (Germany has since succeeded).
NOT_AVAILABLE = {"AW", "AI", "AG", "BM", "BB", "CC", "CX", "KY", "DM", "EH", "FK", "GI", "GD", "IO",
                 "KN", "LC", "MS", "NF", "SJ", "SM", "PM", "TC", "TT", "UM", "VA", "VC", "VG"}
CLIPPED = {"AE": "gcc-states", "BH": "gcc-states", "KW": "gcc-states", "OM": "gcc-states",
           "QA": "gcc-states", "SA": "gcc-states", "MY": "malaysia-singapore-brunei",
           "SG": "malaysia-singapore-brunei", "BN": "malaysia-singapore-brunei", "HT": "haiti-and-domrep",
           "DO": "haiti-and-domrep", "IL": "israel-and-palestine", "PS": "israel-and-palestine",
           "SN": "senegal-and-gambia", "GM": "senegal-and-gambia", "AS": "american-oceania",
           "GU": "american-oceania", "MP": "american-oceania", "IE": "ireland-and-northern-ireland",
           "ID": "indonesia"}


def random_row(rng, osm_id, year):
    lon, lat = rng.uniform(-170, 170), rng.uniform(-50, 60)
    pts = []
    for _ in range(rng.randint(2, 7)):
        lon += rng.uniform(-0.002, 0.002)
        lat += rng.uniform(-0.002, 0.002)
        pts.append(f"{lon:.7f} {lat:.7f}")
    surface, surface_class = rng.choice(SURFACES)
    name = rng.choice(["", "", "Main Street", 'Rue "Neuve"', "Đường Lê Lợi", "Old Mill Road, North"])
    return [osm_id, name, rng.choice(KINDS), rng.choice(["", "", "A1", "NH 44"]), surface, surface_class,
            rng.choice(["", "", "yes"]), rng.choice(["", "", "", "yes"]), "", "LINESTRING (" + ", ".join(pts) + ")",
            year]


def readme(name, iso2, rows, parts, extracted):
    if parts == 1:
        first = f"This CSV file holds all {rows:,} road segments for {name} ({iso2})."
    else:
        first = (f"These {parts} CSV files together hold all {rows:,} road segments for {name} ({iso2}). "
                 f"Rows were split into files of at most {ROWS_PER_PART:,} in no particular order, so "
                 "append all parts before using the data.")
    return "\r\n".join([
        f"OpenStreetMap roads - {name} ({iso2})", "", first,
        f"Road data (c) OpenStreetMap contributors, available under the Open Database License (ODbL): "
        "https://www.openstreetmap.org/copyright. Extracted from Geofabrik (download.geofabrik.de) "
        f"on {extracted}.", "",
    ])


def main():
    os.makedirs(OUT, exist_ok=True)
    rng = random.Random(7)
    now = datetime.now(timezone.utc)
    extracted = now.date().isoformat()
    manifest = {"manifest_version": 1, "updated_at": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
                "rows_per_part": ROWS_PER_PART, "countries": {}}

    for iso2 in cc.tracked_codes():
        if iso2 in NOT_AVAILABLE:
            continue
        name = cc.country_name(iso2)
        rows = 420_000 if iso2 == "VN" else rng.randint(300, 4000)
        parts = -(-rows // ROWS_PER_PART)
        file = f"{iso2.lower()}_roads.zip"
        path = os.path.join(OUT, file)
        osm_id = rng.randint(10_000_000, 900_000_000)
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            left = rows
            for p in range(1, parts + 1):
                n = min(ROWS_PER_PART, left)
                left -= n
                buf = io.StringIO()
                writer = csv.writer(buf, lineterminator="\n")
                writer.writerow(COLUMNS)
                for _ in range(n):
                    osm_id += rng.randint(1, 50)
                    writer.writerow(random_row(rng, osm_id, now.year))
                zf.writestr(f"road_openstreetmap_{iso2.lower()}_part{p:05d}.csv", buf.getvalue().encode("utf-8"))
            zf.writestr("README.txt", readme(name, iso2, rows, parts, extracted).encode("utf-8"))
        manifest["countries"][iso2] = {
            "iso2": iso2, "name": name, "file": file, "size_bytes": os.path.getsize(path), "rows": rows,
            "parts": parts, "columns": COLUMNS, "extracted_at": extracted,
            "built_at": now.isoformat(timespec="seconds"), "extract": CLIPPED.get(iso2),
            "shared_extract": iso2 in CLIPPED, "clipped": iso2 in CLIPPED,
        }

    with open(os.path.join(OUT, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=1)
    print(f"wrote {len(manifest['countries'])} countries to {OUT}")


if __name__ == "__main__":
    main()
