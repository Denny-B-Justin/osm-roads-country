"""
tests/test_zip_notebook.py

Run:  pip install "pyspark>=3.5" pandas pyarrow "shapely>=2.0,<3"   (and Java 17+), then
      python tests/test_zip_notebook.py

Runs databricks/osm_roads_build_zips.py on a local Spark against test tables and checks the output.

Only the Databricks-specific bits are replaced: catalog/schema/paths point at a temp folder, dbutils.fs.rm
is shutil.rmtree, and table_version() reads table stats because DESCRIBE DETAIL is Delta-only.
"""
import glob
import io
import json
import os
import shutil
import sys
import tempfile
import zipfile

import pandas as pd
from pyspark.sql import SparkSession
from pyspark.sql.types import LongType, StringType, StructField, StructType

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NB = os.path.join(ROOT_DIR, "databricks", "osm_roads_build_zips.py")
os.environ.setdefault("PYSPARK_PYTHON", sys.executable)
os.environ.setdefault("PYSPARK_DRIVER_PYTHON", sys.executable)
ROOT = tempfile.mkdtemp(prefix="osmzip_")
OUT = os.path.join(ROOT, "volume")

spark = (SparkSession.builder.master("local[4]").appName("zip-test")
         .config("spark.sql.warehouse.dir", os.path.join(ROOT, "warehouse"))
         .config("spark.sql.shuffle.partitions", "8")
         .config("spark.driver.memory", "3g")
         .config("spark.ui.enabled", "false")
         .getOrCreate())
spark.sparkContext.setLogLevel("ERROR")
spark.sql("CREATE DATABASE IF NOT EXISTS osmtest")


class _FS:
    @staticmethod
    def rm(path, recurse=False):
        if os.path.isdir(path):
            shutil.rmtree(path)
            return True
        if os.path.exists(path):
            os.remove(path)
            return True
        return False


class _DBUtils:
    fs = _FS()


SCHEMA_V1 = StructType([
    StructField("osm_id", LongType()), StructField("name", StringType()), StructField("kind", StringType()),
    StructField("geometry", StringType()), StructField("source_year", LongType()),
])


def wkt(lon, lat, n=3):
    return "LINESTRING (" + ", ".join(f"{lon + i * 0.0001:.7f} {lat + i * 0.0001:.7f}" for i in range(n)) + ")"


NAMES = [None, "", "Main Street", 'Rue "Neuve", Nord', "Đường Lê Lợi", "Line\nbreak road", "طريق الملك فهد", "Back\\slash"]


def make_rows(n, lon, lat, start_id):
    return [(start_id + i, NAMES[i % len(NAMES)], "residential", wkt(lon + (i % 500) * 0.001, lat + (i // 500) * 0.0001), 2026)
            for i in range(n)]


def save(table, rows, schema=SCHEMA_V1, append=False):
    # several small appends, like the extraction notebook's 200k-row chunks
    df = spark.createDataFrame(rows, schema)
    df.repartition(6).write.mode("append" if append else "overwrite").format("parquet").saveAsTable(f"osmtest.{table}")


# Vietnam: 450,123 rows -> 3 parts. Bahrain: GCC extract with Bahrain + Saudi rows. Vanuatu: 2 rows.
save("osm_geofabrik_vn", make_rows(450_123, 105.0, 21.0, 1_000_000))
bh_inside = make_rows(1_234, 50.45, 26.05, 5_000_000)[:1_234]
bh_inside = [(r[0], r[1], r[2], wkt(50.45 + (i % 30) * 0.005, 26.05 + (i // 30) * 0.003), r[4]) for i, r in enumerate(bh_inside)]
sa_rows = [(9_000_000 + i, "Saudi road", "primary", wkt(46.7 + i * 0.001, 24.7), 2026) for i in range(3_000)]
crossing = [(9_999_999, "Causeway", "trunk", "LINESTRING (50.30 26.10, 50.10 26.15)", 2026)]   # starts in buffer zone
save("osm_geofabrik_bh", bh_inside + sa_rows + crossing)
save("osm_geofabrik_vu", [(1, "A", "track", wkt(168.3, -17.7), 2026), (2, None, "road", wkt(168.4, -17.8), 2026)])
save("osm_geofabrik_run_log", [(1, "x", "y", "z", 1)])
save("osm_geofabrik_de__new", [(1, "x", "y", wkt(10, 50), 1)])
spark.createDataFrame(
    [("BHR", json.dumps({"type": "Polygon", "coordinates": [[[50.3, 25.75], [50.8, 25.75], [50.8, 26.35], [50.3, 26.35], [50.3, 25.75]]]})),
     ("SAU", json.dumps({"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[34, 16], [56, 16], [56, 32], [34, 32], [34, 16]]]}}))],
    "iso_a3 string, geometry_json string").write.mode("overwrite").format("parquet").saveAsTable("osmtest.cbd_world_boundaries_dissolved")

# ── run the notebook cells ──────────────────────────────────────────────────
source = open(NB, encoding="utf-8").read()
cells = [c.strip() for c in source.split("# COMMAND ----------")]
g = {"spark": spark, "dbutils": _DBUtils(), "__name__": "__notebook__"}


def run_cell(cell):
    if cell.startswith("# Databricks notebook source"):
        cell = cell.split("\n", 1)[1].strip()
    if not cell or cell.startswith("# MAGIC") or "restartPython" in cell:
        return
    exec(compile(cell, NB, "exec"), g)


def overrides():
    g.update(CATALOG="spark_catalog", SCHEMA="osmtest", OUT_DIR=OUT, STAGING_DIR=os.path.join(OUT, "_staging"),
             BOUNDARY_TABLE="spark_catalog.osmtest.cbd_world_boundaries_dissolved",
             LOCAL_DIR=os.path.join(ROOT, "local"))


def fake_table_version(table):
    n = spark.table(table).count()
    return f"fake|{table}|{n}", "2026-10-16"


for cell in cells:
    run_cell(cell)
    if "CATALOG = \"prd_mega\"" in cell:
        overrides()
    if "def table_version" in cell:
        g["table_version"] = fake_table_version
    if "Build the zips" in cell:
        break

summary_cells = [c for c in cells if "OSM ROAD ZIPS COMPLETE" in c or "Check the published files" in c]
for c in summary_cells:
    run_cell(c)

# ── checks ───────────────────────────────────────────────────────────────
ok = True


def check(cond, msg):
    global ok
    print(("PASS " if cond else "FAIL ") + msg)
    ok &= bool(cond)


manifest = json.load(open(os.path.join(OUT, "manifest.json")))
check(sorted(manifest["countries"]) == ["BH", "VN", "VU"], f"manifest countries {sorted(manifest['countries'])}")
check(not os.path.exists(os.path.join(OUT, "_staging")), "staging folder removed")
check(sorted(os.listdir(OUT)) == ["bh_roads.zip", "manifest.json", "vn_roads.zip", "vu_roads.zip"], f"volume contents {sorted(os.listdir(OUT))}")


def read_zip(path):
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        parts = [n for n in names if n.endswith(".csv")]
        frames = [pd.read_csv(io.BytesIO(zf.read(n)), keep_default_na=False, dtype=str) for n in parts]
        readme = zf.read("README.txt").decode("utf-8")
    return names, frames, readme


names, frames, readme = read_zip(os.path.join(OUT, "vn_roads.zip"))
check(names == ["road_openstreetmap_vn_part00001.csv", "road_openstreetmap_vn_part00002.csv",
                "road_openstreetmap_vn_part00003.csv", "README.txt"], f"VN zip names {names}")
check(all(len(f) <= 200_000 for f in frames), f"VN part sizes {[len(f) for f in frames]}")
vn = pd.concat(frames, ignore_index=True)
check(len(vn) == 450_123 and vn["osm_id"].nunique() == 450_123, f"VN rows {len(vn)}")
check(list(vn.columns) == ["osm_id", "name", "kind", "geometry", "source_year"], f"VN columns {list(vn.columns)}")
src = spark.table("osmtest.osm_geofabrik_vn").toPandas()
src["name"] = src["name"].fillna("").str.replace(r"[\r\n]+", " ", regex=True)
merged = vn.assign(osm_id=vn["osm_id"].astype("int64")).merge(src, on="osm_id", suffixes=("", "_src"))
check((merged["name"] == merged["name_src"]).all(), "names survive quoting (quotes, commas, unicode, backslash)")
check((merged["geometry"] == merged["geometry_src"]).all(), "geometry WKT identical")
check("Line break road" in set(vn["name"]), "line breaks replaced by a space")
m = manifest["countries"]["VN"]
check(m["rows"] == 450_123 and m["parts"] == 3 and m["size_bytes"] == os.path.getsize(os.path.join(OUT, "vn_roads.zip")), "VN manifest numbers")
check("These 3 CSV files together hold all 450,123 road segments for Vietnam (VN)." in readme, "VN README text")
print(readme)

names, frames, readme = read_zip(os.path.join(OUT, "bh_roads.zip"))
bh = pd.concat(frames, ignore_index=True)
ids = set(bh["osm_id"].astype(int))
check(len(bh) == 1_235 and 9_999_999 in ids and not any(9_000_000 <= i < 9_003_000 for i in ids),
      f"BH clipped to Bahrain (+ causeway in buffer): {len(bh)} rows")
check(manifest["countries"]["BH"]["clipped"] and manifest["countries"]["BH"]["extract"] == "gcc-states", "BH manifest clip flags")
check("World Bank official boundary" in readme and "This CSV file holds all 1,235 road segments for Bahrain (BH)." in readme, "BH README")

names, frames, readme = read_zip(os.path.join(OUT, "vu_roads.zip"))
check(names == ["road_openstreetmap_vu_part00001.csv", "README.txt"] and len(frames[0]) == 2, "VU single part")

# ── second run: everything up to date ───────────────────────────────────────
before = {f: os.path.getmtime(os.path.join(OUT, f)) for f in os.listdir(OUT) if f.endswith(".zip")}
for cell in cells:
    if "Build the zips" in cell:
        run_cell(cell)
check([s[2] for s in g["summary"]] == ["skipped"] * 3, f"second run skips all: {g['summary']}")

# ── table changes -> only that country is rebuilt ───────────────────────────
save("osm_geofabrik_vu", [(3, "C", "track", wkt(168.5, -17.9), 2026)], append=True)
for cell in cells:
    if "Build the zips" in cell:
        run_cell(cell)
status = {s[0]: s[2] for s in g["summary"]}
check(status == {"BH": "skipped", "VN": "skipped", "VU": "success"}, f"only VU rebuilt: {status}")
check(json.load(open(os.path.join(OUT, "manifest.json")))["countries"]["VU"]["rows"] == 3, "VU manifest updated to 3 rows")

# ── missing boundary -> keep_unclipped ─────────────────────────────────────
save("osm_geofabrik_qa", [(77, "Doha road", "primary", wkt(51.5, 25.3), 2026)])
g["ONLY_ISO2"] = ["QA"]
for cell in cells:
    if "Build the zips" in cell:
        run_cell(cell)
qa = json.load(open(os.path.join(OUT, "manifest.json")))["countries"]["QA"]
check(qa["shared_extract"] and not qa["clipped"], "QA (no boundary) published unclipped and flagged shared")

print("\nALL CHECKS PASSED" if ok else "\nSOME CHECKS FAILED")
spark.stop()
shutil.rmtree(ROOT, ignore_errors=True)
sys.exit(0 if ok else 1)
