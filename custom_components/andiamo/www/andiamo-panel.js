// Andiamo sidebar panel: places, stations, routes and settings.
// Plain web component, no build step. Edits happen inline, no dialogs.

const T = {
  routes: "Routes", places: "Places", settings: "Settings",
  addRoute: "Add route", addPlace: "Add place", addStation: "Add station",
  name: "Name", from: "From", to: "To", mode: "Mode", transit: "Public transport", car: "Car",
  station: "Station", mainStation: "Main station", speaker: "Speaker",
  lines: "Lines", pickLine: "Pick a line", loadingLines: "Loading lines…", noLines: "No departures found from this station.",
  walk: "Walk (min)", save: "Save", cancel: "Cancel", delete: "Delete", edit: "Edit",
  start: "Start", stop: "Stop", checkHint: "Drive time and traffic right now", arriveBy: "Arrive by", leaveAt: "Leave at {0}", inMin: "in {0}",
  main: "Main", makeMain: "Make main", search: "Search", searchStop: "Search a stop…", searchAddress: "Search an address…",
  latitude: "Latitude", longitude: "Longitude", useHome: "Use HA home",
  tts: "Text-to-speech", language: "Announcement language", none: "None", min: "min",
  lead: "Car countdown starts", leadHint: "Minutes before leaving",
  announceOn: "Announce on", announceHint: "Off: only the sensor and the andiamo_announcement event",
  announce_speaker: "Speaker", announce_notification: "Notification", announce_off: "Off",
  sectionRoute: "Route", sectionAnnounce: "Announcements",
  watch: "Watch", problemAt: "Alert when late by (min)", winFrom: "From", winTo: "Until",
  addWindow: "Add window", removeWindow: "Remove this window",
  boards: "Departure sensors", boardsEvery: "Update every (min)", boardsCount: "Departures listed",
  boardsHint: "On these days and times, the next departure and departures sensors are kept up to date. Each update is one OJP request.",
  usage: "API calls today: {0}", usagePart: "{0}: planned {1}, used {2} / {3}",
  usageHint: "Planned: what today's watch windows and departure sensors cost. Used: the calls Andiamo made since midnight UTC, also for countdowns, checks and searches. Other apps using the same key aren't counted.",
  limitTomtom: "TomTom calls per day", limitOjp: "opentransportdata.swiss calls per day", limitHint: "The free limit; change it for another plan.",
  watchHint: "On these days and times, the problem sensor turns on for traffic jams, delays or cancellations.",
  days: "Mo,Tu,We,Th,Fr,Sa,Su", watching: "Watching",
  problem_traffic: "Traffic jam +{0} min", problem_delayed: "{1} {2} late +{0} min", problem_cancelled: "{1} {2} cancelled",
  noRoutes: "No routes yet.", noStations: "No stations yet.", running: "Running",
  noKeyTransit: "No opentransportdata.swiss key: public transport is off.",
  noKeyCar: "No TomTom key: car routes and address search are off.",
  keysHint: "API keys: Settings → Devices & services → Andiamo → Reconfigure.",
  deleteConfirm: "Delete {0}? Click again to confirm.", delay: "+{0} min",
  german: "German", english: "English", badTime: "Enter a time like {0}.", badDate: "Enter a date like {0}.",
  date: "Date", defaultSpeaker: "Default ({0})", drive: "{0} min drive", traffic: "+{0} min traffic", km: "{0} km",
  messages: "Messages ({0})", messagesHint: "Leave a message empty to use the default. Placeholders:",
  msg_leave_at: "Leave at", msg_changed: "New time", msg_traffic_changed: "Traffic changed",
  msg_minutes_left: "Minutes left", msg_go_now: "Go now", msg_cancelled: "Cancelled", msg_no_connection: "No connection",
  msg_drive_time: "Drive time", msg_drive_time_free: "Drive time, no traffic",
};

// A route's time windows, and what a new one starts with (Monday to Friday).
const WINDOWS = {
  watch_windows: { days: [0, 1, 2, 3, 4], from: "", to: "", problem_minutes: 15 },
  departure_windows: { days: [0, 1, 2, 3, 4], from: "", to: "", every: 2, count: 5 },
};
// Window fields like "watch_windows.0.from" in a draft.
const getPath = (obj, path) => path.split(".").reduce((o, k) => o?.[k], obj);
const setPath = (obj, path, value) => {
  const keys = path.split(".");
  const last = keys.pop();
  keys.reduce((o, k) => o[k], obj)[last] = value;
};
const PLACEHOLDERS = ["time", "minutes", "route", "line", "destination", "departure", "traffic", "km"];
const ANNOUNCE = ["speaker", "notification", "off"];

// OJP PtMode → what search results show next to a stop's name.
const MODES = {
  rail: "Train", intercityRail: "Train", urbanRail: "Train", tram: "Tram", bus: "Bus", trolleyBus: "Bus",
  coach: "Coach", metro: "Metro", underground: "Metro", water: "Boat", telecabin: "Cable car", funicular: "Funicular",
};
const modeNames = (modes) => [...new Set((modes || []).map((m) => MODES[m] || m))].join(", ");

// A route's icon follows its lines: all trams 🚋, all buses 🚌, anything else (trains, mixed) 🚆.
const routeIcon = (lines) => {
  const kinds = new Set((lines || []).map((l) => (l.mode === "tram" ? "tram" : ["bus", "trolleyBus", "coach"].includes(l.mode) ? "bus" : "train")));
  return kinds.size === 1 && kinds.has("tram") ? "🚋" : kinds.size === 1 && kinds.has("bus") ? "🚌" : "🚆";
};

const esc = (v) =>
  String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

// Times follow the user's HA profile (12/24 hours, language or system), not the browser.
let haLocale;
const clock = (iso) => {
  const format = haLocale?.time_format;
  const options = { hour: "2-digit", minute: "2-digit" };
  if (format === "12" || format === "24") options.hourCycle = format === "12" ? "h12" : "h23";
  const language = format === "system" ? undefined : haLocale?.language;
  return new Date(iso).toLocaleTimeString(language, options);
};
const minutesUntil = (iso) => Math.max(0, Math.round((new Date(iso) - Date.now()) / 60000));
// "41 min", from an hour on "1 h 41 min" (or just "2 h").
const shortMinutes = (n) => (n < 60 ? `${n} min` : n % 60 ? `${Math.floor(n / 60)} h ${n % 60} min` : `${n / 60} h`);

// What people type in "Arrive by": "18:30", "1830", "6:30 pm", "6pm" → "18:30"; anything else → null.
const parseTime = (text) => {
  const m = String(text).trim().toLowerCase().match(/^(\d{1,2})(?:[:.h]?(\d{2}))?\s*(am|pm|a|p)?$/);
  if (!m) return null;
  let h = Number(m[1]);
  const min = Number(m[2] || 0);
  if (m[3]) {
    if (h < 1 || h > 12) return null;
    h = (h % 12) + (m[3][0] === "p" ? 12 : 0);
  }
  if (h > 23 || min > 59) return null;
  return `${String(h).padStart(2, "0")}:${String(min).padStart(2, "0")}`;
};
// "18:30" in the user's HA time format.
const showTime = (hhmm) => {
  const [h, m] = hhmm.split(":").map(Number);
  return clock(new Date(2000, 0, 1, h, m).toISOString());
};

// Dates follow the user's HA date format too: day, month and year in its order, with the language's separator.
const pad = (n) => String(n).padStart(2, "0");
const ymdOf = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const today = () => ymdOf(new Date());
const dateParts = () => {
  const format = haLocale?.date_format;
  const language = format === "system" ? undefined : haLocale?.language;
  const parts = new Intl.DateTimeFormat(language, { day: "2-digit", month: "2-digit", year: "numeric" }).formatToParts(new Date(2000, 11, 31));
  const order = ["DMY", "MDY", "YMD"].includes(format)
    ? [...format].map((c) => ({ D: "day", M: "month", Y: "year" })[c])
    : parts.filter((p) => p.type !== "literal").map((p) => p.type);
  const sep = parts.find((p) => p.type === "literal")?.value.trim() || "/";
  return { order, sep };
};
// "2026-10-19" in the user's HA date format.
// A field just wide enough for a time or date in the user's format, plus padding and border.
const fits = (text) => `style="width: calc(${String(text).length + 0.5}ch + 18px)"`;
const showDate = (ymd) => {
  const [year, month, day] = ymd.split("-");
  const value = { year, month, day };
  const { order, sep } = dateParts();
  return order.map((k) => value[k]).join(sep);
};
// What people type in "Date": "19.10", "19.10.26", "19.10.2026", "2026-10-19", "today", "tomorrow" → "2026-10-19"; anything else → null.
const parseDate = (text) => {
  const t = String(text).trim().toLowerCase();
  const now = new Date();
  if (t === "" || t === "today") return today();
  if (t === "tomorrow") return ymdOf(new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1));
  const nums = t.split(/[^0-9]+/).filter(Boolean).map(Number);
  let order = /^\d{4}-/.test(t) ? ["year", "month", "day"] : dateParts().order;
  if (nums.length === 2) order = order.filter((k) => k !== "year");
  if (nums.length !== order.length) return null;
  const v = Object.fromEntries(order.map((k, i) => [k, nums[i]]));
  let year = v.year ?? now.getFullYear();
  if (year < 100) year += 2000;
  let d = new Date(year, v.month - 1, v.day);
  if (d.getMonth() !== v.month - 1 || d.getDate() !== v.day) return null;
  // Without a year, a day that has passed means next year.
  if (v.year === undefined && ymdOf(d) < today()) d = new Date(year + 1, v.month - 1, v.day);
  return ymdOf(d);
};
// "18:30" on "2026-10-19" as ISO; a time already passed today means tomorrow.
const arriveAt = (hhmm, ymd) => {
  const [h, m] = hhmm.split(":").map(Number);
  const [y, mo, d] = ymd.split("-").map(Number);
  const when = new Date(y, mo - 1, d, h, m);
  if (when <= new Date() && ymd === today()) when.setDate(when.getDate() + 1);
  return when.toISOString();
};
// The arrival time, with the date when it isn't today.
const arrival = (iso) => {
  const ymd = ymdOf(new Date(iso));
  return ymd === today() ? clock(iso) : `${showDate(ymd)} ${clock(iso)}`;
};
// "41 min drive · +3 min traffic · 32 km" from the last car trip planned.
const driveText = (trip, t) => {
  if (!trip) return "";
  const km = trip.length_km >= 10 ? Math.round(trip.length_km) : trip.length_km;
  return [t("drive", trip.travel_minutes), trip.traffic_minutes > 0 ? t("traffic", trip.traffic_minutes) : "", t("km", km.toLocaleString(haLocale?.language))]
    .filter(Boolean).join(" · ");
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
    haLocale = hass.locale;
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
      setPath(this._drafts[key], name, el.type === "checkbox" ? el.checked : el.value);
      if (e.type === "change" && el.tagName === "SELECT") this._render();
      // Show a typed time the way HA shows times.
      const time = el.dataset.timefield !== undefined && e.type === "change" && parseTime(el.value);
      if (time) setPath(this._drafts[key], name, (el.value = showTime(time)));
      const date = el.dataset.datefield !== undefined && e.type === "change" && parseDate(el.value);
      if (date) setPath(this._drafts[key], name, (el.value = showDate(date)));
    }
    if (el.dataset.setting && e.type === "change") {
      let value = el.type === "checkbox" ? el.checked : el.value;
      if (el.type === "number") value = Number(value);
      if (value === "") value = null;
      this._ws("settings", { changes: { [el.dataset.setting]: value } });
    }
    if (el.dataset.template && e.type === "change") {
      // Only replaced messages are kept; an empty one goes back to the default.
      const lang = this._data.settings.language;
      const templates = { ...(this._data.settings.templates || {}) };
      const own = { ...(templates[lang] || {}) };
      if (el.value.trim()) own[el.dataset.template] = el.value.trim();
      else delete own[el.dataset.template];
      templates[lang] = own;
      this._ws("settings", { changes: { templates } }).catch(() => {});
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
      case "start": await this._ws("start", { route_id: arg }); return;
      case "check": await this._ws("check", { route_id: arg }); return;
      case "cancel-run": await this._ws("cancel", { route_id: arg }); return;
      case "start-car": {
        const typed = d[`start:${arg}`]?.time;
        if (!typed) return;
        const time = parseTime(typed);
        if (!time) { this._error = this._t("badTime", showTime("18:30")); break; }
        const date = parseDate(d[`start:${arg}`]?.date ?? "");
        if (!date) { this._error = this._t("badDate", showDate(today())); break; }
        await this._ws("start", { route_id: arg, arrive_at: arriveAt(time, date) });
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
      case "toggle-day": {
        const [key, path, day] = arg.split("#");
        const window = getPath(d[key], path);
        const days = new Set(window.days || []);
        days.has(Number(day)) ? days.delete(Number(day)) : days.add(Number(day));
        window.days = [...days].sort();
        break;
      }
      case "add-window": {
        const [key, list] = arg.split("#");
        d[key][list] = [...(d[key][list] || []), structuredClone(WINDOWS[list])];
        break;
      }
      case "remove-window": {
        const [key, path] = arg.split("#");
        const [list, i] = path.split(".");
        d[key][list] = d[key][list].filter((_, j) => j !== Number(i));
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
      if (id !== "new") {
        const r = structuredClone(this._data.routes.find((x) => x.id === id));
        // Window times show the way HA shows times.
        for (const list of Object.keys(WINDOWS)) {
          for (const w of r[list] || []) for (const f of ["from", "to"]) w[f] = w[f] ? showTime(w[f]) : "";
        }
        return r;
      }
      const main = this._data.locations.find((l) => l.main);
      const other = this._data.locations.find((l) => !l.main);
      return { mode: this._data.providers.transit ? "transit" : "car", origin_id: main?.id, destination_id: other?.id, lines: [],
        watch_windows: [], departure_windows: [] };
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
      speaker: r.speaker || null,
      announce: r.announce || null,
    };
    for (const list of Object.keys(WINDOWS)) {
      item[list] = [];
      if (list === "departure_windows" && !transit) continue;
      for (const w of r[list] || []) {
        const window = { ...w };
        for (const f of ["from", "to"]) {
          const typed = (w[f] || "").trim();
          window[f] = typed ? parseTime(typed) : null;
          if (typed && !window[f]) { this._error = this._t("badTime", showTime("06:30")); return; }
        }
        for (const f of ["problem_minutes", "every", "count"]) if (f in w) window[f] = Number(w[f] || WINDOWS[list][f]);
        item[list].push(window);
      }
    }
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
        ${this._usage()}
        ${this._error ? `<div class="error">${esc(this._error)}</div>` : ""}
        ${this._warnings()}
        ${body}
      </div>`;
  }

  // "TomTom: planned 120, used 45 / 2,500" with a bar each, so the free limits stay in sight.
  _usage() {
    const u = this._data.usage;
    if (!u) return "";
    const num = (n) => Number(n).toLocaleString(haLocale?.language);
    const part = (name, { calls, planned, limit }) => {
      // The bar fills with what's used; the rest of the plan shows lighter behind it.
      const used = Math.min(1, calls / limit);
      const plan = Math.min(1, Math.max(calls, planned) / limit);
      return `<span class="usage-part">${this._t("usagePart", name, num(planned), num(calls), num(limit))}
        <span class="bar"><span class="plan" style="width: ${Math.round(plan * 100)}%"></span><span class="${plan >= 0.8 ? "high" : ""}" style="width: ${Math.round(used * 100)}%"></span></span></span>`;
    };
    return `<div class="usage muted" title="${esc(this._t("usageHint"))}">${this._t("usage",
      `${part("TomTom", u.tomtom)} · ${part("OJP", u.ojp)}`)}</div>`;
  }

  _warnings() {
    const p = this._data.providers;
    const w = [];
    if (!p.transit) w.push(this._t("noKeyTransit"));
    if (!p.car) w.push(this._t("noKeyCar"));
    return w.length ? `<div class="hint">${w.map(esc).join("<br>")}<br>${esc(this._t("keysHint"))}</div>` : "";
  }

  _input(key, name, attrs = "") {
    const v = getPath(this._drafts[key], name) ?? "";
    return `<input data-draft="${key}|${name}" value="${esc(v)}" ${attrs}>`;
  }

  _select(key, name, options, attrs = "") {
    const v = getPath(this._drafts[key], name) ?? "";
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
    const icon = r.mode === "car" ? "🚗" : routeIcon(r.lines);
    let where;
    if (r.mode === "transit") {
      const s = this._routeStation(r);
      const lines = (r.lines || []).map((l) => `${l.name} → ${l.destination}`).join(", ");
      where = `${esc(from)}${s ? ` · ${esc(s.name)}` : ""} · ${lines ? esc(lines) : `<span class="late">${this._t("pickLine")}</span>`}`;
    } else {
      // The name already says where; show how long the drive is instead.
      where = esc(driveText(this._data.trips?.[r.id], (k, v) => this._t(k, v)));
    }
    // Car routes: check the drive time now, right before Start or Stop.
    const check = r.mode === "car"
      ? `<button class="icon" data-action="check" data-arg="${r.id}" title="${this._t("checkHint")}" aria-label="${this._t("checkHint")}" ${this._data.providers.car ? "" : "disabled"}><ha-icon icon="mdi:car-clock"></ha-icon></button>`
      : "";
    let action;
    if (run) {
      const delay = run.delay_minutes ? ` <span class="late">${this._t("delay", run.delay_minutes)}</span>` : "";
      const line = run.line ? ` · ${esc(run.line)} ${run.departure ? clock(run.departure) : ""}${delay}`
        : run.arrive_at ? ` · ${this._t("arriveBy")} ${esc(arrival(run.arrive_at))}` : "";
      action = `<span class="run">${run.leave_at ? `${this._t("inMin", shortMinutes(minutesUntil(run.leave_at)))} · ${this._t("leaveAt", clock(run.leave_at))}` : this._t("running")}${line}</span>
        ${check}<button data-action="cancel-run" data-arg="${r.id}">${this._t("stop")}</button>`;
    } else if (r.mode === "transit") {
      action = `<button class="primary" data-action="start" data-arg="${r.id}" ${this._data.providers.transit && r.lines?.length ? "" : "disabled"}>${this._t("start")}</button>`;
    } else {
      const key = `start:${r.id}`;
      const date = this._drafts[key]?.date ?? showDate(today());
      action = `<label class="inline">${this._t("arriveBy")} ${this._input(key, "time", `type="text" class="time" data-timefield placeholder="${esc(showTime("18:30"))}" ${fits(showTime("18:30"))} data-enter="start-car" data-arg="${r.id}"`)}</label>
        <input data-draft="${key}|date" value="${esc(date)}" type="text" class="date" ${fits(showDate(today()))} data-datefield data-enter="start-car" data-arg="${r.id}" aria-label="${this._t("date")}">
        ${check}<button class="primary" data-action="start-car" data-arg="${r.id}" ${this._data.providers.car ? "" : "disabled"}>${this._t("start")}</button>`;
    }
    const problem = this._data.problems?.[r.id];
    const watch = problem ? `<div class="late">⚠ ${esc(this._problemText(problem))}</div>`
      : this._data.watching?.includes(r.id) ? `<div class="muted">👁 ${this._t("watching")}</div>` : "";
    return `
      <div class="row ${run ? "active" : ""}">
        <div class="grow clickable" data-action="open" data-arg="route:${r.id}" title="${this._t("edit")}">
          <div class="title">${icon} ${esc(r.name)}</div>
          ${where ? `<div class="muted">${where}</div>` : ""}
          ${watch}
        </div>
        <div class="actions">${action}${this._deleteBtn(`route:${r.id}`, r.name)}</div>
      </div>`;
  }

  _routeForm(key) {
    const r = this._drafts[key];
    const transit = r.mode === "transit";
    const places = this._data.locations.map((l) => [l.id, l.name]);
    const modes = [["transit", this._t("transit")], ["car", this._t("car")]];
    let where;
    if (transit) {
      const stations = [["", this._t("mainStation")], ...this._stationsOf(r.origin_id).map((s) => [s.id, `${s.name} (${s.walk_minutes}′)`])];
      where = `
        <label>${this._t("station")} ${this._select(key, "station_id", stations)}</label>
        <div class="wide"><div class="muted">${this._t("lines")}</div>${this._lineChecks(key)}</div>`;
    } else {
      where = `<label>${this._t("to")} ${this._select(key, "destination_id", places)}</label>`;
    }
    const settings = this._data.settings.speaker;
    const fallback = settings ? this._hass.states[settings]?.attributes.friendly_name || settings : this._t("none");
    const speakers = [["", this._t("defaultSpeaker", fallback)], ...this._entities("media_player")];
    const announceDefault = this._t(`announce_${this._data.settings.announce || "speaker"}`);
    const number = (path, label, min, max) => `<label>${this._t(label)} ${this._input(key, path, `type="number" min="${min}" max="${max}"`)}</label>`;
    const ready = !transit || r.lines?.length;
    return `
      <div class="form route">
        ${this._group(this._t("sectionRoute"), "", `<div class="fields">
          <label>${this._t("name")} ${this._input(key, "name", `placeholder="${esc(this._routeName(r))}" data-enter="save-route" data-arg="${key}"`)}</label>
          <label>${this._t("mode")} ${this._select(key, "mode", modes)}</label>
          <label>${this._t("from")} ${this._select(key, "origin_id", places)}</label>
          ${where}</div>`)}
        ${this._group(this._t("sectionAnnounce"), "", `<div class="fields">
          <label>${this._t("speaker")} ${this._select(key, "speaker", speakers)}</label>
          <label>${this._t("announceOn")} ${this._select(key, "announce",
            [["", this._t("defaultSpeaker", announceDefault)], ...ANNOUNCE.map((a) => [a, this._t(`announce_${a}`)])])}</label></div>`)}
        ${this._group(this._t("watch"), this._t("watchHint"),
          this._windows(key, "watch_windows", (p) => number(`${p}.problem_minutes`, "problemAt", 1, 180)))}
        ${transit ? this._group(this._t("boards"), this._t("boardsHint"),
          this._windows(key, "departure_windows", (p) => number(`${p}.every`, "boardsEvery", 1, 60) + number(`${p}.count`, "boardsCount", 1, 20))) : ""}
        <div class="buttons">
          <button class="primary" data-action="save-route" data-arg="${key}" ${ready ? "" : "disabled"}>${this._t("save")}</button>
          <button data-action="close" data-arg="${key}">${this._t("cancel")}</button>
        </div>
      </div>`;
  }

  _group(title, hint, body) {
    return `<div class="group"><div class="group-title">${title}</div>${hint ? `<div class="muted">${hint}</div>` : ""}${body}</div>`;
  }

  // A route's time windows (watch or departure sensors): days, from, until, plus the window's own settings.
  _windows(key, list, extra) {
    const placeholder = (t) => `type="text" class="time" data-timefield placeholder="${esc(showTime(t))}"`;
    const names = this._t("days").split(",");
    const rows = (this._drafts[key][list] || []).map((w, i) => {
      const path = `${list}.${i}`;
      const days = new Set(w.days || []);
      const checks = names.map((name, d) => `
        <label class="check"><input type="checkbox" data-action="toggle-day" data-arg="${esc(key)}#${path}#${d}" ${days.has(d) ? "checked" : ""}> ${name}</label>`).join("");
      return `<div class="window">
        <div class="days">${checks}</div>
        <label>${this._t("winFrom")} ${this._input(key, `${path}.from`, placeholder("06:30"))}</label>
        <label>${this._t("winTo")} ${this._input(key, `${path}.to`, placeholder("08:00"))}</label>
        ${extra(path)}
        <button class="ghost danger" data-action="remove-window" data-arg="${esc(key)}#${path}" title="${this._t("removeWindow")}" aria-label="${this._t("removeWindow")}">✕</button>
      </div>`;
    }).join("");
    return `${rows}<button class="add" data-action="add-window" data-arg="${esc(key)}#${list}">+ ${this._t("addWindow")}</button>`;
  }

  _problemText(p) {
    return this._t(`problem_${p.reason}`, p.delay_minutes, p.line || "", p.departure ? clock(p.departure) : "");
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
      (r, i) => `<button class="result" data-action="${kind === "stop" ? "pick-stop" : "pick-place"}" data-arg="${key}#${i}">${esc(r.name)}${r.modes?.length ? ` <span class="muted">· ${esc(modeNames(r.modes))}</span>` : ""}</button>`,
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
        ${row(this._t("announceOn"), this._t("announceHint"), `<select data-setting="announce">${ANNOUNCE
          .map((a) => `<option value="${a}" ${a === s.announce ? "selected" : ""}>${this._t(`announce_${a}`)}</option>`).join("")}</select>`)}
        ${row(this._t("limitTomtom"), this._t("limitHint"), `<input type="number" min="1" step="100" data-setting="limit_tomtom" value="${s.limit_tomtom}">`)}
        ${row(this._t("limitOjp"), this._t("limitHint"), `<input type="number" min="1" step="100" data-setting="limit_ojp" value="${s.limit_ojp}">`)}
      </section>
      ${this._messages(row)}
      <p class="muted">${esc(this._t("keysHint"))}</p>`;
  }

  _messages(row) {
    const lang = this._data.settings.language;
    const own = this._data.settings.templates?.[lang] || {};
    const defaults = this._data.messages?.[lang] || {};
    const rows = Object.keys(defaults).map((key) => row(this._t(`msg_${key}`), "",
      `<input type="text" class="message" data-template="${key}" value="${esc(own[key] || "")}" placeholder="${esc(defaults[key])}">`)).join("");
    const placeholders = PLACEHOLDERS.map((p) => `<code>{${p}}</code>`).join(" ");
    return `
      <section class="card messages">
        <div class="title">${esc(this._t("messages", this._t(lang === "en" ? "english" : "german")))}</div>
        ${rows}
        <p class="muted">${esc(this._t("messagesHint"))} ${placeholders}</p>
      </section>`;
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
  .usage { margin: -8px 0 12px; display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }
  .usage-part { display: inline-flex; gap: 6px; align-items: center; }
  .usage .bar { position: relative; display: inline-block; width: 60px; height: 6px; border-radius: 3px; background: var(--divider-color); overflow: hidden; }
  .usage .bar > span { position: absolute; left: 0; top: 0; height: 100%; background: var(--primary-color); }
  .usage .bar > span.plan { opacity: 0.35; }
  .usage .bar > span.high { background: var(--error-color); }
  button.icon { display: inline-flex; align-items: center; align-self: stretch; padding: 0 8px; --mdc-icon-size: 20px; }
  button.add { border: none; color: var(--primary-color); padding: 10px 0; display: block; }
  input, select { font: inherit; padding: 6px 8px; border-radius: 6px; border: 1px solid var(--divider-color);
    background: var(--secondary-background-color); color: var(--primary-text-color); box-sizing: border-box; }
  /* An open form is framed, so the next row clearly isn't part of it. */
  .form { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 12px; padding: 12px 16px; margin: 8px 0 12px;
    border: 1px solid var(--primary-color); border-radius: 8px; }
  .form.route { display: block; padding-top: 0; }
  .group { padding: 12px 0; border-bottom: 1px solid var(--divider-color); }
  .group-title { font-weight: 500; margin-bottom: 6px; }
  .group .fields { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 12px; }
  .form.route .buttons { padding-top: 12px; }
  .window { display: flex; flex-wrap: wrap; align-items: flex-end; gap: 8px 16px; padding: 8px 0; border-bottom: 1px dashed var(--divider-color); }
  .window .days { margin: 0; align-self: center; gap: 4px 10px; }
  .window input[type="number"] { width: 80px; }
  .form label { display: flex; flex-direction: column; gap: 4px; font-size: 0.9em; color: var(--secondary-text-color); }
  .form label.check { flex-direction: row; align-items: center; gap: 8px; color: var(--primary-text-color); }
  label.inline { display: inline-flex; align-items: center; gap: 6px; font-size: 0.9em; }
  .wide, .buttons { grid-column: 1 / -1; }
  .lines { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 4px 12px; margin-top: 6px; }
  .buttons { display: flex; gap: 8px; flex-wrap: wrap; }
  .days { display: flex; gap: 4px 14px; flex-wrap: wrap; margin: 6px 0; }
  .search { display: flex; gap: 8px; }
  .search input { flex: 1; }
  .results { display: flex; flex-direction: column; margin-top: 4px; }
  .result { text-align: left; border: none; border-bottom: 1px solid var(--divider-color); border-radius: 0; }
  .setting { display: flex; align-items: center; justify-content: space-between; gap: 16px; flex-wrap: wrap;
    padding: 12px 0; border-bottom: 1px solid var(--divider-color); }
  .setting:last-child { border-bottom: none; }
  .setting .control { display: flex; align-items: center; gap: 6px; }
  .setting select { min-width: 240px; }
  input.time { width: 90px; }
  input.date { width: 100px; }
  .setting input[type="number"] { width: 80px; }
  .setting .control:has(.message) { flex: 1; min-width: 240px; }
  .setting input.message { width: 100%; }
  .messages .setting .label { width: 120px; flex: none; }
  .error { background: var(--error-color); color: #fff; padding: 8px 12px; border-radius: 6px; margin-bottom: 16px; }
  .hint { background: var(--secondary-background-color); padding: 8px 12px; border-radius: 6px; margin-bottom: 16px; font-size: 0.9em; }
`;

customElements.define("andiamo-panel", AndiamoPanel);
