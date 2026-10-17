"""
tests/test_extraction_handler.py

Run:  pip install osmium pyspark requests, then  python tests/test_extraction_handler.py

Runs the extraction notebook's parser cells on a small OSM XML file (Spark itself is not started).
"""
import os
import sys
import tempfile

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NB = os.path.join(ROOT_DIR, "databricks", "osm_geofabrik_roads.py")
OSM = """<?xml version='1.0' encoding='UTF-8'?>
<osm version="0.6" generator="test">
  <node id="1" lat="21.0000000" lon="105.0000000" version="1"/>
  <node id="2" lat="21.0010000" lon="105.0010000" version="1"/>
  <node id="3" lat="21.0020000" lon="105.0015000" version="1"><tag k="highway" v="traffic_signals"/></node>
  <node id="4" lat="21.0030000" lon="105.0020000" version="1"/>
  <way id="100" version="1"><nd ref="1"/><nd ref="2"/><nd ref="3"/>
    <tag k="highway" v="primary"/><tag k="name" v="Đường Lê Lợi"/><tag k="ref" v="QL1A"/>
    <tag k="surface" v="Asphalt;gravel"/><tag k="oneway" v="yes"/><tag k="bridge" v="viaduct"/></way>
  <way id="101" version="1"><nd ref="3"/><nd ref="4"/>
    <tag k="highway" v="track"/><tag k="surface" v="dirt"/><tag k="tunnel" v="culvert"/></way>
  <way id="102" version="1"><nd ref="1"/><nd ref="4"/>
    <tag k="highway" v="residential"/><tag k="surface" v="something_odd"/></way>
  <way id="103" version="1"><nd ref="1"/><nd ref="2"/><tag k="highway" v="footway"/></way>
  <way id="104" version="1"><nd ref="2"/><nd ref="999"/><tag k="highway" v="service"/></way>
  <way id="105" version="1"><nd ref="1"/><nd ref="2"/><tag k="waterway" v="river"/></way>
</osm>
"""


class StubSpark:
    def __init__(self):
        self.written = []

    def createDataFrame(self, rows, schema=None):
        spark = self

        class _DF:
            def coalesce(self, n):
                return self

            @property
            def write(self):
                class _W:
                    def mode(self, m):
                        return self

                    def saveAsTable(self, t):
                        spark.written.extend(rows)
                return _W()
        return _DF()


source = open(NB, encoding="utf-8").read()
cells = [c.strip() for c in source.split("# COMMAND ----------")]
g = {"spark": StubSpark(), "__name__": "__notebook__"}
for cell in cells:
    if "import osmium" in cell or "Settings" in cell or "Road writer" in cell:
        exec(compile(cell, NB, "exec"), g)

tmp = tempfile.mkdtemp()
path = os.path.join(tmp, "test.osm")
open(path, "w", encoding="utf-8").write(OSM)
g["LOCAL_DIR"] = tmp
writer = g["RoadWriter"]("test_table")
g["extract_roads"](path, writer)
rows = {r[0]: r for r in g["spark"].written}
cols = g["ROAD_SCHEMA"].fieldNames()
for r in g["spark"].written:
    print(dict(zip(cols, r)))

ok = True


def check(cond, msg):
    global ok
    print(("PASS " if cond else "FAIL ") + msg)
    ok &= bool(cond)


check(sorted(rows) == [100, 101, 102], f"kept ways {sorted(rows)} (footway, way with missing node, river dropped)")
r = dict(zip(cols, rows[100]))
check(r["name"] == "Đường Lê Lợi" and r["ref"] == "QL1A" and r["oneway"] == "yes" and r["bridge"] == "viaduct", "tags copied")
check(r["surface"] == "Asphalt;gravel" and r["surface_class"] == "paved", "first surface value, case-insensitive -> paved")
check(r["geometry"] == "LINESTRING (105.0000000 21.0000000, 105.0010000 21.0010000, 105.0015000 21.0020000)",
      "untagged nodes have locations (KeyFilter does not drop them)")
check(dict(zip(cols, rows[101]))["surface_class"] == "unpaved" and dict(zip(cols, rows[101]))["tunnel"] == "culvert", "track: unpaved, tunnel")
check(dict(zip(cols, rows[102]))["surface_class"] is None, "unknown surface -> empty surface_class")
check(len(cols) == 11 and len(rows[100]) == 11, "row width matches ROAD_SCHEMA")
print("\nALL CHECKS PASSED" if ok else "\nSOME CHECKS FAILED")
sys.exit(0 if ok else 1)
