# OpenStreetMap Roads by Country

A one-page Dash app where anyone can pick a country and download its complete OpenStreetMap road
network as CSV files in a zip, plus a documentation page. Python 3.9, deployed like the Country
Benchmarking Dashboard (cbd-dev): Posit Connect, same Databricks service principal, same fonts and
colours.

## Link: https://datanalytics.worldbank.org/openstreetmap-country-roads/  

| Page | URL |
|------|-----|
| Download page | `/` |
| Documentation (opens in a new tab) | `/?page=roads-data-documentation` |
| A country's zip (used by the Download button) | `/download/<ISO2>`, e.g. `/download/VN` |

## How it works

```
databricks/osm_geofabrik_roads.py     Geofabrik .osm.pbf  ->  prd_mega.sgpbpi163.osm_geofabrik_<iso2>   (one table per country)
databricks/osm_roads_build_zips.py    tables  ->  /Volumes/prd_mega/sgpbpi163/vgpbpi163/OSM/osm_road_all_country/
                                                    <iso2>_roads.zip   CSV parts of at most 200,000 rows + README.txt
                                                    manifest.json      what is available
this app                              manifest.json -> the country list; Download -> streams the zip from the Volume
```

The heavy work (reading millions of rows, writing CSV, zipping) happens once in Databricks, not on
every click. The app never queries a table and needs no SQL warehouse: it reads `manifest.json` and
passes a zip through to the browser 1 MiB at a time through the Databricks Files API. Memory stays
flat whatever the file size (a 600 MB file moved the app's memory by 8 MB in testing), the browser
shows its normal download progress, and interrupted downloads can resume (HTTP Range requests are
passed through).

The country list is whatever `manifest.json` lists, so it is always true: when a new country's zip
is built it appears in the app within `MANIFEST_TTL_SECONDS` (10 minutes by default). The
documentation's "not available yet" list is every code in `countries.py` that is not in the
manifest (obsolete codes AN and CS excluded).

## Project layout

```
app.py              Dash app: routing (?page=), the three small callbacks, the /download/<ISO2> route
pages.py            layouts and all page copy: download page, documentation, not-found page
roads_data.py       manifest.json (cached) and streaming zips from the Volume; local-folder mode for development
countries.py        every country code the pipeline covers, for the "not available yet" list
assets/
  style.css         all styles (Fira Sans and the cbd colour tokens)
  roads.js          Download button: starts the download, spinner until the file arrives, messages
  road_network.svg  background map (generated, see dev/make_road_network.py)
  fonts/            Fira Sans, self-hosted (SIL Open Font License)
databricks/
  osm_roads_build_zips.py   notebook: tables -> zips + manifest.json (run after every extraction)
  osm_geofabrik_roads.py    notebook: extraction, version 2 (adds surface, ref, oneway, bridge, tunnel)
dev/
  make_mock_data.py         builds dev/mock_volume (fake zips + manifest) to run the app without Databricks
  make_road_network.py      regenerates the background map and favicon
tests/                      see "Tests" below
```

## One-time setup in Databricks

1. **Give the app's service principal read access to the Volume** (run as an owner or with MANAGE):

   ```sql
   GRANT USE CATALOG ON CATALOG prd_mega TO `<service-principal-application-id>`;
   GRANT USE SCHEMA  ON SCHEMA  prd_mega.sgpbpi163 TO `<service-principal-application-id>`;
   GRANT READ VOLUME ON VOLUME  prd_mega.sgpbpi163.vgpbpi163 TO `<service-principal-application-id>`;
   ```

   Access to the cbd tables is not enough; READ VOLUME is what the Files API checks. It covers the
   whole volume (including the cached `.osm.pbf` files); if that is too wide, create a separate
   volume for the zips and point `OUT_DIR` (notebook) and `ROADS_VOLUME_DIR` (app) at it.

2. **Import the notebooks**: Workspace > Import > `databricks/osm_roads_build_zips.py` (and,
   optionally, `databricks/osm_geofabrik_roads.py`). They are Databricks source files and open as
   notebooks.

3. **Build the zips**: run `osm_roads_build_zips` on the same cluster type as the extraction. Try
   `ONLY_ISO2 = ["BT", "VN"]` first, then clear it. The first full run builds all 205 countries;
   later runs only rebuild a country when its table changed (or with `FORCE_REBUILD = True`).

4. **Keep it current** (optional): one Databricks job with two tasks, extraction then zips.

### What the zip notebook does that is easy to miss

- It ignores `osm_geofabrik_run_log` and any table whose suffix is not a two-letter code (such as the
  `__new` staging tables of the version-2 extraction).
- Countries that Geofabrik only publishes inside a shared extract (GCC states, Malaysia/Singapore/Brunei,
  Haiti/Dominican Republic, Israel/Palestine, Senegal/Gambia, American Samoa/Guam/Northern Marianas,
  Ireland + Northern Ireland, Indonesia + Timor-Leste) are cut back to their own boundary from
  `prd_mega.sgpbpi163.cbd_world_boundaries_dissolved` (`iso_a3`, `geometry_json`): a road is kept when it
  touches the boundary buffered by about 200 m. If a boundary is missing, the whole extract is published
  and the documentation page says so (`ON_MISSING_BOUNDARY = "fail"` skips the country instead).
- Every CSV part is row-counted while it is zipped; a country whose counts do not match the table is
  not published, and its previous zip stays live.
- Zips are built on local disk and copied to the Volume under a temporary name, then renamed, so the
  app never serves a half-written file. `manifest.json` is rewritten after each country.

### Version 2 of the extraction (optional)

`databricks/osm_geofabrik_roads.py` is your notebook with these changes:

- six more columns: `ref`, `surface`, `surface_class` (paved / unpaved, grouped as on the OSM wiki),
  `oneway`, `bridge`, `tunnel`;
- tables without these columns are rebuilt (`UPGRADE_EXISTING_TABLES = False` keeps them); cached
  `.osm.pbf` files are reused, so nothing is downloaded again unless `FORCE_DOWNLOAD = True`;
- each country is written to `osm_geofabrik_<iso2>__new` and swapped in with `CREATE OR REPLACE TABLE`
  only when complete, so a failure never leaves a country without a table;
- the local copy of each `.osm.pbf` is deleted after its country (the original kept every file on the
  driver's disk).

Rebuilding every country takes several hours (the largest extracts dominate). The app and the zip
notebook work with either version; the documentation page lists only the columns the files contain,
and the paved/unpaved section appears once `surface_class` exists.

## Run locally

```bash
pip install -r requirements.txt
```

Without Databricks, on generated data:

```bash
python dev/make_mock_data.py                      # writes dev/mock_volume
ROADS_LOCAL_DIR=dev/mock_volume python app.py     # Windows: set ROADS_LOCAL_DIR=dev\mock_volume
```

Against the real Volume: copy `.env.example` to `.env`, fill in the hostname, client ID and secret
(the same values as cbd), then `python app.py` and open http://127.0.0.1:8050.

## Deploy to Posit Connect

`manifest.json` is included (Python 3.9.13, entrypoint `app`). Regenerate it after changing files:

```bash
rsconnect write-manifest dash --overwrite --exclude "databricks/**" --exclude "dev/**" --exclude "tests/**" .
```

In the content's settings:

- **Vars**: `DATABRICKS_SERVER_HOSTNAME`, `DATABRICKS_CLIENT_ID`, `DATABRICKS_CLIENT_SECRET`
  (and `ROADS_VOLUME_DIR` if you moved the zips). Do not deploy a `.env` file.
- **Runtime**: a download keeps a connection open for as long as the file takes to arrive, minutes
  for the largest countries. Raise "Max connections per process" (for example to 50) so long downloads
  do not queue other visitors, and keep at least one process running.

## Tests

```bash
python tests/test_download_backend.py      # app + streaming against a fake Databricks workspace (needs only requirements.txt)
python tests/test_zip_notebook.py          # runs the zip notebook on a local Spark (pip install pyspark pandas pyarrow "shapely>=2,<3"; Java 17+)
python tests/test_extraction_handler.py    # runs the extraction parser on a small OSM file (pip install osmium pyspark requests)
```

What they cover: OAuth sign-in and token renewal, byte-for-byte streaming, Range/resume and the
"file changed in between" case, missing files and permission errors, the manifest cache; CSV quoting
of names with quotes, commas, line breaks and non-Latin scripts, 200,000-row parts, clipping to a
boundary, skipping unchanged tables; tag extraction and the paved/unpaved grouping.

## The zip a user gets

```
vn_roads.zip
  road_openstreetmap_vn_part00001.csv     at most 200,000 rows each, header row, UTF-8, RFC 4180 quoting
  road_openstreetmap_vn_part00002.csv
  ...
  README.txt                              what the parts are, that they must be appended, ODbL credit
```

Rows are spread evenly over the parts in no particular order. Columns: `osm_id, name, kind, geometry,
source_year` (version 1), plus `ref, surface, surface_class, oneway, bridge, tunnel` (version 2).
`geometry` is a WKT LINESTRING in EPSG:4326.

## Changing things

- Title, one-liner and documentation text: `pages.py`.
- Colours and layout: `assets/style.css` (tokens at the top).
- Background map: edit and run `dev/make_road_network.py`.
- Authors: `AUTHORS` in `pages.py`.

Road data © OpenStreetMap contributors, ODbL. Extracts from Geofabrik GmbH.
