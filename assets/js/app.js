(() => {
  "use strict";

  const LEGACY_STORAGE_KEY = "night-city-map-local-v2";
  const PREFERENCES_KEY = "night-city-map-preferences-v1";
  const MAP_ID = 115;
  const $ = selector => document.querySelector(selector);
  const legacyState = loadJson(LEGACY_STORAGE_KEY, {});
  const preferences = loadJson(PREFERENCES_KEY, { hiddenTypes: [], hideFound: false, layer: 0 });
  const state = { custom: [], hiddenTypes: preferences.hiddenTypes || [], hideFound: !!preferences.hideFound, layer: Number(preferences.layer) || 0 };
  const elements = {
    sidebar: $("#sidebar"), filters: $("#filters"), search: $("#searchInput"), details: $("#details"),
    foundCount: $("#foundCount"), totalCount: $("#totalCount"), progressBar: $("#progressBar"),
    hideFound: $("#hideFoundButton"), visibleLabel: $("#visibleLabel"), addHint: $("#addHint"), toast: $("#toast")
  };

  let data;
  let locationDetails = {};
  let map;
  let tileLayers;
  let displayLayer;
  let typeBySlug = new Map();
  let entries = [];
  let entryById = new Map();
  let entryBySlug = new Map();
  let activeTypes = new Set();
  let found = new Set();
  let selectedId = null;
  let addMode = false;
  let toastTimer;

  function loadJson(key, fallback) {
    try {
      return { ...fallback, ...JSON.parse(localStorage.getItem(key) || "{}") };
    } catch {
      return fallback;
    }
  }

  function savePreferences() {
    state.hiddenTypes = [...typeBySlug.keys()].filter(slug => !typeBySlug.get(slug).isParent && !activeTypes.has(slug));
    if (!activeTypes.has("custom")) state.hiddenTypes.push("custom");
    localStorage.setItem(PREFERENCES_KEY, JSON.stringify({ hiddenTypes: state.hiddenTypes, hideFound: state.hideFound, layer: state.layer }));
  }

  async function apiFetch(path, options = {}) {
    const response = await fetch(path, {
      ...options,
      headers: { "Content-Type": "application/json", ...(options.headers || {}) }
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.error || `API request failed (${response.status})`);
    return payload;
  }

  function progressKey(item) {
    return String(item.custom ? item.id : item.slug);
  }

  function showToast(text) {
    clearTimeout(toastTimer);
    elements.toast.textContent = text;
    elements.toast.classList.add("show");
    toastTimer = setTimeout(() => elements.toast.classList.remove("show"), 2200);
  }

  function pinHtml(type, isFound = false) {
    if (!type?.icon) return `<div class="custom-pin ${isFound ? "found" : ""}">+</div>`;
    return `<div class="map-pin ${isFound ? "found" : ""}" style="background-position:-${type.icon.offsetX}px -${type.icon.offsetY}px"></div>`;
  }

  function markerIcon(item) {
    const type = typeBySlug.get(item.type);
    if (item.custom || !type?.icon) {
      return L.divIcon({ className: "", html: pinHtml(null, found.has(progressKey(item))), iconSize: [30, 39], iconAnchor: [15, 39] });
    }
    return L.divIcon({
      className: "",
      html: pinHtml(type, found.has(progressKey(item))),
      iconSize: [type.icon.width, type.icon.height],
      iconAnchor: [type.icon.anchorX ?? type.icon.width / 2, type.icon.anchorY ?? type.icon.height]
    });
  }

  function sidebarIcon(type) {
    if (!type?.icon) return `<span class="custom-pin" style="transform:scale(.62);transform-origin:center">+</span>`;
    const scale = 25 / 33;
    return `<span class="sprite" style="background-position:-${(type.icon.offsetX * scale).toFixed(2)}px -${(type.icon.offsetY * scale).toFixed(2)}px"></span>`;
  }

  function createEntry(item) {
    const marker = L.marker([item.lat, item.lng], { icon: markerIcon(item), title: item.name, riseOnHover: true });
    marker.on("click", () => openDetails(item.id));
    return { item, marker };
  }

  function refreshEntries() {
    const customItems = state.custom.map(item => ({ ...item, custom: true, type: item.type || "custom" }));
    entries = [...data.markers, ...customItems].map(createEntry);
    entryById = new Map(entries.map(entry => [String(entry.item.id), entry]));
    entryBySlug = new Map(entries.filter(entry => !entry.item.custom).map(entry => [String(entry.item.slug), entry]));
  }

  function isVisible(item, query) {
    if (!item.custom && !activeTypes.has(item.type)) return false;
    if (item.custom && !activeTypes.has("custom")) return false;
    if (state.hideFound && found.has(progressKey(item))) return false;
    if (!query) return true;
    const typeName = typeBySlug.get(item.type)?.name || "Custom";
    return `${item.name} ${typeName} ${item.notes || ""}`.toLocaleLowerCase("en").includes(query);
  }

  function renderMarkers() {
    const query = elements.search.value.trim().toLocaleLowerCase("en");
    displayLayer.clearLayers();
    let visible = 0;
    for (const entry of entries) {
      if (!isVisible(entry.item, query)) continue;
      entry.marker.setIcon(markerIcon(entry.item));
      displayLayer.addLayer(entry.marker);
      visible += 1;
    }
    elements.visibleLabel.textContent = `${visible.toLocaleString("en-US")} locations`;
    renderProgress();
  }

  function renderProgress() {
    const total = data.markers.length + state.custom.length;
    const currentIds = new Set(entries.map(entry => progressKey(entry.item)));
    const completed = [...found].filter(id => currentIds.has(id)).length;
    elements.foundCount.textContent = completed.toLocaleString("en-US");
    elements.totalCount.textContent = ` / ${total.toLocaleString("en-US")} found`;
    elements.progressBar.style.width = `${total ? completed / total * 100 : 0}%`;
    elements.hideFound.textContent = state.hideFound ? "Show found locations" : "Hide found locations";
  }

  function renderFilters() {
    const parentTypes = data.types.filter(type => type.isParent);
    const orphanTypes = data.types.filter(type => !type.isParent && !type.parent);
    typeBySlug.set("custom", { slug: "custom", name: "Custom markers", icon: null, count: state.custom.length, isParent: false });
    const groups = parentTypes.map(parent => ({ parent, children: parent.childTypes.map(slug => typeBySlug.get(slug)).filter(Boolean) }));
    if (orphanTypes.length) groups.push({ parent: { slug: "other-local", name: "Other", isParent: true }, children: orphanTypes });
    groups.push({ parent: { slug: "custom-group", name: "My markers", isParent: true }, children: [typeBySlug.get("custom")] });

    elements.filters.innerHTML = groups.map((group, groupIndex) => {
      const total = group.children.reduce((sum, type) => sum + (type.slug === "custom" ? state.custom.length : type.count), 0);
      return `<section class="filter-group ${groupIndex > 2 ? "collapsed" : ""}" data-group="${group.parent.slug}">
        <button class="group-button" type="button"><span class="group-chevron">▾</span><span>${escapeHtml(group.parent.name)}</span><span class="group-count">${total.toLocaleString("en-US")}</span></button>
        <div class="group-children">${group.children.map(type => `<label class="filter-row">
          <input type="checkbox" value="${type.slug}" ${activeTypes.has(type.slug) ? "checked" : ""} />
          ${sidebarIcon(type)}<span class="filter-name">${escapeHtml(type.name)}</span><span class="filter-count">${(type.slug === "custom" ? state.custom.length : type.count).toLocaleString("en-US")}</span>
        </label>`).join("")}</div>
      </section>`;
    }).join("");

    elements.filters.querySelectorAll(".group-button").forEach(button => button.addEventListener("click", () => button.closest(".filter-group").classList.toggle("collapsed")));
    elements.filters.querySelectorAll("input[type=checkbox]").forEach(input => input.addEventListener("change", () => {
      if (input.checked) activeTypes.add(input.value); else activeTypes.delete(input.value);
      savePreferences(); renderMarkers();
    }));
  }

  function escapeHtml(value = "") {
    const span = document.createElement("span");
    span.textContent = String(value);
    return span.innerHTML;
  }

  function escapeAttribute(value = "") {
    return escapeHtml(value).replaceAll('"', "&quot;").replaceAll("'", "&#39;");
  }

  function renderInlineMarkdown(value) {
    const pattern = /\[([^\]]+)]\(([^)\s]+)\)|\*\*([^*]+)\*\*|_([^_\n]+)_|\*([^*\n]+)\*/g;
    let html = "";
    let cursor = 0;
    for (const match of value.matchAll(pattern)) {
      html += escapeHtml(value.slice(cursor, match.index));
      if (match[1] !== undefined) {
        const label = escapeHtml(match[1]);
        const localMatch = match[2].match(/[?&]locationIds?=(\d+)/);
        if (localMatch) {
          html += `<button type="button" class="location-link" data-location-id="${localMatch[1]}">${label}</button>`;
        } else {
          try {
            const url = new URL(match[2], window.location.origin);
            html += ["http:", "https:"].includes(url.protocol)
              ? `<a href="${escapeAttribute(url.href)}" target="_blank" rel="noopener noreferrer">${label}</a>`
              : label;
          } catch {
            html += label;
          }
        }
      } else if (match[3] !== undefined) {
        html += `<strong>${escapeHtml(match[3])}</strong>`;
      } else {
        html += `<em>${escapeHtml(match[4] ?? match[5])}</em>`;
      }
      cursor = match.index + match[0].length;
    }
    return html + escapeHtml(value.slice(cursor));
  }

  function renderMarkdown(markdown = "") {
    const lines = String(markdown).replaceAll("\r", "").split("\n");
    const output = [];
    let paragraph = [];
    let list = [];
    const flushParagraph = () => {
      if (!paragraph.length) return;
      output.push(`<p>${paragraph.map(renderInlineMarkdown).join("<br>")}</p>`);
      paragraph = [];
    };
    const flushList = () => {
      if (!list.length) return;
      output.push(`<ul>${list.map(item => `<li>${renderInlineMarkdown(item)}</li>`).join("")}</ul>`);
      list = [];
    };
    for (const rawLine of lines) {
      const bullet = rawLine.match(/^\s*[-*]\s+(.+)$/);
      if (bullet) {
        flushParagraph();
        list.push(bullet[1]);
      } else if (!rawLine.trim()) {
        flushParagraph();
        flushList();
      } else {
        flushList();
        paragraph.push(rawLine.trim());
      }
    }
    flushParagraph();
    flushList();
    return output.join("");
  }

  function getItem(id) {
    return entryById.get(String(id))?.item;
  }

  function focusLocation(locationId) {
    const entry = entryBySlug.get(String(locationId));
    if (!entry) {
      showToast(`Location ${locationId} is not available in this map`);
      return;
    }

    let filtersChanged = false;
    if (!activeTypes.has(entry.item.type)) {
      activeTypes.add(entry.item.type);
      filtersChanged = true;
    }
    if (state.hideFound && found.has(progressKey(entry.item))) {
      state.hideFound = false;
      filtersChanged = true;
    }
    if (elements.search.value) {
      elements.search.value = "";
      filtersChanged = true;
    }
    if (filtersChanged) {
      savePreferences();
      renderFilters();
      renderMarkers();
    }

    const currentZoom = map.getZoom();
    const nativeZoomLimit = data.map.maxNativeZoom || data.map.maxZoom;
    const focusZoom = Math.max(currentZoom, Math.min(nativeZoomLimit, currentZoom + 2));
    map.flyTo([entry.item.lat, entry.item.lng], focusZoom, { duration: 0.55 });
    openDetails(entry.item.id);
  }

  function openDetails(id) {
    const item = getItem(id);
    if (!item) return;
    selectedId = id;
    const type = typeBySlug.get(item.type) || typeBySlug.get("custom");
    $("#detailIcon").innerHTML = sidebarIcon(type);
    $("#detailCategory").textContent = type.name;
    $("#detailName").textContent = item.name;
    $("#detailCoordinates").textContent = `${item.lat.toFixed(7)}, ${item.lng.toFixed(7)}`;
    $("#detailRegion").textContent = item.regionId ?? "—";
    const detail = item.custom ? null : locationDetails[String(item.slug)];
    const description = item.custom ? item.notes : detail?.description;
    const descriptionElement = $("#detailDescription");
    descriptionElement.innerHTML = renderMarkdown(description || "");
    descriptionElement.hidden = !description?.trim();
    const isFound = found.has(progressKey(item));
    $("#foundButton").textContent = isFound ? "Found ✓" : "Mark as found";
    $("#foundButton").classList.toggle("is-found", isFound);
    $("#editCustomButton").hidden = !item.custom;
    $("#deleteCustomButton").hidden = !item.custom;
    elements.details.hidden = false;
    elements.details.scrollTop = 0;
  }

  function closeDetails() {
    selectedId = null;
    elements.details.hidden = true;
  }

  async function toggleFound() {
    if (!selectedId) return;
    const item = getItem(selectedId);
    const key = progressKey(item);
    const wasFound = found.has(key);
    const button = $("#foundButton");
    button.disabled = true;
    try {
      await apiFetch(`/api/v1/user/locations/${encodeURIComponent(key)}`, {
        method: wasFound ? "DELETE" : "PUT",
        body: JSON.stringify({ mapId: MAP_ID })
      });
      if (wasFound) found.delete(key); else found.add(key);
      renderMarkers(); openDetails(selectedId);
      showToast(wasFound ? "Found mark removed" : "Location marked as found");
    } catch (error) {
      showToast(error.message);
    } finally {
      button.disabled = false;
    }
  }

  function setLayer(index) {
    tileLayers.forEach(layer => map.removeLayer(layer));
    tileLayers[index].addTo(map);
    state.layer = index;
    $("#defaultLayerButton").classList.toggle("active", index === 0);
    $("#satelliteLayerButton").classList.toggle("active", index === 1);
    savePreferences();
  }

  function openMarkerDialog(item = null, latlng = null) {
    $("#markerDialogTitle").textContent = item ? "Edit marker" : "Add marker";
    $("#customId").value = item?.id || "";
    $("#customName").value = item?.name || "";
    $("#customType").value = item?.type || "custom";
    $("#customLat").value = (item?.lat ?? latlng?.lat ?? data.map.initialLat).toFixed(7);
    $("#customLng").value = (item?.lng ?? latlng?.lng ?? data.map.initialLng).toFixed(7);
    $("#customNotes").value = item?.notes || "";
    $("#markerDialog").showModal();
    setTimeout(() => $("#customName").focus(), 0);
  }

  async function saveCustomMarker(event) {
    event.preventDefault();
    const id = $("#customId").value;
    const item = {
      ...(id ? { id } : {}), mapId: MAP_ID,
      name: $("#customName").value.trim(), type: $("#customType").value,
      lat: Number($("#customLat").value), lng: Number($("#customLng").value), notes: $("#customNotes").value.trim(),
      regionId: null, custom: true
    };
    const submit = event.currentTarget.querySelector("button[type=submit]");
    submit.disabled = true;
    try {
      const saved = await apiFetch(id ? `/api/v1/user/custom-markers/${encodeURIComponent(id)}` : "/api/v1/user/custom-markers", {
        method: id ? "PUT" : "POST",
        body: JSON.stringify(item)
      });
      state.custom = id ? state.custom.map(entry => entry.id === id ? saved : entry) : [...state.custom, saved];
      activeTypes.add("custom");
      savePreferences(); $("#markerDialog").close(); refreshEntries(); renderFilters(); renderMarkers(); openDetails(saved.id);
      showToast(id ? "Custom marker updated" : "Custom marker added");
    } catch (error) {
      showToast(error.message);
    } finally {
      submit.disabled = false;
    }
  }

  function beginAddMode() {
    addMode = true;
    closeDetails();
    elements.addHint.hidden = false;
    map.getContainer().style.cursor = "crosshair";
    map.once("click", event => {
      if (!addMode) return;
      endAddMode();
      openMarkerDialog(null, event.latlng);
    });
  }

  function endAddMode() {
    addMode = false;
    elements.addHint.hidden = true;
    map.getContainer().style.cursor = "";
  }

  async function deleteCustom() {
    const item = getItem(selectedId);
    if (!item?.custom || !confirm(`Delete “${item.name}”?`)) return;
    try {
      await apiFetch(`/api/v1/user/custom-markers/${encodeURIComponent(item.id)}?mapId=${MAP_ID}`, { method: "DELETE" });
      state.custom = state.custom.filter(entry => entry.id !== selectedId);
      found.delete(progressKey(item));
      closeDetails(); refreshEntries(); renderFilters(); renderMarkers(); showToast("Custom marker deleted");
    } catch (error) { showToast(error.message); }
  }

  function exportData() {
    const payload = { version: 2, exportedAt: new Date().toISOString(), found: [...found], custom: state.custom };
    const url = URL.createObjectURL(new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" }));
    const link = document.createElement("a");
    link.href = url; link.download = `night-city-progress-${new Date().toISOString().slice(0,10)}.json`; link.click();
    URL.revokeObjectURL(url); showToast("Progress exported");
  }

  async function importData(file) {
    try {
      const payload = JSON.parse(await file.text());
      if (!Array.isArray(payload.found) || !Array.isArray(payload.custom)) throw new Error("Invalid backup format");
      const result = await apiFetch("/api/v1/user/import", {
        method: "POST",
        body: JSON.stringify({ mapId: MAP_ID, found: payload.found, custom: payload.custom })
      });
      const [mapState, customState] = await Promise.all([
        apiFetch(`/api/v1/user/map-data/${MAP_ID}`),
        apiFetch(`/api/v1/user/custom-markers?mapId=${MAP_ID}`)
      ]);
      found = new Set(Object.keys(mapState.locations || {}));
      state.custom = customState.markers || [];
      refreshEntries(); renderFilters(); renderMarkers(); closeDetails(); showToast(`${result.locations} found locations imported`);
    } catch (error) { showToast(error.message); }
  }

  function bindEvents() {
    elements.search.addEventListener("input", renderMarkers);
    document.addEventListener("keydown", event => {
      if (event.key === "/" && !["INPUT","TEXTAREA","SELECT"].includes(document.activeElement.tagName)) { event.preventDefault(); elements.search.focus(); }
      if (event.key === "Escape" && addMode) endAddMode();
    });
    $("#showAllButton").addEventListener("click", () => { activeTypes = new Set([...typeBySlug.values()].filter(type => !type.isParent).map(type => type.slug)); savePreferences(); renderFilters(); renderMarkers(); });
    $("#hideAllButton").addEventListener("click", () => { activeTypes.clear(); savePreferences(); renderFilters(); renderMarkers(); });
    elements.hideFound.addEventListener("click", () => { state.hideFound = !state.hideFound; savePreferences(); renderMarkers(); });
    $("#defaultLayerButton").addEventListener("click", () => setLayer(0));
    $("#satelliteLayerButton").addEventListener("click", () => setLayer(1));
    $("#closeDetails").addEventListener("click", closeDetails);
    $("#detailDescription").addEventListener("click", event => {
      const link = event.target.closest("[data-location-id]");
      if (link) focusLocation(link.dataset.locationId);
    });
    $("#foundButton").addEventListener("click", toggleFound);
    $("#addMarkerButton").addEventListener("click", beginAddMode);
    $("#editCustomButton").addEventListener("click", () => openMarkerDialog(getItem(selectedId)));
    $("#deleteCustomButton").addEventListener("click", deleteCustom);
    $("#markerForm").addEventListener("submit", saveCustomMarker);
    $("#dataButton").addEventListener("click", () => $("#dataDialog").showModal());
    $("#exportButton").addEventListener("click", exportData);
    $("#importInput").addEventListener("change", event => { if (event.target.files[0]) importData(event.target.files[0]); event.target.value = ""; });
    $("#resetFoundButton").addEventListener("click", async () => {
      if (!confirm("Reset every found location?")) return;
      try {
        await apiFetch(`/api/v1/user/locations?mapId=${MAP_ID}`, { method: "DELETE" });
        found.clear(); renderMarkers(); closeDetails(); showToast("Found progress reset");
      } catch (error) { showToast(error.message); }
    });
    document.querySelectorAll("[data-close]").forEach(button => button.addEventListener("click", () => document.getElementById(button.dataset.close).close()));
    $("#menuButton").addEventListener("click", () => elements.sidebar.classList.add("open"));
    $("#closeSidebar").addEventListener("click", () => elements.sidebar.classList.remove("open"));
    $("#mobileSearchButton").addEventListener("click", () => { elements.sidebar.classList.add("open"); setTimeout(() => elements.search.focus(), 180); });
  }

  async function initialize() {
    try {
      const [mapFile, detailsFile, mapState, customState] = await Promise.all([
        fetch("assets/data/map-data.json?v=7").then(response => { if (!response.ok) throw new Error(`HTTP ${response.status}`); return response.json(); }),
        fetch("assets/data/location-details.json?v=1").then(response => { if (!response.ok) throw new Error(`HTTP ${response.status}`); return response.json(); }),
        apiFetch(`/api/v1/user/map-data/${MAP_ID}`),
        apiFetch(`/api/v1/user/custom-markers?mapId=${MAP_ID}`)
      ]);
      data = mapFile;
      locationDetails = detailsFile;
      found = new Set(Object.keys(mapState.locations || {}));
      state.custom = customState.markers || [];

      if (found.size === 0 && state.custom.length === 0 && (legacyState.found?.length || legacyState.custom?.length)) {
        const markerIds = new Map(data.markers.map(marker => [String(marker.id), String(marker.slug)]));
        const migratedFound = (legacyState.found || []).map(value => markerIds.get(String(value)) || String(value));
        await apiFetch("/api/v1/user/import", {
          method: "POST",
          body: JSON.stringify({ mapId: MAP_ID, found: migratedFound, custom: legacyState.custom || [] })
        });
        const migratedCustom = await apiFetch(`/api/v1/user/custom-markers?mapId=${MAP_ID}`);
        found = new Set(migratedFound);
        state.custom = migratedCustom.markers || [];
        localStorage.removeItem(LEGACY_STORAGE_KEY);
        showToast("Browser progress migrated to SQLite");
      }
      typeBySlug = new Map(data.types.map(type => [type.slug, type]));
      const leafTypes = data.types.filter(type => !type.isParent);
      activeTypes = new Set(leafTypes.filter(type => !state.hiddenTypes.includes(type.slug)).map(type => type.slug));
      if (!state.hiddenTypes.includes("custom")) activeTypes.add("custom");

      map = L.map("map", { minZoom: data.map.minZoom, maxZoom: data.map.maxZoom, zoomControl: true, preferCanvas: true })
        .setView([data.map.initialLat, data.map.initialLng], Math.min(data.map.maxZoom, data.map.initialZoom + 2));
      map.setMaxBounds([[0.25, -1.12], [1.08, -0.28]]);
      tileLayers = data.map.tilesets.map((url, index) => L.tileLayer(url, {
        minZoom: data.map.minZoom, maxZoom: data.map.maxZoom, maxNativeZoom: data.map.maxNativeZoom,
        noWrap: true, keepBuffer: 3, attribution: index === 0 ? "Map tiles © MapGenie" : "Satellite tiles © MapGenie"
      }));
      displayLayer = L.layerGroup().addTo(map);
      setLayer(Number(state.layer) === 1 ? 1 : 0);
      refreshEntries();

      $("#customType").innerHTML = `<option value="custom">Custom marker</option>${leafTypes.map(type => `<option value="${type.slug}">${escapeHtml(type.name)}</option>`).join("")}`;
      renderFilters(); renderMarkers(); bindEvents();
    } catch (error) {
      elements.filters.innerHTML = `<div class="loading">Map data could not be loaded: ${escapeHtml(error.message)}</div>`;
      console.error(error);
    }
  }

  initialize();
})();
