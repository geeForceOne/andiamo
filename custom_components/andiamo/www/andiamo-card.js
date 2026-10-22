// Andiamo dashboard card: start a route with one tap, or set "arrive by" for a car route.
// Or, with view: timetable, the next departures of public transport routes.
// Set it up in the card editor, or in YAML:
//
// type: custom:andiamo-card
// title: Leave      (optional)
// view: routes       (optional: routes or timetable; default routes)
// mode: car          (optional, routes view: car or transit; default all routes)
// routes: [Home → Girlfriend]   (optional: route names or ids)
// show_date: false   (optional, routes view: hide the date next to "Arrive by"; default true)
// departures: 5      (optional, timetable: departures per route, 1–20)
// refresh: 60        (optional, timetable: seconds between updates, 30–300)

const T = {
  start: "Start", stop: "Stop", checkHint: "Drive time and traffic right now", arriveBy: "Arrive by", leaveAt: "Leave at {0}", inMin: "in {0}",
  running: "Running", noRoutes: "No routes. Add them on the Andiamo page.", delay: "+{0} min",
  badTime: "Enter a time like {0}.", badDate: "Enter a date like {0}.", date: "Date",
  leaveIn: "leave in {0}", leaveNow: "leave now", cancelled: "cancelled", walk: "{0} min walk",
  noDepartures: "No departures soon.", noTransit: "No public transport routes. Add them on the Andiamo page.",
  drive: "{0} min drive", traffic: "+{0} min traffic", reserve: "+{0} min reserve", km: "{0} km",
  problem_traffic: "Traffic jam +{0} min", problem_delayed: "{1} {2} late +{0} min", problem_cancelled: "{1} {2} cancelled",
};

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
const showDate = (ymd) => {
  const [year, month, day] = ymd.split("-");
  const value = { year, month, day };
  const { order, sep } = dateParts();
  return order.map((k) => value[k]).join(sep);
};
// A field just wide enough for a time or date in the user's format, plus padding and border.
const fits = (text) => `style="width: calc(${String(text).length + 0.5}ch + 14px)"`;
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

// "41 min drive · +3 min traffic · 32 km" from the last car trip planned or checked.
const driveText = (trip, t, reserve = 0) => {
  if (!trip) return "";
  const km = trip.length_km >= 10 ? Math.round(trip.length_km) : trip.length_km;
  return [t("drive", trip.travel_minutes), trip.traffic_minutes > 0 ? t("traffic", trip.traffic_minutes) : "",
    reserve > 0 ? t("reserve", reserve) : "", t("km", km.toLocaleString(haLocale?.language))]
    .filter(Boolean).join(" · ");
};
// Minutes a car route plans on top of the drive time: its own, else the setting.
const reserveOf = (route, settings) => route.reserve_minutes ?? settings?.car_reserve_minutes ?? 0;

const DEFAULTS = { view: "routes", show_date: true, departures: 5, refresh: 60 };

class AndiamoCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._times = {};
    this._dates = {};
    this.shadowRoot.addEventListener("click", (e) => {
      const el = e.target.closest("[data-action]");
      if (el) this._act(el.dataset.action, el.dataset.route);
    });
    this.shadowRoot.addEventListener("input", (e) => {
      if (e.target.dataset.time) this._times[e.target.dataset.time] = e.target.value;
      if (e.target.dataset.date) this._dates[e.target.dataset.date] = e.target.value;
    });
    // Show a typed time or date the way HA shows them.
    this.shadowRoot.addEventListener("change", (e) => {
      const time = e.target.dataset.time && parseTime(e.target.value);
      if (time) e.target.value = this._times[e.target.dataset.time] = showTime(time);
      const date = e.target.dataset.date && parseDate(e.target.value);
      if (date) e.target.value = this._dates[e.target.dataset.date] = showDate(date);
    });
    this.shadowRoot.addEventListener("keydown", (e) => {
      const routeId = e.target.dataset.time || e.target.dataset.date;
      if (e.key === "Enter" && routeId) this._act("start-car", routeId);
    });
  }

  static getConfigElement() { return document.createElement("andiamo-card-editor"); }
  static getStubConfig() { return { mode: "car" }; }
  getCardSize() {
    if (this._timetable) return 1 + (this._boards?.length || 1) * (1 + Number(this._config.departures));
    return 1 + (this._routes()?.length || 1);
  }

  setConfig(config) {
    this._config = { ...DEFAULTS, ...(config || {}) };
    this._syncTimetable();
    this._render();
  }

  get _timetable() { return this._config?.view === "timetable"; }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    haLocale = hass.locale;
    if (first) this._subscribe();
  }

  connectedCallback() {
    if (this._hass && !this._unsub) this._subscribe();
    this._syncTimetable();
    this._tick = setInterval(() => this._render(), 15000);
  }

  disconnectedCallback() {
    clearInterval(this._tick);
    if (this._unsub) this._unsub.then((u) => u());
    this._unsub = null;
    this._stopTimetable();
  }

  _subscribe() {
    this._unsub = this._hass.connection.subscribeMessage(
      (data) => { this._data = data; this._syncTimetable(); this._render(); },
      { type: "andiamo/subscribe" },
    );
    this._unsub.catch((err) => { this._error = err.message; this._render(); });
  }

  // The departure boards come from their own subscription, open only while the card shows them.
  _syncTimetable() {
    if (!this._timetable || !this._data || !this._hass || !this.isConnected) {
      this._stopTimetable();
      return;
    }
    const msg = {
      type: "andiamo/timetable",
      route_ids: this._routes().map((r) => r.id),
      count: Number(this._config.departures),
      refresh: Number(this._config.refresh),
    };
    const key = JSON.stringify(msg);
    if (key === this._ttKey) return;
    this._stopTimetable();
    this._ttKey = key;
    this._boards = null;
    this._ttUnsub = this._hass.connection.subscribeMessage(
      (data) => { this._boards = data.boards; this._render(); },
      msg,
    );
    this._ttUnsub.catch((err) => { this._error = err.message; this._render(); });
  }

  _stopTimetable() {
    if (this._ttUnsub) this._ttUnsub.then((u) => u()).catch(() => {});
    this._ttUnsub = null;
    this._ttKey = null;
  }

  _t(key, ...args) {
    let s = T[key];
    args.forEach((a, i) => (s = s.replace(`{${i}}`, a)));
    return s;
  }

  _routes() {
    if (!this._data) return null;
    const c = this._config || {};
    const mode = this._timetable ? "transit" : c.mode;
    return this._data.routes.filter(
      (r) => (!mode || r.mode === mode) && (!c.routes?.length || c.routes.includes(r.name) || c.routes.includes(r.id)),
    );
  }

  async _act(action, routeId) {
    try {
      this._error = "";
      if (action === "start") await this._hass.callWS({ type: "andiamo/start", route_id: routeId });
      if (action === "cancel") await this._hass.callWS({ type: "andiamo/cancel", route_id: routeId });
      if (action === "check") await this._hass.callWS({ type: "andiamo/check", route_id: routeId });
      if (action === "start-car") {
        const typed = this._times[routeId];
        if (!typed) return;
        const time = parseTime(typed);
        if (!time) {
          this._error = this._t("badTime", showTime("18:30"));
          this._render();
          return;
        }
        // Without the date field it's today, or tomorrow once the time has passed.
        const date = this._config.show_date ? parseDate(this._dates[routeId] ?? "") : today();
        if (!date) {
          this._error = this._t("badDate", showDate(today()));
          this._render();
          return;
        }
        await this._hass.callWS({ type: "andiamo/start", route_id: routeId, arrive_at: arriveAt(time, date) });
        delete this._times[routeId];
        delete this._dates[routeId];
      }
    } catch (err) {
      this._error = err.message || String(err);
      this._render();
    }
  }

  _render() {
    if (!this._config) return;
    const active = this.shadowRoot.activeElement?.dataset?.time;
    const routes = this._routes();
    const title = this._config.title ? `<h1>${esc(this._config.title)}</h1>` : "";
    let body;
    if (this._error && !this._data) body = `<p class="muted">${esc(this._error)}</p>`;
    else if (!routes) body = `<p class="muted">…</p>`;
    else if (!routes.length) body = `<p class="muted">${this._t(this._timetable ? "noTransit" : "noRoutes")}</p>`;
    else if (this._timetable) body = this._boards ? this._boards.map((b) => this._board(b)).join("") : `<p class="muted">…</p>`;
    else body = routes.map((r) => this._row(r)).join("");
    this.shadowRoot.innerHTML = `<style>${STYLE}</style><ha-card>${title}<div class="content">
      ${this._error && this._data ? `<div class="error">${esc(this._error)}</div>` : ""}${body}</div></ha-card>`;
    if (active) this.shadowRoot.querySelector(`[data-time="${active}"]`)?.focus();
  }

  _row(r) {
    const run = this._data.runs.find((x) => x.route_id === r.id);
    // Car routes: check the drive time now, right before Start or Stop.
    const check = r.mode === "car"
      ? `<button class="icon" data-action="check" data-route="${r.id}" title="${this._t("checkHint")}" aria-label="${this._t("checkHint")}"><ha-icon icon="mdi:car-clock"></ha-icon></button>`
      : "";
    let right;
    let info = "";
    if (run) {
      const delay = run.delay_minutes ? ` <span class="late">${this._t("delay", run.delay_minutes)}</span>` : "";
      info = `${run.leave_at
        ? `<div class="run">${this._t("inMin", shortMinutes(minutesUntil(run.leave_at)))} · ${this._t("leaveAt", clock(run.leave_at))}</div>
           ${run.line ? `<div class="muted">${esc(run.line)} ${run.departure ? clock(run.departure) : ""}${delay}</div>` : ""}`
        : `<div class="run">${this._t("running")}</div>`}
        ${run.arrive_at ? `<div class="muted">${this._t("arriveBy")} ${esc(arrival(run.arrive_at))}</div>` : ""}`;
      right = `${check}<button data-action="cancel" data-route="${r.id}">${this._t("stop")}</button>`;
    } else if (r.mode === "transit") {
      right = `<button class="primary" data-action="start" data-route="${r.id}">${this._t("start")}</button>`;
    } else {
      const date = this._config.show_date
        ? `<input type="text" class="date" data-date="${r.id}" value="${esc(this._dates[r.id] ?? showDate(today()))}" ${fits(showDate(today()))} aria-label="${this._t("date")}">`
        : "";
      right = `<input type="text" class="time" data-time="${r.id}" value="${esc(this._times[r.id] || "")}" placeholder="${esc(showTime("18:30"))}" ${fits(showTime("18:30"))} aria-label="${this._t("arriveBy")}">
        ${date}${check}<button class="primary" data-action="start-car" data-route="${r.id}">${this._t("start")}</button>`;
    }
    if (r.mode === "car") {
      const drive = driveText(this._data.trips?.[r.id], (k, v) => this._t(k, v), reserveOf(r, this._data.settings));
      if (drive && !run) info = `<div class="muted">${esc(drive)}</div>`;
    }
    const p = this._data.problems?.[r.id];
    const problem = p ? `<div class="late">⚠ ${esc(this._t(`problem_${p.reason}`, p.delay_minutes, p.line || "", p.departure ? clock(p.departure) : ""))}</div>` : "";
    return `<div class="row">
      <div class="grow"><div class="name">${r.mode === "car" ? "🚗" : routeIcon(r.lines)} ${esc(r.name)}</div>${problem}${info}</div>
      <div class="actions">${right}</div></div>`;
  }

  // One route's next departures; the ones whose leave time has passed drop out between refreshes.
  _board(b) {
    const route = this._data.routes.find((r) => r.id === b.route_id);
    const where = b.station ? `${esc(b.station)}${b.walk_minutes ? ` · ${this._t("walk", b.walk_minutes)}` : ""}` : "";
    const now = Date.now();
    const departures = (b.departures || []).filter((d) => new Date(d.leave_at) >= now - 30000).slice(0, Number(this._config.departures));
    let list;
    if (b.error && !b.departures) list = `<div class="muted">${esc(b.error)}</div>`;
    else if (!departures.length) list = `<div class="muted">${this._t("noDepartures")}</div>`;
    else list = departures.map((d) => {
      const left = minutesUntil(d.leave_at);
      const late = d.cancelled ? ` <span class="late">${this._t("cancelled")}</span>`
        : d.delay_minutes > 0 ? ` <span class="late">${this._t("delay", d.delay_minutes)}</span>` : "";
      const leave = d.cancelled ? "" : left ? this._t("leaveIn", shortMinutes(left)) : this._t("leaveNow");
      return `<div class="dep ${d.cancelled ? "gone" : ""}">
        <span class="line">${esc(d.line)}</span>
        <span class="grow dest">${esc(d.destination)}</span>
        <span class="time">${clock(d.departure)}${late}</span>
        <span class="leave run">${leave}</span>
      </div>`;
    }).join("");
    return `<div class="board">
      <div class="name">${routeIcon(route?.lines)} ${esc(b.name)}</div>
      ${where ? `<div class="muted">${where}</div>` : ""}${list}</div>`;
  }
}

// The card editor: HA's own form, so nobody needs YAML.
class AndiamoCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = config || {};
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    if (this._form) this._form.hass = hass;
    if (!this._routes && !this._loading) this._load();
  }

  // The route list once, for the route picker.
  // The first event can arrive before the subscription's promise resolves, so unsubscribe through the promise.
  async _load() {
    this._loading = true;
    try {
      const sub = this._hass.connection.subscribeMessage(
        (data) => {
          if (this._routes) return;
          this._routes = data.routes;
          this._render();
          sub.then((unsub) => unsub()).catch(() => {});
        },
        { type: "andiamo/subscribe" },
      );
      await sub;
    } catch (err) {
      this._routes = [];
      this._render();
    }
  }

  _schema(c) {
    const timetable = c.view === "timetable";
    const mode = timetable ? "transit" : c.mode;
    const routes = (this._routes || []).filter((r) => !mode || r.mode === mode).map((r) => ({ value: r.id, label: r.name }));
    return [
      { name: "title", selector: { text: {} } },
      { name: "view", selector: { select: { mode: "dropdown", options: [
        { value: "routes", label: "Routes (start and stop)" }, { value: "timetable", label: "Timetable (public transport)" }] } } },
      ...(timetable ? [] : [{ name: "mode", selector: { select: { mode: "dropdown", options: [
        { value: "", label: "All" }, { value: "transit", label: "Public transport" }, { value: "car", label: "Car" }] } } }]),
      { name: "routes", selector: { select: { multiple: true, options: routes } } },
      ...(timetable
        ? [
          { name: "departures", selector: { number: { min: 1, max: 20, mode: "box" } } },
          { name: "refresh", selector: { number: { min: 30, max: 300, step: 30, mode: "slider", unit_of_measurement: "s" } } },
        ]
        : [{ name: "show_date", selector: { boolean: {} } }]),
    ];
  }

  _render() {
    if (!this._config) return;
    if (!this._form) {
      this._form = document.createElement("ha-form");
      this._form.computeLabel = (s) => LABELS[s.name];
      this._form.computeHelper = (s) => HELPERS[s.name];
      this._form.addEventListener("value-changed", (e) => this._changed(e.detail.value));
      this.appendChild(this._form);
    }
    const c = { ...DEFAULTS, mode: "", ...this._config };
    // Routes set by name in YAML show up picked too.
    c.routes = (c.routes || []).map((v) => this._routes?.find((r) => r.name === v)?.id || v);
    this._form.hass = this._hass;
    this._form.schema = this._schema(c);
    this._form.data = c;
  }

  _changed(value) {
    const config = { ...this._config, ...value };
    // Leave out what's the default, so the YAML stays short.
    for (const [key, v] of Object.entries(config)) {
      if (v === "" || v === undefined || (Array.isArray(v) && !v.length) || DEFAULTS[key] === v) delete config[key];
    }
    if (config.view === "timetable") { delete config.mode; delete config.show_date; }
    else { delete config.departures; delete config.refresh; }
    this._config = config;
    this._render();
    this.dispatchEvent(new CustomEvent("config-changed", { detail: { config }, bubbles: true, composed: true }));
  }
}

const LABELS = {
  title: "Title", view: "Show", mode: "Routes of type", routes: "Routes", show_date: "Show the date next to \"Arrive by\"",
  departures: "Departures per route", refresh: "Refresh every",
};
const HELPERS = {
  routes: "None picked: all of them.",
  show_date: "Off: today, or tomorrow once the time has passed.",
};

const STYLE = `
  h1 { font-size: 20px; font-weight: 400; margin: 0; padding: 16px 16px 0; }
  .content { padding: 8px 16px; }
  /* In a narrow column the buttons and fields move under the name instead of squeezing it. */
  .row { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; padding: 8px 0; border-bottom: 1px solid var(--divider-color); }
  .row:last-child { border-bottom: none; }
  .grow { flex: 1; min-width: 0; }
  .row > .grow { flex: 1 1 9em; }
  .name { font-weight: 500; }
  .run { color: var(--primary-color); font-weight: 500; }
  .late { color: var(--error-color); }
  .muted { color: var(--secondary-text-color); font-size: 0.9em; }
  .actions { display: flex; flex-wrap: wrap; justify-content: flex-end; align-items: center; gap: 6px; margin-left: auto; }
  button { font: inherit; padding: 6px 12px; border-radius: 6px; border: 1px solid var(--divider-color); background: none;
    color: var(--primary-text-color); cursor: pointer; }
  button.icon { display: inline-flex; align-items: center; align-self: stretch; padding: 0 8px; --mdc-icon-size: 20px; }
  button.primary { background: var(--primary-color); border-color: var(--primary-color); color: var(--text-primary-color); }
  input.time { width: 70px; }
  input.date { width: 90px; }
  input { box-sizing: border-box; font: inherit; padding: 5px 6px; border-radius: 6px; border: 1px solid var(--divider-color);
    background: var(--secondary-background-color); color: var(--primary-text-color); }
  .error { color: var(--error-color); padding: 4px 0; }
  .board { padding: 8px 0; border-bottom: 1px solid var(--divider-color); }
  .board:last-child { border-bottom: none; }
  .board .name { margin-bottom: 2px; }
  .dep { display: flex; align-items: baseline; gap: 8px; padding: 4px 0; }
  .dep .line { min-width: 2.5em; padding: 0 6px; border-radius: 4px; text-align: center; font-weight: 500;
    background: var(--secondary-background-color); }
  .dep .dest { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .dep .time, .dep .leave { white-space: nowrap; }
  .dep .leave { min-width: 7.5em; text-align: right; }
  .dep.gone .dest, .dep.gone .time { text-decoration: line-through; color: var(--secondary-text-color); }
`;

customElements.define("andiamo-card", AndiamoCard);
customElements.define("andiamo-card-editor", AndiamoCardEditor);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "andiamo-card",
  name: "Andiamo",
  description: "Start an Andiamo route, set an arrival time for a car route, or show the next departures.",
});
