// Andiamo dashboard card: start a route with one tap, or set "arrive by" for a car route.
//
// type: custom:andiamo-card
// title: Leave      (optional)
// mode: car          (optional: car or transit; default all routes)
// routes: [Home → Girlfriend]   (optional: route names or ids)

const T = {
  start: "Start", stop: "Stop", arriveBy: "Arrive by", leaveAt: "Leave at {0}", inMin: "in {0} min",
  running: "Running", noRoutes: "No routes. Add them on the Andiamo page.", delay: "+{0} min",
  badTime: "Enter a time like {0}.", badDate: "Enter a date like {0}.", date: "Date"
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

  static getStubConfig() { return { mode: "car" }; }
  getCardSize() { return 1 + (this._routes()?.length || 1); }

  setConfig(config) {
    this._config = config || {};
    this._render();
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    haLocale = hass.locale;
    if (first) this._subscribe();
  }

  connectedCallback() {
    if (this._hass && !this._unsub) this._subscribe();
    this._tick = setInterval(() => this._render(), 30000);
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
    let s = T[key];
    args.forEach((a, i) => (s = s.replace(`{${i}}`, a)));
    return s;
  }

  _routes() {
    if (!this._data) return null;
    const c = this._config || {};
    return this._data.routes.filter(
      (r) => (!c.mode || r.mode === c.mode) && (!c.routes || c.routes.includes(r.name) || c.routes.includes(r.id)),
    );
  }

  async _act(action, routeId) {
    try {
      this._error = "";
      if (action === "press") await this._hass.callWS({ type: "andiamo/press", route_id: routeId });
      if (action === "cancel") await this._hass.callWS({ type: "andiamo/cancel", route_id: routeId });
      if (action === "start-car") {
        const typed = this._times[routeId];
        if (!typed) return;
        const time = parseTime(typed);
        if (!time) {
          this._error = this._t("badTime", showTime("18:30"));
          this._render();
          return;
        }
        const date = parseDate(this._dates[routeId] ?? "");
        if (!date) {
          this._error = this._t("badDate", showDate(today()));
          this._render();
          return;
        }
        await this._hass.callWS({ type: "andiamo/start_car", route_id: routeId, arrive_at: arriveAt(time, date) });
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
    else if (!routes.length) body = `<p class="muted">${this._t("noRoutes")}</p>`;
    else body = routes.map((r) => this._row(r)).join("");
    this.shadowRoot.innerHTML = `<style>${STYLE}</style><ha-card>${title}<div class="content">
      ${this._error && this._data ? `<div class="error">${esc(this._error)}</div>` : ""}${body}</div></ha-card>`;
    if (active) this.shadowRoot.querySelector(`[data-time="${active}"]`)?.focus();
  }

  _row(r) {
    const run = this._data.runs.find((x) => x.route_id === r.id);
    let right;
    let info = "";
    if (run) {
      const delay = run.delay_minutes ? ` <span class="late">${this._t("delay", run.delay_minutes)}</span>` : "";
      info = `${run.leave_at
        ? `<div class="run">${this._t("leaveAt", clock(run.leave_at))} · ${this._t("inMin", minutesUntil(run.leave_at))}</div>
           ${run.line ? `<div class="muted">${esc(run.line)} ${run.departure ? clock(run.departure) : ""}${delay}</div>` : ""}`
        : `<div class="run">${this._t("running")}</div>`}
        ${run.arrive_at ? `<div class="muted">${this._t("arriveBy")} ${esc(arrival(run.arrive_at))}</div>` : ""}`;
      right = `<button data-action="cancel" data-route="${r.id}">${this._t("stop")}</button>`;
    } else if (r.mode === "transit") {
      right = `<button class="primary" data-action="press" data-route="${r.id}">${this._t("start")}</button>`;
    } else {
      right = `<input type="text" class="time" data-time="${r.id}" value="${esc(this._times[r.id] || "")}" placeholder="${esc(showTime("18:30"))}" aria-label="${this._t("arriveBy")}">
        <input type="text" class="date" data-date="${r.id}" value="${esc(this._dates[r.id] ?? showDate(today()))}" aria-label="${this._t("date")}">
        <button class="primary" data-action="start-car" data-route="${r.id}">${this._t("start")}</button>`;
    }
    return `<div class="row">
      <div class="grow"><div class="name">${r.mode === "car" ? "🚗" : routeIcon(r.lines)} ${esc(r.name)}</div>${info}</div>
      <div class="actions">${right}</div></div>`;
  }
}

const STYLE = `
  h1 { font-size: 20px; font-weight: 400; margin: 0; padding: 16px 16px 0; }
  .content { padding: 8px 16px; }
  .row { display: flex; align-items: center; gap: 8px; padding: 8px 0; border-bottom: 1px solid var(--divider-color); }
  .row:last-child { border-bottom: none; }
  .grow { flex: 1; min-width: 0; }
  .name { font-weight: 500; }
  .run { color: var(--primary-color); font-weight: 500; }
  .late { color: var(--error-color); }
  .muted { color: var(--secondary-text-color); font-size: 0.9em; }
  .actions { display: flex; align-items: center; gap: 6px; }
  button { font: inherit; padding: 6px 12px; border-radius: 6px; border: 1px solid var(--divider-color); background: none;
    color: var(--primary-text-color); cursor: pointer; }
  button.primary { background: var(--primary-color); border-color: var(--primary-color); color: var(--text-primary-color); }
  input.time { width: 70px; }
  input.date { width: 90px; }
  input { font: inherit; padding: 5px 6px; border-radius: 6px; border: 1px solid var(--divider-color);
    background: var(--secondary-background-color); color: var(--primary-text-color); }
  .error { color: var(--error-color); padding: 4px 0; }
`;

customElements.define("andiamo-card", AndiamoCard);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "andiamo-card",
  name: "Andiamo",
  description: "Start a Andiamo route, or set an arrival time for a car route.",
});
