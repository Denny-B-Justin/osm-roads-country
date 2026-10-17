"""
app.py
------
OpenStreetMap Roads by Country - Dash app.

Run with:  python app.py        then open  http://127.0.0.1:8050

  /                                   pick a country and download its zip
  /?page=roads-data-documentation     documentation (opens in a new tab)
  /download/<ISO2>                    the zip itself, streamed from the Volume

Files
  app.py          this file: Dash app, routing, the download route
  pages.py        layouts and all page copy
  roads_data.py   manifest.json + streaming zips from the Unity Catalog Volume
  countries.py    every country code the pipeline covers (for the "not yet available" list)
  assets/         style.css, roads.js (download button), fonts, logo, background map

How a download works
  The Download button (assets/roads.js) points a hidden iframe at
  /download/<ISO2>?t=<token>. The route streams the zip from the Volume 1 MiB at
  a time and sets a short-lived cookie "<token>-ok" on the response, which is
  how the page knows the file has started arriving and can stop the spinner.
  Errors set "<token>-missing" or "<token>-failed" instead.
"""

import logging
import re
from html import escape
from urllib.parse import parse_qs

from dash import ClientsideFunction, Dash, Input, Output, State, dcc, html
from flask import Response, request

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

import pages  # noqa: E402  (logging first, so roads_data's start-up message is shown)
import roads_data as rd  # noqa: E402

log = logging.getLogger("roads-app")

app = Dash(
    __name__,
    title=pages.APP_TITLE,
    update_title=None,
    suppress_callback_exceptions=True,
    meta_tags=[
        {"name": "viewport", "content": "width=device-width, initial-scale=1"},
        {"name": "description", "content": pages.META_DESCRIPTION},
    ],
)
server = app.server

LOGO_URL = app.get_asset_url("The-World-Bank-group-white.png")
PIM_PAM_LOGO_URL = app.get_asset_url("PIM-PAM-Logo.png")
FAVICON_ICO = app.get_asset_url("favicon.ico")
FAVICON_SVG = app.get_asset_url("favicon.svg")

# "/download/" locally, "/content/<guid>/download/" behind Posit Connect.
DOWNLOAD_BASE = app.get_relative_path("/download/")
DOWNLOAD_RULE = app.config.routes_pathname_prefix + "download/<code>"

DOWNLOAD_COOKIE = "osm_roads_dl"
_TOKEN = re.compile(r"^[A-Za-z0-9]{8,40}$")
_CODE = re.compile(r"^[A-Za-z]{2}$")

app.index_string = """<!DOCTYPE html>
<html lang="en">
    <head>
        {%metas%}
        <title>{%title%}</title>
        <link rel="icon" href=\"""" + FAVICON_ICO + """\" sizes="48x48">
        <link rel="icon" href=\"""" + FAVICON_SVG + """\" type="image/svg+xml">
        {%css%}
    </head>
    <body>
        {%app_entry%}
        <footer>
            {%config%}
            {%scripts%}
            {%renderer%}
        </footer>
    </body>
</html>
"""


# ══════════════════════════════════════════════════════════════════════════
# Routing: ?page=  (query-string based so it works behind Posit Connect)
# ══════════════════════════════════════════════════════════════════════════

app.layout = html.Div([
    dcc.Location(id="url", refresh=False),
    html.Div(id="page-content"),
    html.Div(id="title-sink", hidden=True),
])


def _page_key(search):
    if not search:
        return ""
    return parse_qs(search.lstrip("?")).get("page", [""])[0]


@app.callback(Output("page-content", "children"), Input("url", "search"))
def render_page(search):
    page = _page_key(search)
    catalog = rd.get_catalog()
    if page == "":
        return pages.home_layout(catalog, LOGO_URL, PIM_PAM_LOGO_URL, DOWNLOAD_BASE)
    if page == pages.DOCS_PAGE:
        return pages.docs_layout(catalog, LOGO_URL, PIM_PAM_LOGO_URL)
    return pages.not_found_layout(LOGO_URL, PIM_PAM_LOGO_URL)


app.clientside_callback(
    ClientsideFunction(namespace="roads", function_name="setTitle"),
    Output("title-sink", "children"),
    Input("url", "search"),
)

# Selecting a country enables the button and shows what the download contains.
app.clientside_callback(
    ClientsideFunction(namespace="roads", function_name="select"),
    Output("dl-btn", "disabled"),
    Output("dl-note", "children"),
    Output("dl-note", "className"),
    Input("country-dd", "value"),
    State("dl-meta", "data"),
    prevent_initial_call=True,     # keeps a "list could not be loaded" message on screen
)

# The click starts the download; roads.js updates the button and note as it goes.
app.clientside_callback(
    ClientsideFunction(namespace="roads", function_name="download"),
    Output("dl-run", "data"),
    Input("dl-btn", "n_clicks"),
    State("country-dd", "value"),
    State("dl-meta", "data"),
    State("dl-base", "data"),
    prevent_initial_call=True,
)


# ══════════════════════════════════════════════════════════════════════════
# The download itself
# ══════════════════════════════════════════════════════════════════════════

def _mark(response, token, state):
    """Tell the page how the request went (read by assets/roads.js)."""
    if token:
        response.set_cookie(DOWNLOAD_COOKIE, f"{token}-{state}", max_age=600, path="/",
                            samesite="Lax", secure=request.is_secure, httponly=False)
    return response


def _error_page(status, token, state, message):
    body = (
        "<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'>"
        f"<title>{escape(pages.APP_TITLE)}</title>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'></head>"
        "<body style=\"font-family:'Fira Sans','Segoe UI',Arial,sans-serif;max-width:40rem;margin:4rem auto;"
        "padding:0 1rem;color:#14243A\">"
        f"<h1 style='color:#0B2B4B;font-size:1.5rem'>The file could not be downloaded</h1>"
        f"<p>{escape(message)}</p>"
        f"<p><a href='{escape(app.get_relative_path('/'))}'>Back to the download page</a></p>"
        "</body></html>"
    )
    response = Response(body, status=status, mimetype="text/html")
    response.headers["Cache-Control"] = "no-store"
    return _mark(response, token, state)


@server.route(DOWNLOAD_RULE, methods=["GET"])
def download(code):
    token = request.args.get("t", "")
    token = token if _TOKEN.match(token) else ""

    entry = rd.get_catalog().get(code.upper()) if _CODE.match(code) else None
    if entry is None:
        return _error_page(404, token, "missing",
                           "There is no road file for this country. The list may have changed: "
                           "go back to the download page and pick the country again.")
    try:
        response = rd.zip_response(entry, range_header=request.headers.get("Range"),
                                   if_range=request.headers.get("If-Range"))
    except rd.VolumeError as exc:
        log.error("Download of %s failed: %s", entry.file, exc)
        if exc.status == 404:
            return _error_page(404, token, "missing",
                               f"The {entry.name} file is being rebuilt. Try again in a few minutes.")
        return _error_page(502, token, "failed",
                           "The file could not be fetched from the data store. Try again in a few minutes.")

    log.info("Download %s (%s): HTTP %s, range=%s", entry.file, rd.human_size(entry.size_bytes),
             response.status_code, request.headers.get("Range") or "-")
    return _mark(response, token, "ok")


if __name__ == "__main__":
    app.run(debug=False, host="127.0.0.1", port=8050)
