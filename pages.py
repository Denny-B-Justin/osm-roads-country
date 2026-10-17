"""
pages.py
--------
Layouts for the three pages. They only describe structure; behaviour lives in
app.py (routing, download route) and assets/roads.js (download button).

  home_layout()    "/"                                    pick a country, download its zip
  docs_layout()    "/?page=roads-data-documentation"      what the data is and how to use it
  not_found_layout()
"""

from datetime import datetime

from dash import dcc, html

import countries as cc
import roads_data as rd

APP_TITLE = "OpenStreetMap Roads by Country"
SHORT_NAME = "OSM Roads by Country"
DOCS_PAGE = "roads-data-documentation"
HOME_HREF = "?"                                  # relative on purpose: works under any URL prefix
DOCS_HREF = f"?page={DOCS_PAGE}"
PIM_PAM_URL = "https://datanalytics.worldbank.org/wkpgf-pimpam-digital-tools/"
META_DESCRIPTION = ("Download the OpenStreetMap road network of a country as CSV files, "
                    "split into parts of up to 200,000 rows.")
AUTHORS = ["Denny B. Justin", "Kaushiki Singh", "Kai-Alexander Kaiser"]

OSM_COPYRIGHT_URL = "https://www.openstreetmap.org/copyright"
OSM_URL = "https://www.openstreetmap.org"
ODBL_URL = "https://opendatacommons.org/licenses/odbl/1-0/"
GEOFABRIK_URL = "https://download.geofabrik.de"
OSM_WIKI_HIGHWAY_URL = "https://wiki.openstreetmap.org/wiki/Key:highway"
OSM_WIKI_SURFACE_URL = "https://wiki.openstreetmap.org/wiki/Key:surface"

# The road classes the extraction keeps (OSM_ROAD_HIGHWAY_VALUES in the notebook), grouped.
ROAD_CLASSES = [
    ("Main roads", [
        ("motorway", "Highest-class roads: controlled-access, divided highways such as freeways and "
                     "expressways."),
        ("trunk", "The most important roads that are not motorways, often the main routes between cities."),
        ("primary", "Major roads linking large towns; in many countries the national road network."),
        ("secondary", "Roads linking towns, often regional or provincial roads."),
        ("tertiary", "Roads linking smaller towns and villages, and the main streets inside towns."),
    ]),
    ("Link roads", [
        ("motorway_link, trunk_link, primary_link, secondary_link, tertiary_link",
         "Slip roads and ramps that join or leave a road of that class, for example motorway exits."),
    ]),
    ("Local roads", [
        ("unclassified", "Minor public roads below tertiary, typically joining villages and hamlets. "
                         "The name is OSM convention: these are known minor roads, not roads of unknown type."),
        ("residential", "Streets that give access to housing."),
        ("living_street", "Residential streets where pedestrians have priority and speeds are very low."),
        ("service", "Access roads: driveways, parking aisles, alleys, and roads inside industrial or "
                    "business sites."),
    ]),
    ("Other roads", [
        ("track", "Agricultural and forestry roads, usually unpaved."),
        ("road", "Roads whose class has not been decided yet by mappers."),
    ]),
]

# Column descriptions. Only the columns that exist in the published files are shown.
COLUMN_DOCS = {
    "osm_id": "OpenStreetMap way ID. Look a road up at openstreetmap.org/way/<osm_id>.",
    "name": "Road name, from the OSM name tag. Empty when the road has no name.",
    "kind": "Road class: the OSM highway tag, one of the values in the table above.",
    "ref": "Road number, such as A1 or NH 44 (OSM ref tag). Empty when there is none.",
    "surface": "Surface as mapped (OSM surface tag), for example asphalt, gravel or dirt.",
    "surface_class": "paved or unpaved, worked out from surface. Empty when the surface is not mapped "
                     "or not a recognised value.",
    "oneway": "OSM oneway tag: yes, no, or -1 (one-way against the direction the line is drawn). "
              "Empty when not mapped.",
    "bridge": "OSM bridge tag, for example yes or viaduct, when the segment is a bridge.",
    "tunnel": "OSM tunnel tag, for example yes or culvert, when the segment runs through a tunnel.",
    "geometry": "Shape of the road as WKT LINESTRING in longitude/latitude (WGS 84, EPSG:4326), "
                "7 decimal places (about 1 cm).",
    "source_year": "Year the data were extracted from OpenStreetMap.",
}
BASE_COLUMNS = ["osm_id", "name", "kind", "geometry", "source_year"]

PAVED_VALUES = ("paved, asphalt, chipseal, concrete (and its :lanes / :plates variants), paving_stones, "
                "sett, cobblestone, unhewn_cobblestone, bricks, grass_paver, metal, metal_grid, wood, "
                "stepping_stones, rubber, tiles")
UNPAVED_VALUES = ("unpaved, compacted, fine_gravel, gravel, shells, rock, pebblestone, ground, dirt, earth, "
                  "grass, mud, sand, woodchips, snow, ice, salt")

SECTIONS = [
    ("introduction", "Introduction"),
    ("data-source", "Data source"),
    ("roads", "Roads"),
    ("usage", "Usage"),
    ("achievements", "Achievements"),
    ("summary", "Summary"),
]


# ══════════════════════════════════════════════════════════════════════════
# Shared pieces
# ══════════════════════════════════════════════════════════════════════════

def icon(name):
    return html.Span(className=f"ico ico-{name}", **{"aria-hidden": "true"})


def ext_link(label, href, cls=None):
    return html.A(label, href=href, target="_blank", rel="noopener noreferrer", className=cls)


def build_header(current, logo_src, pim_pam_logo_src):
    """current: 'home' or 'docs'."""
    pim_pam_nav_link = html.A(["PIM-PAM", icon("external")], href=PIM_PAM_URL, target="_blank",
                              rel="noopener noreferrer", className="nav-link",
                              title="Opens PIM-PAM in a new tab")
    if current == "docs":
        nav = [
            dcc.Link("Download data", href=HOME_HREF, className="nav-link"),
            html.Span("Documentation", className="nav-link is-current", **{"aria-current": "page"}),
            pim_pam_nav_link,
        ]
    else:
        nav = [
            html.A(["Documentation", icon("external")], href=DOCS_HREF, target="_blank",
                  rel="noopener", className="nav-link",
                  title="Opens the documentation in a new tab"),
            pim_pam_nav_link,
        ]
    return html.Header(className="app-header", children=html.Div(className="app-header-inner", children=[
        html.Div(className="header-brand", children=[
            dcc.Link(html.Img(src=logo_src, className="header-logo", alt="World Bank Group"),
                     href=HOME_HREF, className="header-brand-link"),
            html.Span(className="header-divider", **{"aria-hidden": "true"}),
            html.A(html.Img(src=pim_pam_logo_src, className="header-logo", alt="PIM-PAM"),
                   href=PIM_PAM_URL, target="_blank", rel="noopener noreferrer",
                   className="header-brand-link", title="Opens PIM-PAM in a new tab"),
        ]),
        html.Nav(nav, className="header-nav", **{"aria-label": "Main"}),
    ]))


def credit_line(cls):
    return html.P(className=cls, children=[
        "Road data © ", ext_link("OpenStreetMap contributors", OSM_COPYRIGHT_URL),
        ", available under the Open Database License. Country extracts from ",
        ext_link("Geofabrik", GEOFABRIK_URL), ".",
    ])


def format_date(value):
    """'2026-10-17T03:28:00Z' or '2026-10-17' -> '17 October 2026' (None if unparseable)."""
    if not value:
        return None
    try:
        text = str(value).strip().replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text) if "T" in text else datetime.strptime(text[:10], "%Y-%m-%d")
    except ValueError:
        return None
    return f"{parsed.day} {parsed.strftime('%B %Y')}"


# ══════════════════════════════════════════════════════════════════════════
# Home
# ══════════════════════════════════════════════════════════════════════════

def _download_meta(catalog):
    """What assets/roads.js needs to describe and download each country."""
    return {
        c.iso2: {
            "name": c.name,
            "rows": c.rows,
            "parts": c.parts,
            "size": rd.human_size(c.size_bytes),
        }
        for c in catalog.countries
    }


def home_layout(catalog, logo_src, pim_pam_logo_src, download_base):
    available = len(catalog.countries)
    options = [{"label": c.name, "value": c.iso2, "search": f"{c.name} {c.iso2}"}
               for c in catalog.countries]

    if available:
        lede = (f"Download the complete road network of any of {available:,} countries and territories "
                f"as ready-to-use CSV files.")
    else:
        lede = "Download the complete road network of a country as ready-to-use CSV files."

    if not catalog.loaded:
        note = html.P("The list of countries could not be loaded. Refresh the page in a minute.",
                      id="dl-note", className="dl-note is-error", role="status")
    elif not options:
        note = html.P("No country files have been published yet. Check back soon.",
                      id="dl-note", className="dl-note", role="status")
    else:
        note = html.P(id="dl-note", className="dl-note", role="status", **{"aria-live": "polite"})

    updated = format_date(catalog.updated_at)
    facts = ("Each download is one zip file: the roads split into CSV files of up to "
             f"{catalog.rows_per_part:,} rows, and a short README.")
    if updated:
        facts += f" Data last updated {updated}."

    return html.Div(className="page page-home", children=[
        build_header("home", logo_src, pim_pam_logo_src),
        html.Main(className="hero", children=[
            html.Div(className="hero-roads", **{"aria-hidden": "true"}),
            html.Div(className="hero-inner", children=[
                html.H1(APP_TITLE, className="hero-title"),
                html.P(lede, className="hero-lede"),
                html.Div(className="picker", children=[
                    html.Div(className="picker-field", children=[
                        html.Label("Country", htmlFor="country-dd", className="visually-hidden"),
                        icon("globe"),
                        dcc.Dropdown(
                            id="country-dd",
                            options=options,
                            value=None,
                            multi=False,
                            clearable=True,
                            searchable=True,
                            placeholder="Select country" if catalog.loaded else "Country list unavailable",
                            disabled=not options,
                            maxHeight=320,
                            className="picker-dd",
                            labels={"search": "Type a country name",
                                    "no_options_found": "No country with that name"},
                        ),
                    ]),
                    html.Button(
                        [icon("download"), html.Span("Download", id="dl-btn-label")],
                        id="dl-btn", type="button", n_clicks=0, disabled=True,
                        className="btn btn-primary dl-btn",
                    ),
                ]),
                note,
                html.P(facts, className="hero-facts"),
            ]),
            credit_line("hero-credit"),
        ]),
        dcc.Store(id="dl-meta", data=_download_meta(catalog)),
        dcc.Store(id="dl-base", data=download_base),
        dcc.Store(id="dl-run"),
    ])


# ══════════════════════════════════════════════════════════════════════════
# Documentation
# ══════════════════════════════════════════════════════════════════════════

def _section(sid, title, children):
    return html.Section(id=sid, className="doc-section", children=[html.H2(title)] + children)


def _code(text):
    return html.Pre(html.Code(text), className="doc-code")


def _road_class_table():
    rows = []
    for group, items in ROAD_CLASSES:
        rows.append(html.Tr(html.Th(group, colSpan=2, scope="colgroup", className="group-row")))
        for value, text in items:
            codes = []
            for k, v in enumerate(value.split(", ")):
                codes += ([" "] if k else []) + [html.Code(v)]
            rows.append(html.Tr([html.Td(codes, className="codes"), html.Td(text)]))
    return html.Div(className="table-wrap", children=html.Table(className="doc-table", children=[
        html.Thead(html.Tr([html.Th("kind (OSM highway value)", scope="col"), html.Th("What it is", scope="col")])),
        html.Tbody(rows),
    ]))


def _columns_table(columns):
    rows = [html.Tr([html.Td(html.Code(col)), html.Td(COLUMN_DOCS.get(col, "OpenStreetMap tag of the same name."))])
            for col in columns]
    return html.Div(className="table-wrap", children=html.Table(className="doc-table", children=[
        html.Thead(html.Tr([html.Th("Column", scope="col"), html.Th("Contents", scope="col")])),
        html.Tbody(rows),
    ]))


def _name_list(names):
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + " and " + names[-1]


def _intro(catalog):
    n = len(catalog.countries)
    scope = f"{n:,} countries and territories" if n else "countries around the world"
    return _section("introduction", "Introduction", [
        html.P("A road network dataset records where roads are, how they connect and what kind of road "
               "each one is. It is one of the most used datasets in development work: it shows how people "
               "reach markets, schools and health care, where transport investment is needed, how far "
               "a community is from the nearest main road, and which places are cut off when a road "
               "floods or a bridge fails."),
        html.P(f"This site provides the road network of {scope}, taken from OpenStreetMap and packaged "
               "one country at a time as plain CSV files. Each road keeps its OpenStreetMap ID, name, class "
               "and full line shape, so the files can be used directly in Python, R or QGIS, or loaded "
               "into a database, without any OpenStreetMap-specific tools."),
    ])


def _data_source(catalog):
    clipped = sorted((c for c in catalog.countries if c.clipped), key=lambda c: c.name)
    shared = sorted((c for c in catalog.countries if c.shared_extract and not c.clipped), key=lambda c: c.name)

    children = [
        html.H3("OpenStreetMap"),
        html.P(["OpenStreetMap (", ext_link("OSM", OSM_URL), ") is a free, editable map of the world built "
                "by a global community of volunteers, humanitarian mapping teams, governments and companies. "
                "Contributors trace roads from aerial and satellite imagery, record GPS tracks and add local "
                "knowledge such as street names, road numbers and surfaces. The map changes every minute as "
                "people add and correct features."]),
        html.P("Because it is built by mappers rather than a single agency, coverage varies. Main roads are "
               "mapped almost everywhere; minor roads, tracks and attributes such as surface are more "
               "complete in some countries and in cities than in rural areas. OSM is often the most complete "
               "open road dataset available, but it is worth checking against local sources for "
               "decisions that depend on a specific area."),
        html.H3("Geofabrik"),
        html.P(["Geofabrik is a German company that specialises in OpenStreetMap services. Its free ",
                ext_link("download server", GEOFABRIK_URL), " publishes OSM data cut into continents, "
                "countries and regions, rebuilt every day from the main OpenStreetMap database, in the "
                "compact .osm.pbf format. Each file on this site was made from the Geofabrik extract of "
                "that country."]),
    ]
    if clipped:
        children.append(html.P(
            "For some countries Geofabrik publishes one extract that covers several neighbours, for example "
            "the Gulf states together. For these, the roads were cut back to the country: a road is kept "
            "when it touches the country's World Bank official boundary, so roads that cross a border "
            f"appear in both countries' files. This applies to {_name_list([c.name for c in clipped])}."))
    if shared:
        children.append(html.P(
            "The files for " + _name_list([c.name for c in shared]) + " come from a Geofabrik extract that "
            "also covers neighbouring countries or territories, so they include those roads as well.",
            className="doc-callout"))
    children += [
        html.H3("Licence and attribution"),
        html.P(["OpenStreetMap data are © OpenStreetMap contributors and available under the ",
                ext_link("Open Database License (ODbL) 1.0", ODBL_URL), ". You can use, share and adapt "
                "them for any purpose, including commercial use, as long as you credit OpenStreetMap "
                "contributors, and share any database you publish that is derived from them under the same "
                "licence. Maps and reports made from the data only need the credit. See ",
                ext_link("openstreetmap.org/copyright", OSM_COPYRIGHT_URL), " for details."]),
    ]
    return _section("data-source", "Data source", children)


def _roads(catalog):
    columns = catalog.columns or BASE_COLUMNS
    children = [
        html.P(["In OpenStreetMap a road is a way (a line made of points) tagged with ",
                html.Code("highway"), ". The files keep the classes below, which together make up the "
                "network that vehicles can use. Footways, paths, cycleways, steps, pedestrian streets, "
                "bridleways and roads that are proposed or under construction are left out. The ",
                ext_link("OSM wiki", OSM_WIKI_HIGHWAY_URL), " describes each class in detail."]),
        _road_class_table(),
        html.H3("Columns"),
        html.P("Every CSV file has a header row and the same columns, whatever the country:"),
        _columns_table(columns),
        html.H3("One row, one road segment"),
        html.P("Each row is one OSM way. A long road is usually split into several ways wherever something "
               "about it changes, such as its name, number of lanes, a bridge or a speed limit, so one road "
               "often spans many rows. Combine rows with the same name or ref if you need whole roads. "
               "Lines are stored exactly as mapped; no simplification is applied."),
    ]
    if "surface_class" in columns:
        children += [
            html.H3("Paved and unpaved roads"),
            html.P(["The surface column is copied from the OSM ",
                    ext_link("surface", OSM_WIKI_SURFACE_URL), " tag. surface_class groups it into paved "
                    "and unpaved following the OSM wiki:"]),
            html.Ul(className="doc-list", children=[
                html.Li([html.Strong("paved: "), PAVED_VALUES]),
                html.Li([html.Strong("unpaved: "), UNPAVED_VALUES]),
            ]),
            html.P("Where a road has several values (for example asphalt;gravel), the first one is used. Many "
                   "roads have no surface tag, especially minor and rural roads, so an empty surface_class "
                   "means not recorded, not unpaved."),
        ]
    return _section("roads", "Roads", children)


def _usage(catalog):
    rows_per_part = f"{catalog.rows_per_part:,}"
    return _section("usage", "Usage", [
        html.H3("Download a country"),
        html.Ol(className="doc-steps", children=[
            html.Li(["Open the ", dcc.Link("download page", href=HOME_HREF), " and pick a country. You can "
                     "type to search the list."]),
            html.Li("The number of road segments, CSV files and the size of the zip appear under the list. "
                    "Click Download."),
            html.Li("The zip file goes to your browser's downloads. Files for the largest countries can be "
                    "several gigabytes, so use a stable connection."),
        ]),
        html.H3("What is in the zip"),
        html.P([f"A file such as vn_roads.zip holds the road CSV files, each with at most {rows_per_part} "
                "rows, and README.txt:"]),
        _code("road_openstreetmap_vn_part00001.csv\n"
              "road_openstreetmap_vn_part00002.csv\n"
              "...\n"
              "README.txt"),
        html.P("Rows are spread over the parts in no particular order: a part is not a region or a road "
               "class. Append all parts to get the whole country. All files are UTF-8 encoded."),
        html.H3("Combine the parts"),
        html.P("Python with pandas, then GeoPandas for a spatial layer:"),
        _code('import glob\n'
              'import pandas as pd\n'
              'import geopandas as gpd\n\n'
              'files = sorted(glob.glob("road_openstreetmap_vn_part*.csv"))\n'
              'roads = pd.concat((pd.read_csv(f) for f in files), ignore_index=True)\n\n'
              'roads = gpd.GeoDataFrame(\n'
              '    roads.drop(columns="geometry"),\n'
              '    geometry=gpd.GeoSeries.from_wkt(roads["geometry"]),\n'
              '    crs="EPSG:4326",\n'
              ')'),
        html.P("R with sf:"),
        _code('library(sf)\n\n'
              'files <- list.files(pattern = "^road_openstreetmap_vn_part[0-9]+\\\\.csv$")\n'
              'roads <- do.call(rbind, lapply(files, read.csv, fileEncoding = "UTF-8"))\n'
              'roads <- st_as_sf(roads, wkt = "geometry", crs = 4326)'),
        html.P("QGIS: use Layer > Add Layer > Add Delimited Text Layer, choose a CSV file, set Geometry "
               "definition to Well known text (WKT) with the geometry field and EPSG:4326. Add each part "
               "this way, then join them with Processing > Toolbox > Merge vector layers."),
        html.P("Spreadsheet programs cut a cell at 32,767 characters, so the geometry of very long roads can "
               "be truncated there. Use them for browsing names and classes, and Python, R or QGIS for "
               "analysis.", className="doc-callout"),
        html.H3("Credit the data"),
        html.P("When you publish anything made with these files, credit “© OpenStreetMap contributors”."),
    ])


def _achievements(catalog):
    tracked = len(cc.tracked_codes())
    pending = cc.not_yet_available(catalog.codes) if catalog.loaded else []
    children = []
    if catalog.loaded and catalog.countries:
        updated = format_date(catalog.updated_at)
        facts = [
            ("Countries and territories", f"{len(catalog.countries):,}"), #of {tracked:,}"),
            ("Road segments", f"{catalog.total_rows:,}"),
            ("Download size, all countries", rd.human_size(catalog.total_bytes)),
        ]
        if updated:
            facts.append(("Last updated", updated))
        children.append(html.Dl(className="doc-facts", children=[
            html.Div([html.Dt(label), html.Dd(value)]) for label, value in facts
        ]))
    children += [
        html.P("Every country is produced by the same process from the same source, so the files share "
               "one layout: the same columns, the same road classes, the same geometry encoding and the "
               "same file names. A script written for one country runs unchanged on any other."),
        html.P("Each file contains every road of the kept classes in that country's OpenStreetMap data, "
               "with the full line shape, ready to open without converting from OpenStreetMap's own "
               "formats."),
    ]
    # To add Pending Country List
    # if pending:
    #     children.append(html.Div(className="doc-pending", children=[
    #         html.H3("Not available yet"),
    #         html.P("We are working on these countries and territories:"),
    #         html.Ul(className="pending-list", children=[html.Li(cc.country_name(c)) for c in pending]),
    #     ]))
    # elif not catalog.loaded:
    #     children.append(html.P("The current list of countries could not be loaded. Refresh the page in a "
    #                            "minute.", className="doc-callout"))
    return _section("achievements", "Achievements", children)


def _summary(catalog):
    n = len(catalog.countries)
    scope = f"{n:,} countries and territories" if n else "each available country"
    year = datetime.now().year
    return _section("summary", "Summary", [
        html.P(f"This site turns OpenStreetMap's road network into one consistent download for {scope}: "
               "16 road classes from motorways to tracks, each road with its ID, name, class and shape, in "
               "CSV files that open in common analysis tools. The data come from Geofabrik's daily "
               "OpenStreetMap extracts and are shared under the Open Database License."),
        html.P("Suggested citation:"),
        html.Blockquote(className="doc-cite", children=(
            f"Road network data © OpenStreetMap contributors, available under the Open Database License "
            f"(ODbL). Country extracts from Geofabrik GmbH. Retrieved from {APP_TITLE}, World Bank, {year}."
        )),
    ])


def docs_layout(catalog, logo_src, pim_pam_logo_src):
    return html.Div(className="page page-docs", children=[
        build_header("docs", logo_src, pim_pam_logo_src),
        html.Div(className="docs-hero", children=[
            html.Div(className="docs-hero-roads", **{"aria-hidden": "true"}),
            html.Div(className="docs-hero-inner", children=[
                html.H1("Roads data documentation", className="docs-title"),
                html.P("What the downloads contain, where the data come from and how to use them.",
                       className="docs-lede"),
                html.P(className="docs-authors", children=[
                    "Developed by ", html.Span(AUTHORS[0]), 
                    " and ", html.Span(AUTHORS[1]), 
                    # " and ", html.Span(AUTHORS[2]),
                ]),
            ]),
        ]),
        html.Div(className="docs-body", children=[
            html.Nav(className="docs-toc", **{"aria-label": "On this page"}, children=[
                html.P("On this page", className="toc-label"),
                html.Ul([html.Li(html.A(label, href=f"#{sid}")) for sid, label in SECTIONS]),
            ]),
            html.Article(className="docs-article", children=[
                _intro(catalog),
                _data_source(catalog),
                _roads(catalog),
                _usage(catalog),
                _achievements(catalog),
                _summary(catalog),
            ]),
        ]),
        html.Footer(className="docs-footer", children=html.Div(className="docs-footer-inner", children=[
            credit_line("docs-credit"),
        ])),
    ])


def not_found_layout(logo_src, pim_pam_logo_src):
    return html.Div(className="page page-docs", children=[
        build_header("missing", logo_src, pim_pam_logo_src),
        html.Main(className="not-found", children=[
            html.H1("This page does not exist"),
            html.P("The link may be mistyped or out of date."),
            dcc.Link("Go to the download page", href=HOME_HREF, className="btn btn-primary"),
        ]),
    ])
