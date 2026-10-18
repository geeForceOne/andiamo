// Andiamo dashboard card: start a route with one tap, or set "arrive by" for a car route.
//
// type: custom:andiamo-card
// title: Leave      (optional)
// mode: car          (optional: car or transit; default all routes)
// routes: [Home → Girlfriend]   (optional: route names or ids)

const T = {
  start: "Start", stop: "Stop", arriveBy: "Arrive by", leaveAt: "Leave at {0}", inMin: "in {0} min",
  running: "Running", noRoutes: "No routes. Add them on the Andiamo page.", delay: "+{0} min"
};

const esc = (v) =>
  String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const clock = (iso) => new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
const minutesUntil = (iso) => Math.max(0, Math.round((new Date(iso) - Date.now()) / 60000));
const nextTime = (hhmm) => {
  const [h, m] = hhmm.split(":").map(Number);
  const d = new Date();
  d.setHours(h, m, 0, 0);
  if (d <= new Date()) d.setDate(d.getDate() + 1);
  return d.toISOString();
};

class AndiamoCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._times = {};
    this.shadowRoot.addEventListener("click", (e) => {
      const el = e.target.closest("[data-action]");
      if (el) this._act(el.dataset.action, el.dataset.route);
    });
    this.shadowRoot.addEventListener("input", (e) => {
      if (e.target.dataset.time) this._times[e.target.dataset.time] = e.target.value;
    });
    this.shadowRoot.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && e.target.dataset.time) this._act("start-car", e.target.dataset.time);
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
        const time = this._times[routeId];
        if (!time) return;
        await this._hass.callWS({ type: "andiamo/start_car", route_id: routeId, arrive_at: nextTime(time) });
        delete this._times[routeId];
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
      info = run.leave_at
        ? `<div class="run">${this._t("leaveAt", clock(run.leave_at))} · ${this._t("inMin", minutesUntil(run.leave_at))}</div>
           ${run.line ? `<div class="muted">${esc(run.line)} ${run.departure ? clock(run.departure) : ""}${delay}</div>` : ""}
           ${run.arrive_at ? `<div class="muted">${this._t("arriveBy")} ${clock(run.arrive_at)}</div>` : ""}`
        : `<div class="run">${this._t("running")}</div>`;
      right = `<button data-action="cancel" data-route="${r.id}">${this._t("stop")}</button>`;
    } else if (r.mode === "transit") {
      right = `<button class="primary" data-action="press" data-route="${r.id}">${this._t("start")}</button>`;
    } else {
      right = `<input type="time" data-time="${r.id}" value="${esc(this._times[r.id] || "")}" aria-label="${this._t("arriveBy")}">
        <button class="primary" data-action="start-car" data-route="${r.id}">${this._t("start")}</button>`;
    }
    return `<div class="row">
      <div class="grow"><div class="name">${r.mode === "car" ? "🚗" : "🚋"} ${esc(r.name)}</div>${info}</div>
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
