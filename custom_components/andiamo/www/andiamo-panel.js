// Andiamo sidebar panel: places, stations, routes and settings.
// Plain web component, no build step. Edits happen inline, no dialogs.

const T = {
  routes: "Routes", places: "Places", settings: "Settings",
  addRoute: "Add route", addPlace: "Add place", addStation: "Add station",
  name: "Name", from: "From", to: "To", mode: "Mode", transit: "Public transport", car: "Car",
  station: "Station", mainStation: "Main station", speaker: "Speaker",
  lines: "Lines", pickLine: "Pick a line", loadingLines: "Loading lines…", noLines: "No departures found from this station.",
  walk: "Walk (min)", save: "Save", cancel: "Cancel", delete: "Delete", edit: "Edit",
  start: "Start", stop: "Stop", arriveBy: "Arrive by", leaveAt: "Leave at {0}", inMin: "in {0} min",
  main: "Main", makeMain: "Make main", search: "Search", searchStop: "Search a stop…", searchAddress: "Search an address…",
  latitude: "Latitude", longitude: "Longitude", useHome: "Use HA home",
  tts: "Text-to-speech", language: "Announcement language", none: "None", min: "min",
  lead: "Car countdown starts", leadHint: "Minutes before leaving",
  testMode: "Test mode", testModeHint: "Notifications instead of the speaker",
  noRoutes: "No routes yet.", noStations: "No stations yet.", running: "Running",
  noKeyTransit: "No opentransportdata.swiss key: public transport is off.",
  noKeyCar: "No TomTom key: car routes and address search are off.",
  keysHint: "API keys: Settings → Devices & services → Andiamo → Reconfigure.",
  deleteConfirm: "Delete {0}? Click again to confirm.", delay: "+{0} min",
  german: "German", english: "English",
};

const esc = (v) =>
  String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

const clock = (iso) => new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
const minutesUntil = (iso) => Math.max(0, Math.round((new Date(iso) - Date.now()) / 60000));

// "18:30" → the next 18:30 (today, or tomorrow if it has passed), as ISO.
const nextTime = (hhmm) => {
  const [h, m] = hhmm.split(":").map(Number);
  const d = new Date();
  d.setHours(h, m, 0, 0);
  if (d <= new Date()) d.setDate(d.getDate() + 1);
  return d.toISOString();
};

class AndiamoPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._tab = "routes";
    this._drafts = {};
    this._search = {};
    this._lines = {};
    this._confirm = null;
    this._error = "";
    this._data = null;
    this.shadowRoot.addEventListener("click", (e) => this._onClick(e));
    this.shadowRoot.addEventListener("input", (e) => this._onInput(e));
    this.shadowRoot.addEventListener("change", (e) => this._onInput(e));
    this.shadowRoot.addEventListener("keydown", (e) => this._onKey(e));
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first) this._subscribe();
  }

  set narrow(v) { this._narrow = v; }
  set panel(v) {}
  set route(v) {}

  connectedCallback() {
    if (this._hass && !this._unsub) this._subscribe();
    this._tick = setInterval(() => this._data && this._render(), 30000);
  }

  disconnectedCallback() {
    clearInterval(this._tick);
    if (this._unsub) this._unsub.then((u) => u());
    this._unsub = null;
  }

  _subscribe() {
    this._unsub = this._hass.connection.subscribeMessage(
      (data) => { this._data = data; this._render(); },
      { type: "andiamo/subscribe" },
    );
    this._unsub.catch((err) => { this._error = err.message; this._render(); });
  }

  _t(key, ...args) {
    let s = T[key] ?? key;
    args.forEach((a, i) => (s = s.replace(`{${i}}`, a)));
    return s;
  }

  async _ws(type, data = {}) {
    try {
      this._error = "";
      return await this._hass.callWS({ type: `andiamo/${type}`, ...data });
    } catch (err) {
      this._error = err.message || String(err);
      this._render();
      throw err;
    }
  }

  // Lookups

  _loc(id) { return this._data.locations.find((l) => l.id === id); }
  _stationsOf(id) { return this._data.stations.filter((s) => s.location_id === id); }
  _run(routeId) { return this._data.runs.find((r) => r.route_id === routeId); }
  _entities(domain) {
    return Object.keys(this._hass.states).filter((e) => e.startsWith(`${domain}.`)).sort()
      .map((e) => [e, this._hass.states[e].attributes.friendly_name || e]);
  }

  // Events

  _onInput(e) {
    const el = e.target;
    const field = el.dataset.draft;
    if (field) {
      const [key, name] = field.split("|");
      this._drafts[key] = this._drafts[key] || {};
      this._drafts[key][name] = el.type === "checkbox" ? el.checked : el.value;
      if (e.type === "change" && el.tagName === "SELECT") this._render();
    }
    if (el.dataset.setting && e.type === "change") {
      let value = el.type === "checkbox" ? el.checked : el.value;
      if (el.type === "number") value = Number(value);
      if (value === "") value = null;
      this._ws("settings", { changes: { [el.dataset.setting]: value } });
    }
  }

  _onKey(e) {
    const el = e.target;
    if (e.key === "Enter" && el.dataset.search) { e.preventDefault(); this._doSearch(el.dataset.search, el.dataset.kind); }
    else if (e.key === "Enter" && el.dataset.enter) { e.preventDefault(); this._act(el.dataset.enter, el.dataset.arg); }
    else if (e.key === "Escape" && el.dataset.draft) { delete this._drafts[el.dataset.draft.split("|")[0]]; this._render(); }
  }

  _onClick(e) {
    const el = e.target.closest("[data-action]");
    if (!el) return;
    this._act(el.dataset.action, el.dataset.arg);
  }

  async _act(action, arg) {
    const d = this._drafts;
    switch (action) {
      case "tab": this._tab = arg; break;
      case "open": d[arg] = this._draftFor(arg); break;
      case "close": delete d[arg]; delete this._search[arg]; break;
      case "press": await this._ws("press", { route_id: arg }); return;
      case "cancel-run": await this._ws("cancel", { route_id: arg }); return;
      case "start-car": {
        const time = d[`start:${arg}`]?.time;
        if (!time) return;
        await this._ws("start_car", { route_id: arg, arrive_at: nextTime(time) });
        delete d[`start:${arg}`];
        return;
      }
      case "save-route": await this._saveRoute(arg); break;
      case "toggle-line": {
        const [key, i] = arg.split("#");
        const r = d[key];
        const line = this._lineOptions(r)[i];
        const ticked = (r.lines || []).some((l) => l.key === line.key);
        r.lines = ticked ? r.lines.filter((l) => l.key !== line.key) : [...(r.lines || []), line];
        break;
      }
      case "save-loc": await this._saveLoc(arg); break;
      case "save-station": await this._saveStation(arg); break;
      case "main-loc": await this._ws("location/save", { item: { ...this._loc(arg), main: true } }); return;
      case "main-station": {
        const s = this._data.stations.find((x) => x.id === arg);
        await this._ws("station/save", { item: { ...s, main: true } });
        return;
      }
      case "delete": {
        if (this._confirm !== arg) { this._confirm = arg; break; }
        this._confirm = null;
        const [kind, id] = arg.split(":");
        await this._ws(`${kind}/delete`, { item_id: id });
        return;
      }
      case "pick-stop": {
        const [key, i] = arg.split("#");
        const stop = this._search[key].results[i];
        d[key] = { ...d[key], name: stop.name, stop_ref: stop.ref };
        delete this._search[key];
        break;
      }
      case "pick-place": {
        const [key, i] = arg.split("#");
        const place = this._search[key].results[i];
        d[key] = { ...d[key], latitude: place.latitude, longitude: place.longitude, address: place.name };
        if (!d[key].name) d[key].name = place.name.split(",")[0];
        delete this._search[key];
        break;
      }
      case "use-home": {
        const c = this._hass.config;
        d[arg] = { ...d[arg], latitude: c.latitude, longitude: c.longitude, address: c.location_name };
        break;
      }
      case "search": { const [key, kind] = arg.split("|"); this._doSearch(key, kind); return; }
    }
    this._render();
  }

  _draftFor(key) {
    const [kind, id, extra] = key.split(":");
    if (kind === "route") {
      if (id !== "new") return { ...this._data.routes.find((r) => r.id === id) };
      const main = this._data.locations.find((l) => l.main);
      const other = this._data.locations.find((l) => !l.main);
      return { mode: this._data.providers.transit ? "transit" : "car", origin_id: main?.id, destination_id: other?.id, lines: [] };
    }
    if (kind === "loc") return id === "new" ? {} : { ...this._loc(id) };
    if (kind === "station") {
      return id === "new" ? { location_id: extra, walk_minutes: 5 } : { ...this._data.stations.find((s) => s.id === id) };
    }
    return {};
  }

  async _doSearch(key, kind) {
    const query = (this._drafts[key]?.query || "").trim();
    if (!query) return;
    this._search[key] = { loading: true, results: [] };
    this._render();
    try {
      const results = await this._ws(kind === "stop" ? "search_stops" : "search_places", { query });
      this._search[key] = { results };
    } catch {
      delete this._search[key];
    }
    this._render();
  }

  async _saveRoute(key) {
    const r = this._drafts[key];
    const transit = r.mode === "transit";
    const item = {
      name: r.name || this._routeName(r),
      mode: r.mode, origin_id: r.origin_id,
      destination_id: transit ? null : r.destination_id,
      station_id: transit ? r.station_id || null : null,
      lines: transit ? r.lines || [] : [],
    };
    if (r.id) item.id = r.id;
    await this._ws("route/save", { item });
    delete this._drafts[key];
  }

  async _saveLoc(key) {
    const l = this._drafts[key];
    const item = { name: (l.name || "").trim(), latitude: Number(l.latitude), longitude: Number(l.longitude) };
    if (l.id) item.id = l.id;
    await this._ws("location/save", { item });
    delete this._drafts[key];
    delete this._search[key];
  }

  async _saveStation(key) {
    const s = this._drafts[key];
    const item = { location_id: s.location_id, name: s.name, stop_ref: s.stop_ref, walk_minutes: Number(s.walk_minutes || 0) };
    if (s.id) item.id = s.id;
    await this._ws("station/save", { item });
    delete this._drafts[key];
    delete this._search[key];
  }

  // Rendering

  _render() {
    const root = this.shadowRoot;
    const active = root.activeElement;
    const focus = active && (active.dataset.draft || active.dataset.search);
    const sel = active && active.selectionStart;
    root.innerHTML = `<style>${STYLE}</style>${this._data ? this._page() : this._loading()}`;
    if (focus) {
      const el = root.querySelector(`[data-draft="${focus}"]`);
      if (el) { el.focus(); try { el.setSelectionRange(sel, sel); } catch {} }
    }
  }

  _loading() {
    return `<div class="page"><p>${esc(this._error || "…")}</p></div>`;
  }

  _page() {
    const tabs = ["routes", "places", "settings"].map(
      (t) => `<button class="tab ${t === this._tab ? "on" : ""}" data-action="tab" data-arg="${t}">${this._t(t)}</button>`,
    ).join("");
    const body = { routes: () => this._routes(), places: () => this._places(), settings: () => this._settings() }[this._tab]();
    return `
      <div class="page">
        <header><h1>Andiamo</h1><nav>${tabs}</nav></header>
        ${this._error ? `<div class="error">${esc(this._error)}</div>` : ""}
        ${this._warnings()}
        ${body}
      </div>`;
  }

  _warnings() {
    const p = this._data.providers;
    const w = [];
    if (!p.transit) w.push(this._t("noKeyTransit"));
    if (!p.car) w.push(this._t("noKeyCar"));
    return w.length ? `<div class="hint">${w.map(esc).join("<br>")}<br>${esc(this._t("keysHint"))}</div>` : "";
  }

  _input(key, name, attrs = "") {
    const v = this._drafts[key]?.[name] ?? "";
    return `<input data-draft="${key}|${name}" value="${esc(v)}" ${attrs}>`;
  }

  _select(key, name, options, attrs = "") {
    const v = this._drafts[key]?.[name] ?? "";
    return `<select data-draft="${key}|${name}" ${attrs}>${options
      .map(([value, label]) => `<option value="${esc(value)}" ${String(value) === String(v) ? "selected" : ""}>${esc(label)}</option>`)
      .join("")}</select>`;
  }

  _deleteBtn(arg, label) {
    const confirming = this._confirm === arg;
    return `<button class="ghost danger" data-action="delete" data-arg="${arg}" title="${esc(confirming ? this._t("deleteConfirm", label) : this._t("delete"))}">${confirming ? this._t("deleteConfirm", esc(label)) : "✕"}</button>`;
  }

  _routes() {
    const rows = this._data.routes.map((r) => this._drafts[`route:${r.id}`] ? this._routeForm(`route:${r.id}`) : this._routeRow(r));
    return `
      <section class="card">
        ${rows.length ? rows.join("") : `<p class="muted">${this._t("noRoutes")}</p>`}
        ${this._drafts["route:new"] ? this._routeForm("route:new")
          : `<button class="add" data-action="open" data-arg="route:new">+ ${this._t("addRoute")}</button>`}
      </section>`;
  }

  _routeRow(r) {
    const run = this._run(r.id);
    const from = this._loc(r.origin_id)?.name;
    const icon = r.mode === "car" ? "🚗" : "🚋";
    let where;
    if (r.mode === "transit") {
      const s = this._routeStation(r);
      const lines = (r.lines || []).map((l) => `${l.name} → ${l.destination}`).join(", ");
      where = `${esc(from)}${s ? ` · ${esc(s.name)}` : ""} · ${lines ? esc(lines) : `<span class="late">${this._t("pickLine")}</span>`}`;
    } else {
      where = `${esc(from)} → ${esc(this._loc(r.destination_id)?.name)}`;
    }
    let action;
    if (run) {
      const delay = run.delay_minutes ? ` <span class="late">${this._t("delay", run.delay_minutes)}</span>` : "";
      const line = run.line ? ` · ${esc(run.line)} ${run.departure ? clock(run.departure) : ""}${delay}` : "";
      action = `<span class="run">${run.leave_at ? `${this._t("leaveAt", clock(run.leave_at))} · ${this._t("inMin", minutesUntil(run.leave_at))}` : this._t("running")}${line}</span>
        <button data-action="cancel-run" data-arg="${r.id}">${this._t("stop")}</button>`;
    } else if (r.mode === "transit") {
      action = `<button class="primary" data-action="press" data-arg="${r.id}" ${this._data.providers.transit && r.lines?.length ? "" : "disabled"}>${this._t("start")}</button>`;
    } else {
      const key = `start:${r.id}`;
      action = `<label class="inline">${this._t("arriveBy")} ${this._input(key, "time", `type="time" data-enter="start-car" data-arg="${r.id}"`)}</label>
        <button class="primary" data-action="start-car" data-arg="${r.id}" ${this._data.providers.car ? "" : "disabled"}>${this._t("start")}</button>`;
    }
    return `
      <div class="row ${run ? "active" : ""}">
        <div class="grow clickable" data-action="open" data-arg="route:${r.id}" title="${this._t("edit")}">
          <div class="title">${icon} ${esc(r.name)}</div>
          <div class="muted">${where}</div>
        </div>
        <div class="actions">${action}${this._deleteBtn(`route:${r.id}`, r.name)}</div>
      </div>`;
  }

  _routeForm(key) {
    const r = this._drafts[key];
    const transit = r.mode === "transit";
    const places = this._data.locations.map((l) => [l.id, l.name]);
    const modes = [["transit", this._t("transit")], ["car", this._t("car")]];
    let fields;
    if (transit) {
      const stations = [["", this._t("mainStation")], ...this._stationsOf(r.origin_id).map((s) => [s.id, `${s.name} (${s.walk_minutes}′)`])];
      fields = `
        <label>${this._t("station")} ${this._select(key, "station_id", stations)}</label>
        <div class="wide"><div class="muted">${this._t("lines")}</div>${this._lineChecks(key)}</div>`;
    } else {
      fields = `<label>${this._t("to")} ${this._select(key, "destination_id", places)}</label>`;
    }
    const ready = !transit || r.lines?.length;
    return `
      <div class="form">
        <label>${this._t("name")} ${this._input(key, "name", `placeholder="${esc(this._routeName(r))}" data-enter="save-route" data-arg="${key}"`)}</label>
        <label>${this._t("mode")} ${this._select(key, "mode", modes)}</label>
        <label>${this._t("from")} ${this._select(key, "origin_id", places)}</label>
        ${fields}
        <div class="buttons">
          <button class="primary" data-action="save-route" data-arg="${key}" ${ready ? "" : "disabled"}>${this._t("save")}</button>
          <button data-action="close" data-arg="${key}">${this._t("cancel")}</button>
        </div>
      </div>`;
  }

  _routeStation(r) {
    return r.station_id ? this._data.stations.find((x) => x.id === r.station_id)
      : this._stationsOf(r.origin_id).find((x) => x.main);
  }

  _routeName(r) {
    const from = this._loc(r.origin_id)?.name ?? "";
    const to = r.mode === "transit" ? r.lines?.[0]?.destination : this._loc(r.destination_id)?.name;
    return `${from} → ${to ?? ""}`;
  }

  // The station's lines, plus ticked ones it doesn't list right now.
  _lineOptions(r) {
    const found = this._lines[this._routeStation(r)?.id]?.results || [];
    const extra = (r.lines || []).filter((l) => !found.some((f) => f.key === l.key));
    return [...found, ...extra];
  }

  _lineChecks(key) {
    const r = this._drafts[key];
    const station = this._routeStation(r);
    if (!station) return `<p class="muted">${this._t("noStations")}</p>`;
    const state = this._lines[station.id];
    if (!state) this._loadLines(station.id);
    if (!state || state.loading) return `<p class="muted">${this._t("loadingLines")}</p>`;
    const options = this._lineOptions(r);
    if (!options.length) return `<p class="muted">${this._t("noLines")}</p>`;
    const ticked = new Set((r.lines || []).map((l) => l.key));
    return `<div class="lines">${options.map((l, i) => `
      <label class="check"><input type="checkbox" data-action="toggle-line" data-arg="${esc(key)}#${i}" ${ticked.has(l.key) ? "checked" : ""}>
        <span><b>${esc(l.name)}</b> → ${esc(l.destination)}</span></label>`).join("")}</div>`;
  }

  async _loadLines(stationId) {
    this._lines[stationId] = { loading: true };
    try {
      this._lines[stationId] = { results: await this._ws("lines", { station_id: stationId }) };
    } catch {
      this._lines[stationId] = { results: [] };
    }
    this._render();
  }


  _places() {
    const cards = this._data.locations.map((l) => this._placeCard(l)).join("");
    return `
      ${cards}
      <section class="card">
        ${this._drafts["loc:new"] ? this._placeForm("loc:new")
          : `<button class="add" data-action="open" data-arg="loc:new">+ ${this._t("addPlace")}</button>`}
      </section>`;
  }

  _placeCard(l) {
    const key = `loc:${l.id}`;
    const head = this._drafts[key] ? this._placeForm(key) : `
      <div class="row">
        <div class="grow clickable" data-action="open" data-arg="${key}" title="${this._t("edit")}">
          <div class="title">📍 ${esc(l.name)} ${l.main ? `<span class="badge">${this._t("main")}</span>` : ""}</div>
          <div class="muted">${l.latitude.toFixed(5)}, ${l.longitude.toFixed(5)}</div>
        </div>
        <div class="actions">
          ${l.main ? "" : `<button class="ghost" data-action="main-loc" data-arg="${l.id}">${this._t("makeMain")}</button>`}
          ${this._deleteBtn(`location:${l.id}`, l.name)}
        </div>
      </div>`;
    const stations = this._stationsOf(l.id).map((s) => this._drafts[`station:${s.id}`] ? this._stationForm(`station:${s.id}`) : `
      <div class="row sub">
        <div class="grow clickable" data-action="open" data-arg="station:${s.id}" title="${this._t("edit")}">
          🚏 ${esc(s.name)} <span class="muted">· ${this._t("walk")}: ${s.walk_minutes}</span>
          ${s.main ? `<span class="badge">${this._t("main")}</span>` : ""}
        </div>
        <div class="actions">
          ${s.main ? "" : `<button class="ghost" data-action="main-station" data-arg="${s.id}">${this._t("makeMain")}</button>`}
          ${this._deleteBtn(`station:${s.id}`, s.name)}
        </div>
      </div>`).join("");
    const newKey = `station:new:${l.id}`;
    const add = this._data.providers.transit
      ? this._drafts[newKey] ? this._stationForm(newKey)
        : `<button class="add sub" data-action="open" data-arg="${newKey}">+ ${this._t("addStation")}</button>`
      : "";
    return `<section class="card">${head}${stations}${add}</section>`;
  }

  _searchBox(key, kind) {
    const s = this._search[key];
    const results = s?.loading ? `<div class="muted">…</div>` : (s?.results || []).map(
      (r, i) => `<button class="result" data-action="${kind === "stop" ? "pick-stop" : "pick-place"}" data-arg="${key}#${i}">${esc(r.name)}</button>`,
    ).join("");
    return `
      <div class="search">
        ${this._input(key, "query", `placeholder="${this._t(kind === "stop" ? "searchStop" : "searchAddress")}" data-search="${key}" data-kind="${kind}"`)}
        <button data-action="search" data-arg="${key}|${kind}">${this._t("search")}</button>
      </div>
      ${results ? `<div class="results">${results}</div>` : ""}`;
  }

  _placeForm(key) {
    const l = this._drafts[key];
    const search = this._data.providers.car ? this._searchBox(key, "place") : "";
    return `
      <div class="form">
        <label>${this._t("name")} ${this._input(key, "name", `data-enter="save-loc" data-arg="${key}"`)}</label>
        <div class="wide">${search}</div>
        ${l.address ? `<div class="wide muted">${esc(l.address)}</div>` : ""}
        <label>${this._t("latitude")} ${this._input(key, "latitude", 'type="number" step="any"')}</label>
        <label>${this._t("longitude")} ${this._input(key, "longitude", 'type="number" step="any"')}</label>
        <div class="buttons">
          <button class="primary" data-action="save-loc" data-arg="${key}">${this._t("save")}</button>
          <button class="ghost" data-action="use-home" data-arg="${key}">${this._t("useHome")}</button>
          <button data-action="close" data-arg="${key}">${this._t("cancel")}</button>
        </div>
      </div>`;
  }

  _stationForm(key) {
    const s = this._drafts[key];
    return `
      <div class="form sub">
        <div class="wide">${s.stop_ref ? `🚏 <b>${esc(s.name)}</b>` : this._searchBox(key, "stop")}</div>
        <label>${this._t("walk")} ${this._input(key, "walk_minutes", `type="number" min="0" max="120" data-enter="save-station" data-arg="${key}"`)}</label>
        <div class="buttons">
          <button class="primary" data-action="save-station" data-arg="${key}" ${s.stop_ref ? "" : "disabled"}>${this._t("save")}</button>
          <button data-action="close" data-arg="${key}">${this._t("cancel")}</button>
        </div>
      </div>`;
  }

  _settings() {
    const s = this._data.settings;
    const opts = (list, value, empty) => [["", empty], ...list]
      .map(([v, l]) => `<option value="${esc(v)}" ${v === (value || "") ? "selected" : ""}>${esc(l)}</option>`).join("");
    // One row per setting: label (and hint) left, control right.
    const row = (label, hint, control) => `
      <div class="setting">
        <div class="label">${label}${hint ? `<div class="muted">${hint}</div>` : ""}</div>
        <div class="control">${control}</div>
      </div>`;
    return `
      <section class="card">
        ${row(this._t("tts"), "", `<select data-setting="tts_entity">${opts(this._entities("tts"), s.tts_entity, this._t("none"))}</select>`)}
        ${row(this._t("speaker"), "", `<select data-setting="speaker">${opts(this._entities("media_player"), s.speaker, this._t("none"))}</select>`)}
        ${row(this._t("language"), "", `<select data-setting="language">
          <option value="de" ${s.language === "de" ? "selected" : ""}>${this._t("german")}</option>
          <option value="en" ${s.language === "en" ? "selected" : ""}>${this._t("english")}</option>
        </select>`)}
        ${row(this._t("lead"), this._t("leadHint"), `<input type="number" min="5" max="180" step="5" data-setting="car_lead_minutes" value="${s.car_lead_minutes}"> ${this._t("min")}`)}
        ${row(this._t("testMode"), this._t("testModeHint"), `<input type="checkbox" data-setting="test_mode" ${s.test_mode ? "checked" : ""}>`)}
      </section>
      <p class="muted">${esc(this._t("keysHint"))}</p>`;
  }
}

const STYLE = `
  :host { display: block; background: var(--primary-background-color); color: var(--primary-text-color); min-height: 100vh;
    font-family: var(--paper-font-body1_-_font-family, Roboto, sans-serif); }
  .page { max-width: 960px; margin: 0 auto; padding: 16px; box-sizing: border-box; }
  header { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px; margin-bottom: 16px; }
  h1 { font-size: 24px; font-weight: 400; margin: 0; }
  nav { display: flex; gap: 4px; }
  .tab { background: none; border: none; border-bottom: 2px solid transparent; border-radius: 0; color: var(--secondary-text-color); }
  .tab.on { color: var(--primary-color); border-bottom-color: var(--primary-color); }
  .card { background: var(--card-background-color); border-radius: var(--ha-card-border-radius, 12px);
    box-shadow: var(--ha-card-box-shadow, none); border: 1px solid var(--divider-color); padding: 8px 16px; margin-bottom: 16px; }
  .row { display: flex; align-items: center; gap: 12px; padding: 10px 0; border-bottom: 1px solid var(--divider-color); flex-wrap: wrap; }
  .row:last-of-type { border-bottom: none; }
  .row.active .title { color: var(--primary-color); }
  .sub { margin-left: 24px; }
  .grow { flex: 1; min-width: 180px; }
  .clickable { cursor: pointer; }
  .title { font-weight: 500; }
  .muted { color: var(--secondary-text-color); font-size: 0.9em; }
  .actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
  .run { font-weight: 500; }
  .late { color: var(--error-color); }
  .badge { font-size: 0.75em; padding: 1px 6px; border-radius: 8px; background: var(--primary-color); color: var(--text-primary-color); margin-left: 6px; }
  button { font: inherit; padding: 6px 12px; border-radius: 6px; border: 1px solid var(--divider-color); background: none;
    color: var(--primary-text-color); cursor: pointer; }
  button.primary { background: var(--primary-color); border-color: var(--primary-color); color: var(--text-primary-color); }
  button.ghost { border-color: transparent; color: var(--secondary-text-color); }
  button.danger:hover { color: var(--error-color); }
  button:disabled { opacity: 0.4; cursor: default; }
  button.add { border: none; color: var(--primary-color); padding: 10px 0; display: block; }
  input, select { font: inherit; padding: 6px 8px; border-radius: 6px; border: 1px solid var(--divider-color);
    background: var(--secondary-background-color); color: var(--primary-text-color); box-sizing: border-box; }
  .form { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 12px; padding: 12px 0; }
  .form label { display: flex; flex-direction: column; gap: 4px; font-size: 0.9em; color: var(--secondary-text-color); }
  .form label.check { flex-direction: row; align-items: center; gap: 8px; color: var(--primary-text-color); }
  label.inline { display: inline-flex; align-items: center; gap: 6px; font-size: 0.9em; }
  .wide, .buttons { grid-column: 1 / -1; }
  .lines { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 4px 12px; margin-top: 6px; }
  .buttons { display: flex; gap: 8px; flex-wrap: wrap; }
  .search { display: flex; gap: 8px; }
  .search input { flex: 1; }
  .results { display: flex; flex-direction: column; margin-top: 4px; }
  .result { text-align: left; border: none; border-bottom: 1px solid var(--divider-color); border-radius: 0; }
  .setting { display: flex; align-items: center; justify-content: space-between; gap: 16px; flex-wrap: wrap;
    padding: 12px 0; border-bottom: 1px solid var(--divider-color); }
  .setting:last-child { border-bottom: none; }
  .setting .control { display: flex; align-items: center; gap: 6px; }
  .setting select { min-width: 240px; }
  .setting input[type="number"] { width: 80px; }
  .error { background: var(--error-color); color: #fff; padding: 8px 12px; border-radius: 6px; margin-bottom: 16px; }
  .hint { background: var(--secondary-background-color); padding: 8px 12px; border-radius: 6px; margin-bottom: 16px; font-size: 0.9em; }
`;

customElements.define("andiamo-panel", AndiamoPanel);
