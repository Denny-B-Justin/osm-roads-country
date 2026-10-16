/* ============================================================================
   roads.js - clientside callbacks for the download page (Dash loads it from /assets).

   select(value, meta)                    enable the button, describe the chosen file
   download(n_clicks, value, meta, base)  start the download in a hidden iframe and
                                          show progress until the file starts arriving
   setTitle(search)                       tab title per page

   How "the file started arriving" is detected: the server sets the cookie
   osm_roads_dl=<token>-ok on the zip response (or <token>-missing / -failed on an
   error). We poll for it, because a download in an iframe fires no load event.
   ============================================================================ */

(function () {
  var COOKIE = "osm_roads_dl";
  var POLL_MS = 400;
  var GIVE_UP_MS = 120000;
  var BASE_TITLE = "OpenStreetMap Roads by Country";
  var TITLES = { "roads-data-documentation": "Documentation" };

  var busy = false;

  function nf(n) { return Number(n).toLocaleString("en-US"); }

  function describe(m) {
    var parts = m.parts === 1 ? "1 CSV file" : nf(m.parts) + " CSV files";
    var rows = m.rows === 1 ? "1 road segment" : nf(m.rows) + " road segments";
    return rows + " in " + parts + ". Zip file " + m.size + ".";
  }

  function readCookie() {
    var items = document.cookie ? document.cookie.split("; ") : [];
    for (var i = 0; i < items.length; i++) {
      var eq = items[i].indexOf("=");
      if (items[i].slice(0, eq) === COOKIE) return decodeURIComponent(items[i].slice(eq + 1));
    }
    return null;
  }

  function clearCookie() {
    document.cookie = COOKIE + "=; Max-Age=0; path=/; SameSite=Lax";
  }

  function newToken() {
    var s = "";
    var chars = "abcdefghijklmnopqrstuvwxyz0123456789";
    var bytes = new Uint8Array(20);
    (window.crypto || window.msCrypto).getRandomValues(bytes);
    for (var i = 0; i < bytes.length; i++) s += chars[bytes[i] % chars.length];
    return s;
  }

  function frame() {
    var f = document.getElementById("dl-frame");
    if (!f) {
      f = document.createElement("iframe");
      f.id = "dl-frame";
      f.title = "Download";
      f.setAttribute("aria-hidden", "true");
      f.tabIndex = -1;
      f.style.cssText = "position:absolute;width:0;height:0;border:0;visibility:hidden";
      document.body.appendChild(f);
    }
    return f;
  }

  function setBusy(on, label) {
    var set = window.dash_clientside.set_props;
    busy = on;
    set("dl-btn", { disabled: on, className: "btn btn-primary dl-btn" + (on ? " is-busy" : "") });
    set("dl-btn-label", { children: label });
  }

  function note(text, cls) {
    window.dash_clientside.set_props("dl-note", { children: text, className: "dl-note" + (cls ? " " + cls : "") });
  }

  function start(code, m, base) {
    var token = newToken();
    clearCookie();
    setBusy(true, "Preparing…");
    note("Preparing the " + m.name + " file (" + m.size + ")…", "is-busy");

    frame().src = base + encodeURIComponent(code) + "?t=" + token;

    var started = Date.now();
    var timer = setInterval(function () {
      var value = readCookie();
      var state = null;
      if (value && value.indexOf(token + "-") === 0) state = value.slice(token.length + 1);
      if (!state && Date.now() - started < GIVE_UP_MS) return;

      clearInterval(timer);
      clearCookie();
      setBusy(false, "Download");
      if (state === "ok") {
        note("The " + m.name + " download has started (" + m.size + "). It will appear in your browser's downloads.", "is-done");
      } else if (state === "missing") {
        note("The " + m.name + " file is not available right now. Refresh the page and try again in a few minutes.", "is-error");
      } else if (state === "failed") {
        note("The " + m.name + " file could not be fetched from the data store. Try again in a few minutes.", "is-error");
      } else {
        note("The download has not started yet. If nothing appears in your browser's downloads in the next few minutes, click Download again.", "is-error");
      }
    }, POLL_MS);
  }

  window.dash_clientside = Object.assign({}, window.dash_clientside, {
    roads: {
      select: function (value, meta) {
        var m = value && meta ? meta[value] : null;
        if (!m) return [true, "", "dl-note"];
        return [busy, describe(m), "dl-note"];
      },

      download: function (nClicks, value, meta, base) {
        var m = value && meta ? meta[value] : null;
        if (!nClicks || !m || busy) return window.dash_clientside.no_update;
        start(value, m, base);
        return nClicks;
      },

      setTitle: function (search) {
        var page = new URLSearchParams(search || "").get("page") || "";
        document.title = TITLES[page] ? TITLES[page] + " – " + BASE_TITLE : BASE_TITLE;
        if (window.location.hash) {
          // Content is rendered after load, so jump to #section once it exists.
          var id = window.location.hash.slice(1);
          setTimeout(function () {
            var el = document.getElementById(id);
            if (el) el.scrollIntoView();
          }, 300);
        }
        return "";
      }
    }
  });
})();
