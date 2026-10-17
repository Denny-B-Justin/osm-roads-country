"""
roads_data.py
-------------
Where the downloads come from.

The Databricks notebook databricks/osm_roads_build_zips.py writes, into a Unity
Catalog Volume folder:

    <iso2>_roads.zip     one per country (CSV parts of at most 200,000 rows + README.txt)
    manifest.json        what is there: name, rows, parts, size, columns, dates

This module reads manifest.json (cached, refreshed every MANIFEST_TTL_SECONDS)
and streams a country's zip to the browser. Nothing is ever loaded into memory
in full and no SQL warehouse is involved: a download is a pass-through of the
file, 1 MiB at a time.

Two backends, picked from the environment at import time:

  DatabricksVolume   production. Databricks Files API, signed in with the same
                     service principal (OAuth client ID + secret) as the cbd app.
                     The principal needs USE CATALOG, USE SCHEMA and READ VOLUME.
  LocalFolder        development. A local folder with the same layout, set with
                     ROADS_LOCAL_DIR (see dev/make_mock_data.py).
"""

import json
import logging
import os
import re
import threading
import time
from dataclasses import dataclass
from typing import Dict, Iterator, Optional, Tuple
from urllib.parse import quote

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # python-dotenv is optional: env vars can come from the system
    pass

log = logging.getLogger(__name__)

DEFAULT_VOLUME_DIR = "/Volumes/prd_mega/sgpbpi163/vgpbpi163/OSM/osm_road_all_country"
MANIFEST_NAME = "manifest.json"
MANIFEST_TTL_SECONDS = int(os.getenv("MANIFEST_TTL_SECONDS", "600"))
MANIFEST_RETRY_SECONDS = 30          # after a failed read, wait this long before trying again
STREAM_CHUNK_BYTES = 1024 * 1024
CONNECT_TIMEOUT = 10                 # seconds to open the connection to Databricks
READ_TIMEOUT = 120                   # seconds without a byte before giving up

_ISO2 = re.compile(r"^[A-Z]{2}$")
_ZIP_NAME = re.compile(r"^[a-z]{2}_roads\.zip$")
_SINGLE_RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")


class VolumeError(RuntimeError):
    """The Volume could not serve a file. `status` is the HTTP status to report."""

    def __init__(self, message, status=502):
        super().__init__(message)
        self.status = status


# ══════════════════════════════════════════════════════════════════════════
# Manifest -> Catalog
# ══════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class CountryFile:
    iso2: str
    name: str
    file: str
    size_bytes: int
    rows: int
    parts: int
    columns: Tuple[str, ...]
    extracted_at: Optional[str]      # date the OSM extract was turned into a table (YYYY-MM-DD)
    built_at: Optional[str]          # when the zip was built (ISO timestamp)
    extract: Optional[str]           # Geofabrik extract it came from
    shared_extract: bool             # that extract also covers other countries
    clipped: bool                    # rows were kept only where roads touch the country boundary


@dataclass(frozen=True)
class Catalog:
    countries: Tuple[CountryFile, ...]   # sorted by name
    updated_at: Optional[str]
    rows_per_part: int
    loaded: bool                         # False when the manifest could not be read at all

    def get(self, iso2):
        for c in self.countries:
            if c.iso2 == iso2:
                return c
        return None

    @property
    def codes(self):
        return [c.iso2 for c in self.countries]

    @property
    def total_rows(self):
        return sum(c.rows for c in self.countries)

    @property
    def total_bytes(self):
        return sum(c.size_bytes for c in self.countries)

    @property
    def columns(self):
        """Every column that appears in any file, in first-seen order."""
        seen = []
        for c in self.countries:
            for col in c.columns:
                if col not in seen:
                    seen.append(col)
        return seen

    @staticmethod
    def unavailable():
        return Catalog(countries=(), updated_at=None, rows_per_part=200_000, loaded=False)


def _parse_entry(iso2, raw):
    """One manifest entry -> CountryFile, or None (with a warning) if it is not usable."""
    if not _ISO2.match(str(iso2)) or not isinstance(raw, dict):
        log.warning("Manifest: skipping malformed entry %r", iso2)
        return None
    file = raw.get("file")
    if not isinstance(file, str) or not _ZIP_NAME.match(file):
        log.warning("Manifest: skipping %s, unexpected file name %r", iso2, file)
        return None
    try:
        size, rows, parts = int(raw["size_bytes"]), int(raw["rows"]), int(raw["parts"])
    except (KeyError, TypeError, ValueError):
        log.warning("Manifest: skipping %s, size/rows/parts missing", iso2)
        return None
    if size <= 0 or rows <= 0 or parts <= 0:
        log.warning("Manifest: skipping %s, empty file", iso2)
        return None
    columns = raw.get("columns") or []
    return CountryFile(
        iso2=iso2,
        name=str(raw.get("name") or iso2),
        file=file,
        size_bytes=size,
        rows=rows,
        parts=parts,
        columns=tuple(str(c) for c in columns if isinstance(c, str)),
        extracted_at=raw.get("extracted_at"),
        built_at=raw.get("built_at"),
        extract=raw.get("extract"),
        shared_extract=bool(raw.get("shared_extract")),
        clipped=bool(raw.get("clipped")),
    )


def parse_manifest(data):
    """manifest.json (already decoded) -> Catalog. Unusable entries are skipped."""
    if not isinstance(data, dict) or not isinstance(data.get("countries"), dict):
        raise ValueError("manifest.json has no 'countries' object")
    entries = []
    for iso2, raw in data["countries"].items():
        entry = _parse_entry(iso2, raw)
        if entry is not None:
            entries.append(entry)
    entries.sort(key=lambda c: c.name)
    return Catalog(
        countries=tuple(entries),
        updated_at=data.get("updated_at"),
        rows_per_part=int(data.get("rows_per_part") or 200_000),
        loaded=True,
    )


# ══════════════════════════════════════════════════════════════════════════
# Backends
# ══════════════════════════════════════════════════════════════════════════

def _attachment_headers(file_name):
    return {
        "Content-Disposition": f'attachment; filename="{file_name}"',
        "Cache-Control": "private, no-cache, no-transform",
        "X-Content-Type-Options": "nosniff",
    }


class DatabricksVolume:
    """Files API access to the Volume (GET /api/2.0/fs/files/Volumes/...).

    Sign-in is Databricks OAuth machine-to-machine (M2M) for a service principal, done
    directly against the workspace token endpoint, as documented by Databricks:

        POST https://<workspace>/oidc/v1/token
             Basic auth <client id>:<client secret>
             grant_type=client_credentials&scope=all-apis

    This is the same endpoint the databricks-sdk ends up calling, without depending on
    how a given SDK version discovers it. The token (valid about an hour) is cached and
    renewed five minutes before it expires, or straight away after a 401.
    """

    TOKEN_MARGIN_SECONDS = 300

    def __init__(self, host, client_id, client_secret, volume_dir):
        host = host.strip().rstrip("/")
        if not host.startswith("https://"):
            host = "https://" + host.replace("http://", "")
        self.host = host
        self.volume_dir = volume_dir.rstrip("/")
        self._client_id = client_id
        self._client_secret = client_secret
        self._token = None
        self._token_expires = 0.0                # time.monotonic()
        self._token_lock = threading.Lock()
        self._session = None
        self._session_lock = threading.Lock()

    def describe(self):
        return f"Databricks Volume {self.volume_dir} on {self.host}"

    # -- plumbing ---------------------------------------------------------------

    def _http(self):
        with self._session_lock:
            if self._session is None:
                import requests
                from requests.adapters import HTTPAdapter
                session = requests.Session()
                adapter = HTTPAdapter(pool_connections=4, pool_maxsize=32)
                session.mount("https://", adapter)
                session.mount("http://", adapter)
                self._session = session
        return self._session

    def _auth_headers(self, renew=False) -> Dict[str, str]:
        with self._token_lock:
            if renew or self._token is None or time.monotonic() >= self._token_expires:
                try:
                    response = self._http().post(
                        f"{self.host}/oidc/v1/token",
                        auth=(self._client_id, self._client_secret),
                        data={"grant_type": "client_credentials", "scope": "all-apis"},
                        headers={"Accept": "application/json"},
                        timeout=(CONNECT_TIMEOUT, 30),
                    )
                except Exception as exc:
                    raise VolumeError(f"Could not reach the Databricks token endpoint: {exc}") from exc
                if response.status_code != 200:
                    raise VolumeError(f"Databricks sign-in failed (HTTP {response.status_code}): "
                                      f"{response.text[:300]}")
                data = response.json()
                lifetime = int(data.get("expires_in") or 3600)
                self._token = data["access_token"]
                self._token_expires = time.monotonic() + max(60, lifetime - self.TOKEN_MARGIN_SECONDS)
            return {"Authorization": f"Bearer {self._token}"}

    def _url(self, file_name):
        return f"{self.host}/api/2.0/fs/files{quote(self.volume_dir + '/' + file_name, safe='/')}"

    def _get(self, file_name, extra_headers=None, stream=False, renew_token=False):
        headers = dict(self._auth_headers(renew=renew_token))
        headers["Accept-Encoding"] = "identity"
        if extra_headers:
            headers.update(extra_headers)
        try:
            response = self._http().get(self._url(file_name), headers=headers, stream=stream,
                                        timeout=(CONNECT_TIMEOUT, READ_TIMEOUT))
        except Exception as exc:
            raise VolumeError(f"Could not reach Databricks: {exc}") from exc
        if response.status_code == 401 and not renew_token:
            # Token revoked or expired early: sign in again once.
            response.close()
            return self._get(file_name, extra_headers, stream, renew_token=True)
        return response

    @staticmethod
    def _fail(response, file_name):
        status = response.status_code
        detail = ""
        try:
            detail = response.text[:300]
        except Exception:
            pass
        response.close()
        if status == 404:
            raise VolumeError(f"{file_name} is not in the Volume", status=404)
        if status in (401, 403):
            raise VolumeError(f"No permission to read {file_name} (HTTP {status}). The service "
                              f"principal needs READ VOLUME on the Volume. {detail}")
        raise VolumeError(f"Files API returned HTTP {status} for {file_name}: {detail}")

    # -- public -----------------------------------------------------------------

    def read_manifest(self):
        response = self._get(MANIFEST_NAME)
        if response.status_code != 200:
            self._fail(response, MANIFEST_NAME)
        try:
            return json.loads(response.content.decode("utf-8-sig"))
        finally:
            response.close()

    def zip_response(self, entry, range_header=None, if_range=None):
        """Flask Response that streams entry.file from the Volume (supports single byte ranges)."""
        from flask import Response
        from werkzeug.http import http_date, parse_date

        extra = {}
        if range_header and _SINGLE_RANGE.match(range_header.strip()) and range_header.strip() != "bytes=-":
            if if_range is None:
                extra["Range"] = range_header.strip()
            else:
                # Resume only if the file has not changed since the browser got its first part.
                since = parse_date(if_range)
                if since is not None:
                    extra["Range"] = range_header.strip()
                    extra["If-Unmodified-Since"] = http_date(since)

        upstream = self._get(entry.file, extra, stream=True)
        if extra and upstream.status_code == 412:
            # The file was rebuilt in between: send the whole new file instead (RFC 9110 If-Range).
            upstream.close()
            upstream = self._get(entry.file, stream=True)
        if upstream.status_code == 416:
            headers = {"Content-Range": upstream.headers.get("Content-Range", f"bytes */{entry.size_bytes}")}
            upstream.close()
            return Response(status=416, headers=headers)
        if upstream.status_code not in (200, 206):
            self._fail(upstream, entry.file)

        headers = _attachment_headers(entry.file)
        headers["Accept-Ranges"] = "bytes"
        encoded = upstream.headers.get("Content-Encoding", "identity").lower() != "identity"
        if upstream.headers.get("Content-Length") and not encoded:
            headers["Content-Length"] = upstream.headers["Content-Length"]
        if upstream.status_code == 206 and upstream.headers.get("Content-Range"):
            headers["Content-Range"] = upstream.headers["Content-Range"]
        if upstream.headers.get("Last-Modified"):
            headers["Last-Modified"] = upstream.headers["Last-Modified"]

        def body() -> Iterator[bytes]:
            sent = 0
            try:
                for chunk in upstream.iter_content(chunk_size=STREAM_CHUNK_BYTES):
                    if chunk:
                        sent += len(chunk)
                        yield chunk
            except Exception:
                log.exception("Download of %s stopped after %d bytes", entry.file, sent)
                raise
            finally:
                upstream.close()

        response = Response(body(), status=upstream.status_code, headers=headers,
                            mimetype="application/zip", direct_passthrough=True)
        # Also release the connection when the body is never read (HEAD request, client gone early).
        response.call_on_close(upstream.close)
        return response


class LocalFolder:
    """Same layout as the Volume, on local disk. For development and tests."""

    def __init__(self, folder):
        self.folder = os.path.abspath(folder)

    def describe(self):
        return f"local folder {self.folder}"

    def read_manifest(self):
        path = os.path.join(self.folder, MANIFEST_NAME)
        try:
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
        except FileNotFoundError as exc:
            raise VolumeError(f"{path} does not exist", status=404) from exc

    def zip_response(self, entry, range_header=None, if_range=None):
        from flask import send_file
        path = os.path.join(self.folder, entry.file)
        if not os.path.isfile(path):
            raise VolumeError(f"{entry.file} is not in {self.folder}", status=404)
        response = send_file(path, mimetype="application/zip", as_attachment=True,
                             download_name=entry.file, conditional=True, max_age=0)
        for key, value in _attachment_headers(entry.file).items():
            if key != "Content-Disposition":
                response.headers[key] = value
        return response


def _make_backend():
    local_dir = os.getenv("ROADS_LOCAL_DIR")
    if local_dir:
        return LocalFolder(local_dir)

    required = {
        "DATABRICKS_SERVER_HOSTNAME": os.getenv("DATABRICKS_SERVER_HOSTNAME"),
        "DATABRICKS_CLIENT_ID": os.getenv("DATABRICKS_CLIENT_ID"),
        "DATABRICKS_CLIENT_SECRET": os.getenv("DATABRICKS_CLIENT_SECRET"),
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        raise EnvironmentError(
            "\n\nMissing required environment variables:\n"
            + "\n".join(f"  {k}" for k in missing)
            + "\n\nCreate a .env file in the project folder (see .env.example) with:\n"
            + "  DATABRICKS_SERVER_HOSTNAME=adb-xxxx.azuredatabricks.net\n"
            + "  DATABRICKS_CLIENT_ID=your-client-id\n"
            + "  DATABRICKS_CLIENT_SECRET=your-client-secret\n"
            + "or set ROADS_LOCAL_DIR to run on a local copy (python dev/make_mock_data.py).\n"
        )
    return DatabricksVolume(
        host=required["DATABRICKS_SERVER_HOSTNAME"],
        client_id=required["DATABRICKS_CLIENT_ID"],
        client_secret=required["DATABRICKS_CLIENT_SECRET"],
        volume_dir=os.getenv("ROADS_VOLUME_DIR", DEFAULT_VOLUME_DIR),
    )


BACKEND = _make_backend()
log.info("Road downloads served from %s", BACKEND.describe())


# ══════════════════════════════════════════════════════════════════════════
# Cached catalog
# ══════════════════════════════════════════════════════════════════════════

class _State:
    catalog: Optional[Catalog] = None
    fetched_at = 0.0          # time.monotonic() of the last good read
    failed_at = -1e9          # time.monotonic() of the last failed read


_state = _State()
_refresh_lock = threading.Lock()


def _fresh(now):
    return _state.catalog is not None and now - _state.fetched_at < MANIFEST_TTL_SECONDS


def get_catalog() -> Catalog:
    """The current catalog. Re-reads manifest.json at most every MANIFEST_TTL_SECONDS.

    While one request refreshes it, others keep using the previous copy. If a
    refresh fails, the previous copy is kept (and retried after
    MANIFEST_RETRY_SECONDS); with no copy at all, an empty, not-loaded catalog
    is returned so the page can say the list is unavailable.
    """
    now = time.monotonic()
    if _fresh(now):
        return _state.catalog

    have_copy = _state.catalog is not None
    if not _refresh_lock.acquire(blocking=not have_copy):
        return _state.catalog                       # another request is refreshing it
    try:
        now = time.monotonic()
        if _fresh(now):
            return _state.catalog
        if now - _state.failed_at < MANIFEST_RETRY_SECONDS:
            return _state.catalog or Catalog.unavailable()
        try:
            catalog = parse_manifest(BACKEND.read_manifest())
        except Exception as exc:
            log.error("Could not read %s from %s: %s", MANIFEST_NAME, BACKEND.describe(), exc)
            _state.failed_at = now
            return _state.catalog or Catalog.unavailable()
        _state.catalog, _state.fetched_at = catalog, now
        log.info("Loaded manifest: %d countries", len(catalog.countries))
        return catalog
    finally:
        _refresh_lock.release()


def zip_response(entry, range_header=None, if_range=None):
    return BACKEND.zip_response(entry, range_header=range_header, if_range=if_range)


def human_size(n_bytes):
    """1536 -> '2 KB', 503316480 -> '480 MB', 3.2e9 -> '3.0 GB' (base 1024, like file browsers)."""
    units = ["bytes", "KB", "MB", "GB", "TB"]
    size = float(n_bytes)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            if unit == "bytes":
                return f"{int(size)} bytes"
            return f"{size:,.1f} {unit}" if size < 10 and unit in ("GB", "TB") else f"{size:,.0f} {unit}"
        size /= 1024
    return f"{n_bytes} bytes"


def short_count(n):
    """2926219 -> '2.9 million', 140282 -> '140,282'."""
    if n >= 1_000_000_000:
        return f"{n / 1_000_000_000:,.1f} billion"
    if n >= 1_000_000:
        return f"{n / 1_000_000:,.1f} million"
    return f"{n:,}"


