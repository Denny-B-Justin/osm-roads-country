"""
tests/test_download_backend.py

Run:  python tests/test_download_backend.py      (needs only requirements.txt)

Exercises roads_data.DatabricksVolume + the /download route against a fake Databricks workspace:
  /oidc/v1/token                                  OAuth M2M client-credentials token endpoint
  /api/2.0/fs/files/Volumes/...                   Files API: Range, If-Unmodified-Since (412), 404, auth
"""
import base64
import email.utils
import hashlib
import os
import re
import sys
import threading
import time

from flask import Flask, Response, request
from werkzeug.serving import make_server

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_DIR = ROOT_DIR
MOCK = os.path.join(APP_DIR, "dev", "mock_volume")
if not os.path.isfile(os.path.join(MOCK, "manifest.json")):
    import subprocess
    subprocess.run([sys.executable, os.path.join(APP_DIR, "dev", "make_mock_data.py")], check=True)
VOLUME = "/Volumes/prd_mega/sgpbpi163/vgpbpi163/OSM/osm_road_all_country"
PORT = 8061
CLIENT_ID, CLIENT_SECRET = "sp-client-id", "sp-secret"
calls = {"token": 0, "files": [], "auth_fail": 0}

fake = Flask("fake-databricks")


@fake.post("/oidc/v1/token")
def token():
    auth = request.headers.get("Authorization", "")
    expected = "Basic " + base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
    if auth != expected or request.form.get("grant_type") != "client_credentials" or request.form.get("scope") != "all-apis":
        return {"error": "invalid_client"}, 401
    calls["token"] += 1
    return {"access_token": "tok-123", "token_type": "Bearer", "expires_in": 3600}


@fake.get("/api/2.0/fs/files/<path:p>")
def files(p):
    calls["files"].append((p, dict(request.headers)))
    if calls.pop("reject_next", False):
        return {"error_code": "UNAUTHENTICATED"}, 401
    if request.headers.get("Authorization") != "Bearer tok-123":
        calls["auth_fail"] += 1
        return {"error_code": "PERMISSION_DENIED", "message": "no"}, 403
    prefix = VOLUME.lstrip("/") + "/"
    if not p.startswith(prefix):
        return {"error_code": "NOT_FOUND"}, 404
    local = os.path.join(MOCK, p[len(prefix):])
    if not os.path.isfile(local):
        return {"error_code": "NOT_FOUND", "message": "missing"}, 404
    data = open(local, "rb").read()
    mtime = int(os.path.getmtime(local))
    headers = {"Last-Modified": email.utils.formatdate(mtime, usegmt=True), "Content-Type": "application/octet-stream"}
    ius = request.headers.get("If-Unmodified-Since")
    if ius and mtime > email.utils.parsedate_to_datetime(ius).timestamp():
        return Response(status=412)
    rng = request.headers.get("Range")
    if rng:
        m = re.match(r"bytes=(\d*)-(\d*)$", rng)
        a, b = m.group(1), m.group(2)
        n = len(data)
        if a == "":
            start, end = n - int(b), n - 1
        else:
            start, end = int(a), (int(b) if b else n - 1)
        if start >= n:
            return Response(status=416, headers={"Content-Range": f"bytes */{n}"})
        end = min(end, n - 1)
        headers["Content-Range"] = f"bytes {start}-{end}/{n}"
        return Response(data[start:end + 1], status=206, headers=headers)
    return Response(data, status=200, headers=headers)


server = make_server("127.0.0.1", PORT, fake, threaded=True)
threading.Thread(target=server.serve_forever, daemon=True).start()

# ── import the app in Databricks mode ──────────────────────────────────────
os.environ.pop("ROADS_LOCAL_DIR", None)
os.environ.update(DATABRICKS_SERVER_HOSTNAME=f"127.0.0.1:{PORT}", DATABRICKS_CLIENT_ID=CLIENT_ID,
                  DATABRICKS_CLIENT_SECRET=CLIENT_SECRET, NO_PROXY="127.0.0.1,localhost", no_proxy="127.0.0.1,localhost")
for k in ("DATABRICKS_TOKEN", "DATABRICKS_CONFIG_PROFILE"):
    os.environ.pop(k, None)
os.chdir(APP_DIR)
sys.path.insert(0, APP_DIR)
import roads_data as rd  # noqa: E402

check_ok = True


def check(cond, msg):
    global check_ok
    print(("PASS " if cond else "FAIL ") + msg)
    check_ok &= bool(cond)


check(isinstance(rd.BACKEND, rd.DatabricksVolume), "Databricks backend selected from env")
check(rd.BACKEND.host == f"https://127.0.0.1:{PORT}", f"host normalised to https ({rd.BACKEND.host})")
rd.BACKEND.host = f"http://127.0.0.1:{PORT}"     # the fake workspace speaks plain http

import app as webapp  # noqa: E402

client = webapp.server.test_client()

catalog = rd.get_catalog()
check(catalog.loaded and len(catalog.countries) == 205, f"manifest via Files API: {len(catalog.countries)} countries")
check(calls["token"] == 1, f"one OAuth token request so far ({calls['token']})")

vn = open(os.path.join(MOCK, "vn_roads.zip"), "rb").read()
r = client.get("/download/VN?t=abc12345xyz")
body = r.get_data()
check(r.status_code == 200 and body == vn, f"full download streamed byte-for-byte ({len(body):,} bytes)")
check(r.headers["Content-Length"] == str(len(vn)), "Content-Length passed through")
check(r.headers["Content-Disposition"] == 'attachment; filename="vn_roads.zip"', "attachment filename")
check(r.headers.get("Accept-Ranges") == "bytes" and r.headers.get("Last-Modified"), "Accept-Ranges and Last-Modified")
check("osm_roads_dl=abc12345xyz-ok" in r.headers.get("Set-Cookie", ""), "ok cookie set")
sent = calls["files"][-1][1]
check(sent.get("Accept-Encoding") == "identity", "asks Databricks for an unencoded body")
check(calls["token"] == 1, "token reused, not fetched per request")

lm = r.headers["Last-Modified"]
r = client.get("/download/vn", headers={"Range": "bytes=1000-", "If-Range": lm})
check(r.status_code == 206 and r.get_data() == vn[1000:] and r.headers["Content-Range"] == f"bytes 1000-{len(vn) - 1}/{len(vn)}",
      "resume with Range + If-Range -> 206 with the rest of the file")
check("If-Unmodified-Since" in calls["files"][-1][1], "If-Range forwarded as If-Unmodified-Since")

old = email.utils.formatdate(time.time() - 10 * 24 * 3600, usegmt=True)
r = client.get("/download/VN", headers={"Range": "bytes=1000-", "If-Range": old})
check(r.status_code == 200 and r.get_data() == vn, "file changed since first part (412 upstream) -> whole file, 200")

r = client.get("/download/VN", headers={"Range": "bytes=0-99,200-299"})
check(r.status_code == 200 and r.get_data() == vn, "multi-range ignored -> whole file")

r = client.get("/download/VN", headers={"Range": f"bytes={len(vn) + 5}-"})
check(r.status_code == 416, "range past the end -> 416")

r = client.get("/download/ZZ?t=abc12345xyz")
check(r.status_code == 404 and "abc12345xyz-missing" in r.headers.get("Set-Cookie", ""), "unknown country -> 404 + missing cookie")
for u in ("/download/..%2Fmanifest", "/download/../manifest.json", "/download/VN/../../manifest.json"):
    r = client.get(u)
    check(r.mimetype == "text/html" and b"countries" not in r.get_data(), f"{u} serves no file")

os.rename(os.path.join(MOCK, "vu_roads.zip"), os.path.join(MOCK, "vu_roads.zip.bak"))
try:
    r = client.get("/download/VU?t=tok99999")
    check(r.status_code == 404 and "tok99999-missing" in r.headers.get("Set-Cookie", ""), "zip missing in Volume -> 404 page + missing cookie")
finally:
    os.rename(os.path.join(MOCK, "vu_roads.zip.bak"), os.path.join(MOCK, "vu_roads.zip"))

real_auth = rd.BACKEND._auth_headers
rd.BACKEND._auth_headers = lambda renew=False: {"Authorization": "Bearer wrong"}
r = client.get("/download/VN?t=tok77777")
check(r.status_code == 502 and "tok77777-failed" in r.headers.get("Set-Cookie", ""), "permission denied -> 502 + failed cookie")
rd.BACKEND._auth_headers = real_auth

r = client.get("/download/VN?t=bad token!")
check(r.status_code == 200 and "osm_roads_dl" not in r.headers.get("Set-Cookie", ""), "invalid token -> no cookie, download still works")
r.close()

tokens_before = calls["token"]
calls["reject_next"] = True
r = client.get("/download/VN?t=tok55555")
check(r.status_code == 200 and r.get_data() == vn and calls["token"] == tokens_before + 1,
      "401 from Files API -> signs in again once and the download succeeds")

# Manifest unreadable: keep the last good copy.
rd._state.fetched_at -= 10_000
os.rename(os.path.join(MOCK, "manifest.json"), os.path.join(MOCK, "manifest.json.bak"))
try:
    cat = rd.get_catalog()
    check(cat.loaded and len(cat.countries) == 205, "manifest read fails -> previous catalog kept")
finally:
    os.rename(os.path.join(MOCK, "manifest.json.bak"), os.path.join(MOCK, "manifest.json"))

# Pages render in Databricks mode.
page = webapp.render_page("")
docs = webapp.render_page("?page=roads-data-documentation")
check(page is not None and docs is not None, "home and docs layouts build")

server.shutdown()
print("\nALL CHECKS PASSED" if check_ok else "\nSOME CHECKS FAILED")
sys.exit(0 if check_ok else 1)
