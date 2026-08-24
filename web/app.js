/* AVGAS-Map front-end.
 *
 * Data-source resolution: try a local manifest at data/index.json first (local
 * preview, written by `run_pipeline.py --local`); fall back to the published
 * manifest that ships with the deployed site. Same code both ways.
 *
 * Renders AVGAS-only aerodromes (features) as clustered Leaflet markers, with a
 * detail popup, an AIRAC-cycle selector (default latest), a grade filter, and
 * search. Tolerant of older dataset schema_versions: reads what is present,
 * treats missing fields as unknown, never assumes a field exists.
 */
(function () {
  "use strict";

  // Published manifest location (relative to the deployed site). For v1 the
  // pipeline ships index.json alongside the site; the local path is tried first.
  var LOCAL_MANIFEST = "data/index.json";
  var PUBLISHED_MANIFEST = "index.json";

  var map, cluster;
  var allFeatures = [];   // features for the currently loaded cycle
  var markersByIcao = {}; // icao -> marker (for search focus)
  var manifestBase = "";  // URL the active manifest was loaded from (for relative cycle URLs)

  function el(id) { return document.getElementById(id); }

  function showStatus(msg, isError) {
    var s = el("status");
    s.textContent = msg;
    s.classList.toggle("error", !!isError);
    s.hidden = false;
  }
  function clearStatus() { el("status").hidden = true; }

  function initMap() {
    map = L.map("map", { worldCopyJump: true }).setView([46.6, 2.4], 6); // France-ish default
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 18,
      attribution: "© OpenStreetMap contributors"
    }).addTo(map);
    cluster = L.markerClusterGroup();
    map.addLayer(cluster);

    // FR/EN toggle inside popups (delegated, bound once). Buttons carry the
    // target element id and the language; the target holds both texts in data-*.
    document.addEventListener("click", function (e) {
      var btn = e.target.closest && e.target.closest(".fren-btn");
      if (!btn) return;
      e.preventDefault();
      var target = document.getElementById(btn.getAttribute("data-target"));
      if (!target) return;
      var lang = btn.getAttribute("data-lang");
      target.textContent = target.getAttribute("data-" + lang) || "";
      var group = btn.parentNode;
      Array.prototype.forEach.call(group.querySelectorAll(".fren-btn"), function (b) {
        b.classList.toggle("active", b === btn);
      });
    });
  }

  function fetchJson(url) {
    return fetch(url, { cache: "no-store" }).then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status + " for " + url);
      return r.json();
    });
  }

  // Resolve the manifest: local first, then published. Remember WHICH manifest
  // URL we loaded so cycle URLs (which may be relative, e.g. the local
  // "dataset-2608.geojson") resolve against the manifest's own location rather
  // than the page. Absolute cycle URLs (published Release assets) are unaffected.
  function resolveManifest() {
    return fetchJson(LOCAL_MANIFEST)
      .then(function (m) { return { manifest: m, base: LOCAL_MANIFEST }; })
      .catch(function () {
        return fetchJson(PUBLISHED_MANIFEST).then(function (m) {
          return { manifest: m, base: PUBLISHED_MANIFEST };
        });
      });
  }

  // Resolve a (possibly relative) cycle URL against the manifest's URL.
  function resolveDataUrl(entryUrl, manifestBase) {
    try {
      return new URL(entryUrl, new URL(manifestBase, window.location.href)).href;
    } catch (e) {
      return entryUrl; // fall back to as-is if URL construction fails
    }
  }

  function selectedGrades() {
    var out = [];
    document.querySelectorAll(".grade-filter").forEach(function (cb) {
      if (cb.checked) out.push(cb.value);
    });
    return out;
  }

  function featureMatchesGrades(feature, grades) {
    var g = (feature.properties && feature.properties.avgas_grades) || [];
    return g.some(function (x) { return grades.indexOf(x) !== -1; });
  }

  function selectedProvider() {
    var sel = el("provider-select");
    return sel ? sel.value : "";
  }

  function featureMatchesProvider(feature, provider) {
    if (!provider) return true; // "All"
    var b = feature.properties && feature.properties.conditions
      && feature.properties.conditions.brand;
    return b === provider;
  }

  // Populate the provider dropdown from the brands present in the loaded cycle.
  function populateProviders(features) {
    var sel = el("provider-select");
    if (!sel) return;
    var brands = {};
    features.forEach(function (f) {
      var b = f.properties && f.properties.conditions && f.properties.conditions.brand;
      if (b) brands[b] = true;
    });
    var prev = sel.value;
    sel.innerHTML = '<option value="">All providers</option>';
    Object.keys(brands).sort().forEach(function (b) {
      var o = document.createElement("option");
      o.value = b;
      o.textContent = b;
      sel.appendChild(o);
    });
    // Keep the prior selection if it still exists.
    sel.value = Array.prototype.some.call(sel.options, function (o) { return o.value === prev; })
      ? prev : "";
  }

  function escapeHtml(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function conditionFlags(conditions) {
    if (!conditions) return [];
    var labels = {
      on_request: "On request", ppr: "PPR", self_service: "Self-service",
      reserved_for_based: "Based aircraft only", mil_civ_split: "MIL/CIV",
      has_hours: "Operating hours"
    };
    var out = [];
    Object.keys(labels).forEach(function (k) {
      if (conditions[k]) out.push(labels[k]);
    });
    if (conditions.payment && conditions.payment.length) {
      out.push(conditions.payment.map(escapeHtml).join("/"));
    }
    return out;
  }

  // Split the cleaned source text into French and English. The French AIP marks
  // the English translation as italic (`_..._`). Lines whose content is wrapped
  // in balanced underscores are English; the rest are French. A line may hold
  // both; we route each italic span to EN and the remainder to FR.
  function splitFrEn(text) {
    var fr = [], en = [];
    (text || "").split("\n").forEach(function (line) {
      var italic = [], plain = line;
      plain = plain.replace(/_([^_]+)_/g, function (_m, inner) {
        italic.push(inner.trim());
        return " ";
      });
      plain = plain.replace(/\s{2,}/g, " ").trim();
      if (plain) fr.push(plain);
      if (italic.length) en.push(italic.join(" "));
    });
    return { fr: fr.join("\n").trim(), en: en.join("\n").trim() };
  }

  // Render phone/website/email as usable links; other contact-ish info as text.
  function contactLinks(conditions) {
    if (!conditions) return "";
    var parts = [];
    if (conditions.phone) {
      var tel = conditions.phone.replace(/[^\d+]/g, "");
      parts.push('<div class="contact">☎ <a href="tel:' + escapeHtml(tel) + '">' +
        escapeHtml(conditions.phone) + "</a></div>");
    }
    if (conditions.website) {
      var href = /^https?:\/\//i.test(conditions.website)
        ? conditions.website : "https://" + conditions.website;
      parts.push('<div class="contact">🌐 <a href="' + escapeHtml(href) +
        '" target="_blank" rel="noopener noreferrer">' +
        escapeHtml(conditions.website) + "</a></div>");
    }
    if (conditions.email) {
      parts.push('<div class="contact">✉ <a href="mailto:' + escapeHtml(conditions.email) +
        '">' + escapeHtml(conditions.email) + "</a></div>");
    }
    return parts.join("");
  }

  var _popupSeq = 0;

  function popupHtml(props) {
    var grades = props.avgas_grades || [];
    // AVGAS grades render RED per the international fuel-colour convention.
    var badges = grades.map(function (g) {
      return '<span class="badge avgas">' + escapeHtml(g) + "</span>";
    }).join("");
    // Jet A-1 renders BLACK, as a secondary detail.
    var jet = props.jet_a1
      ? '<div class="jet"><span class="badge jet-badge">Jet A-1</span> also available</div>'
      : "";
    var brand = (props.conditions && props.conditions.brand)
      ? '<div class="provider">Provider: <strong>' +
        escapeHtml(props.conditions.brand) + "</strong></div>" : "";
    var flags = conditionFlags(props.conditions).map(function (f) {
      return '<span class="flag">' + f + "</span>";
    }).join("");
    var contacts = contactLinks(props.conditions);
    var amdt = props.amdt ? '<div class="amdt">Source AMDT ' + escapeHtml(props.amdt) + "</div>" : "";

    // Source text with a small FR/EN toggle.
    var raw = "";
    if (props.source_text) {
      var parts = splitFrEn(props.source_text);
      var id = "src" + (++_popupSeq);
      var hasEn = !!parts.en;
      var toggle = hasEn
        ? '<span class="fren-toggle" role="group" aria-label="Language">' +
          '<button type="button" class="fren-btn active" data-target="' + id +
          '" data-lang="fr">FR</button>' +
          '<button type="button" class="fren-btn" data-target="' + id +
          '" data-lang="en">EN</button></span>'
        : "";
      raw =
        '<details><summary>Source text ' + toggle + "</summary>" +
        '<div class="raw" id="' + id + '" data-fr="' + escapeHtml(parts.fr) +
        '" data-en="' + escapeHtml(parts.en) + '">' +
        escapeHtml(parts.fr) + "</div></details>";
    }
    return (
      '<div class="avgas-popup">' +
      "<h3>" + escapeHtml(props.name || props.icao) +
      ' <span class="icao">' + escapeHtml(props.icao) + "</span></h3>" +
      '<div class="grades">' + (badges || "No AVGAS grade listed") + "</div>" +
      jet +
      brand +
      (flags ? '<div class="flags">' + flags + "</div>" : "") +
      contacts +
      amdt +
      raw +
      "</div>"
    );
  }

  function render(features) {
    cluster.clearLayers();
    markersByIcao = {};
    var grades = selectedGrades();
    var provider = selectedProvider();
    var bounds = [];
    features.forEach(function (f) {
      if (!featureMatchesGrades(f, grades)) return;
      if (!featureMatchesProvider(f, provider)) return;
      var c = f.geometry && f.geometry.coordinates;
      if (!c || c.length !== 2) return;
      var latlng = [c[1], c[0]];
      var marker = L.marker(latlng);
      marker.bindPopup(popupHtml(f.properties || {}));
      cluster.addLayer(marker);
      markersByIcao[(f.properties.icao || "").toUpperCase()] = { marker: marker, latlng: latlng };
      bounds.push(latlng);
    });
    if (bounds.length) map.fitBounds(bounds, { padding: [30, 30], maxZoom: 10 });
  }

  function loadCycle(manifest, cycle) {
    var entry = manifest.cycles.find(function (c) { return c.cycle === cycle; });
    if (!entry) { showStatus("Cycle " + cycle + " not found.", true); return; }
    clearStatus();
    fetchJson(resolveDataUrl(entry.url, manifestBase)).then(function (dataset) {
      allFeatures = dataset.features || [];
      var meta = dataset.metadata || {};
      // Freshness only when both effective date and cycle are known.
      if (meta.effective_date && meta.airac_cycle) {
        el("freshness").textContent =
          "AIRAC " + meta.airac_cycle + " · effective " + meta.effective_date;
      } else {
        el("freshness").textContent = "";
      }
      if (meta.attribution && meta.attribution.fuel) {
        el("attr-fuel").textContent = Object.values(meta.attribution.fuel).join(", ");
      }
      populateProviders(allFeatures);
      render(allFeatures);
    }).catch(function (e) {
      showStatus("Could not load aerodrome data: " + e.message, true);
    });
  }

  function populateCycles(manifest) {
    var sel = el("cycle-select");
    sel.innerHTML = "";
    (manifest.cycles || []).forEach(function (c) {
      var o = document.createElement("option");
      o.value = c.cycle;
      o.textContent = c.cycle + (c.cycle === manifest.latest ? " (latest)" : "");
      sel.appendChild(o);
    });
    sel.value = manifest.latest || (manifest.cycles[0] && manifest.cycles[0].cycle);
    sel.addEventListener("change", function () { loadCycle(manifest, sel.value); });
  }

  function wireControls(manifest) {
    document.querySelectorAll(".grade-filter").forEach(function (cb) {
      cb.addEventListener("change", function () { render(allFeatures); });
    });
    var provSel = el("provider-select");
    if (provSel) provSel.addEventListener("change", function () { render(allFeatures); });
    el("search").addEventListener("keydown", function (e) {
      if (e.key !== "Enter") return;
      var q = e.target.value.trim().toUpperCase();
      if (!q) return;
      // Exact ICAO first, then name contains.
      var hit = markersByIcao[q];
      if (!hit) {
        var f = allFeatures.find(function (x) {
          var p = x.properties || {};
          return (p.name || "").toUpperCase().indexOf(q) !== -1;
        });
        if (f) hit = markersByIcao[(f.properties.icao || "").toUpperCase()];
      }
      if (hit) {
        clearStatus();
        map.setView(hit.latlng, 11);
        hit.marker.openPopup();
      } else {
        showStatus("No aerodrome found for “" + e.target.value + "”.");
      }
    });
  }

  function boot() {
    initMap();
    resolveManifest().then(function (resolved) {
      var manifest = resolved.manifest;
      manifestBase = resolved.base;
      if (!manifest.cycles || !manifest.cycles.length) {
        showStatus("No published data yet.", true);
        return;
      }
      populateCycles(manifest);
      wireControls(manifest);
      loadCycle(manifest, el("cycle-select").value);
    }).catch(function (e) {
      showStatus("Could not load the data manifest: " + e.message, true);
    });
  }

  document.addEventListener("DOMContentLoaded", boot);
})();
