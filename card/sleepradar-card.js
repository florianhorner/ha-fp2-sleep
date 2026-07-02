// SleepRadar Card — the "Now" readout from the add-on's own MQTT sensors.
//
// Zero dependencies, no build step. Reads the three sensors that already
// exist once the SleepRadar add-on is running:
//   sensor.<node>_sleep_state
//   sensor.<node>_heart_rate
//   sensor.<node>_respiration_rate
//
// Install: copy this file to /config/www/sleepradar-card.js, then add it as
// a Lovelace resource (Settings > Dashboards > Resources):
//   URL: /local/sleepradar-card.js, Type: JavaScript module
// Then add a card with type: custom:sleepradar-card.

const DEFAULT_NODE_ID = "aqara_fp2_sleep";

// Suffixes match the add-on's own discovery object ids
// (aqara_fp2_sleep/aqara_fp2_sleep_poller.py). Keep these three in sync with
// the poller's SENSORS list; scripts/validate_repository.py checks this.
const ENTITY_SUFFIXES = {
  sleep_state: "sleep_state",
  heart_rate: "heart_rate",
  respiration_rate: "respiration_rate",
};

// Raw Aqara sleep_state codes. Codes 1 and 2 are both "awake"; see README
// "Sleep State Codes" and examples/sleep_tracking.yaml for the same mapping.
const PHASES = {
  0: "Out of bed",
  1: "Awake",
  2: "Awake",
  3: "REM",
  4: "Light sleep",
  5: "Deep sleep",
};

const UNAVAILABLE_STATES = new Set(["unavailable", "unknown", "", undefined, null]);

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function defaultEntities(nodeId) {
  return {
    sleep_state: `sensor.${nodeId}_${ENTITY_SUFFIXES.sleep_state}`,
    heart_rate: `sensor.${nodeId}_${ENTITY_SUFFIXES.heart_rate}`,
    respiration_rate: `sensor.${nodeId}_${ENTITY_SUFFIXES.respiration_rate}`,
  };
}

// Mirrors the add-on's own sanitize_node_id() (aqara_fp2_sleep_poller.py) so
// a card config pasted straight from mqtt_node_id (e.g. "Bedroom FP2") maps
// to the same entity ids the add-on actually publishes, instead of a
// literal, never-matching sensor.Bedroom FP2_sleep_state.
function sanitizeNodeId(value) {
  const node = String(value || "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_]+/g, "_")
    .replace(/_+/g, "_")
    .replace(/^_|_$/g, "");
  return node || DEFAULT_NODE_ID;
}

function describeNow(phase, code, hr, br) {
  if (code === 0) return "Not in bed right now.";
  const haveVitals = hr !== null && br !== null;
  if (code === 1 || code === 2) {
    return haveVitals
      ? `Awake in bed — heart ${hr} bpm, breathing ${br} br/min.`
      : "Awake in bed.";
  }
  return haveVitals ? `${phase} — heart ${hr} bpm, breathing ${br} br/min.` : `${phase}.`;
}

// Treats non-numeric sensor states (e.g. a stringified "None" from a null
// MQTT payload) the same as unavailable, instead of rendering them verbatim.
function numericStateOrNull(stateObj) {
  if (!stateObj || UNAVAILABLE_STATES.has(stateObj.state)) return null;
  return Number.isFinite(Number(stateObj.state)) ? stateObj.state : null;
}

// Single source of truth for "is this a usable last_updated timestamp",
// shared by the stale-badge calculation and the header time display.
// `new Date(null)` / `new Date(0)` resolve to a valid epoch date rather than
// NaN, so a missing/non-string timestamp must be rejected before it reaches
// the Date constructor.
function parseTimestampMs(value) {
  if (typeof value !== "string" || !value) return NaN;
  const ms = new Date(value).getTime();
  return Number.isNaN(ms) ? NaN : ms;
}

function formatTime(isoString) {
  const ms = parseTimestampMs(isoString);
  if (Number.isNaN(ms)) return "";
  return new Date(ms).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

class SleepradarCard extends HTMLElement {
  setConfig(config) {
    const nodeId = sanitizeNodeId(config && config.mqtt_node_id);
    const defaults = defaultEntities(nodeId);
    const overrides = (config && config.entities) || {};
    this._entityIds = {
      sleep_state: overrides.sleep_state || defaults.sleep_state,
      heart_rate: overrides.heart_rate || defaults.heart_rate,
      respiration_rate: overrides.respiration_rate || defaults.respiration_rate,
    };
    const pollIntervalSeconds = Number(config && config.poll_interval_seconds);
    this._pollIntervalSeconds =
      Number.isFinite(pollIntervalSeconds) && pollIntervalSeconds > 0 ? pollIntervalSeconds : 60;
    this._config = config || {};
    this._lastSignature = null;
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  connectedCallback() {
    // Staleness depends on wall-clock time, not just entity state — without
    // this, a card whose watched entities stop updating (add-on hung, still
    // connected to MQTT) would never re-evaluate the "stale" badge, since
    // _render()'s cheap re-render guard only fires on entity state changes.
    this._staleCheckTimer = setInterval(() => {
      this._lastSignature = null;
      this._render();
    }, 30000);
  }

  disconnectedCallback() {
    clearInterval(this._staleCheckTimer);
  }

  getCardSize() {
    return 3;
  }

  static getStubConfig() {
    return {};
  }

  _render() {
    if (!this._hass || !this._entityIds) return;

    const stateObj = this._hass.states[this._entityIds.sleep_state];
    const hrObj = this._hass.states[this._entityIds.heart_rate];
    const brObj = this._hass.states[this._entityIds.respiration_rate];

    // Cheap re-render guard: skip DOM work if nothing relevant changed.
    const signature = JSON.stringify([
      stateObj && [stateObj.state, stateObj.last_updated],
      hrObj && [hrObj.state, hrObj.last_updated],
      brObj && [brObj.state, brObj.last_updated],
    ]);
    if (signature === this._lastSignature) return;
    this._lastSignature = signature;

    if (!stateObj || UNAVAILABLE_STATES.has(stateObj.state)) {
      this.shadowRoot.innerHTML = this._styles() + `
        <ha-card>
          <div class="sr-empty">
            <div class="sr-empty-title">SleepRadar</div>
            <div class="sr-empty-body">
              No data from ${escapeHtml(this._entityIds.sleep_state)} yet.
              Check that the SleepRadar add-on is running and the sensor exists.
            </div>
          </div>
        </ha-card>`;
      return;
    }

    // parseInt() alone would accept garbage-suffixed states like "3-bad" as
    // code 3 (REM) instead of surfacing them as unknown; require the whole
    // string to be a clean integer first.
    const code = /^-?\d+$/.test(stateObj.state) ? parseInt(stateObj.state, 10) : NaN;
    const phase = PHASES[code] || "Unknown";
    const hr = numericStateOrNull(hrObj);
    const br = numericStateOrNull(brObj);

    const ageMs = Date.now() - parseTimestampMs(stateObj.last_updated);
    const staleAfterMs = this._pollIntervalSeconds * 1000 * 3;
    const isStale = Number.isFinite(ageMs) && ageMs > staleAfterMs;

    const time = formatTime(stateObj.last_updated);
    const readout = describeNow(phase, code, hr, br);

    this.shadowRoot.innerHTML = this._styles() + `
      <ha-card>
        <div class="sr-card">
          <div class="sr-header">
            <div class="sr-header-left">
              <div class="sr-eyebrow">READING NOW${time ? ` · ${escapeHtml(time)}` : ""}</div>
              <div class="sr-phase">${escapeHtml(phase)}
                <span class="sr-caption">the sensor's best guess</span>
              </div>
            </div>
            ${isStale ? '<div class="sr-badge">stale</div>' : ""}
          </div>
          <div class="sr-readout">${escapeHtml(readout)}</div>
          <div class="sr-stats">
            <div class="sr-stat">
              <div class="sr-stat-label">Heart rate</div>
              <div class="sr-stat-value">${hr !== null ? escapeHtml(hr) : "—"}
                <span class="sr-unit">bpm</span>
              </div>
            </div>
            <div class="sr-stat">
              <div class="sr-stat-label">Breathing</div>
              <div class="sr-stat-value">${br !== null ? escapeHtml(br) : "—"}
                <span class="sr-unit">br/min</span>
              </div>
            </div>
          </div>
          <div class="sr-footer">
            Heart rate and breathing are measured directly by the sensor.
            Sleep stage is the device's best guess.
          </div>
        </div>
      </ha-card>`;
  }

  _styles() {
    return `<style>
      ha-card { padding: 16px; }
      .sr-card { display: flex; flex-direction: column; gap: 12px; }
      .sr-header { display: flex; justify-content: space-between; align-items: flex-start; }
      .sr-eyebrow {
        font-size: 0.75rem; letter-spacing: 0.04em; text-transform: uppercase;
        color: var(--secondary-text-color);
      }
      .sr-phase {
        font-size: 1.4rem; font-weight: 600; color: var(--primary-text-color);
        margin-top: 2px;
      }
      .sr-caption {
        font-size: 0.8rem; font-weight: 400; color: var(--secondary-text-color);
        margin-left: 6px;
      }
      .sr-badge {
        font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.04em;
        color: var(--warning-color, #f0ad4e); border: 1px solid var(--warning-color, #f0ad4e);
        border-radius: 4px; padding: 2px 6px; height: fit-content;
      }
      .sr-readout { color: var(--primary-text-color); }
      .sr-stats { display: flex; gap: 12px; }
      .sr-stat {
        flex: 1; border: 1px solid var(--divider-color); border-radius: 8px;
        padding: 10px 12px;
      }
      .sr-stat-label { font-size: 0.8rem; color: var(--secondary-text-color); }
      .sr-stat-value { font-size: 1.4rem; font-weight: 600; color: var(--primary-text-color); }
      .sr-unit { font-size: 0.85rem; font-weight: 400; color: var(--secondary-text-color); }
      .sr-footer { font-size: 0.75rem; color: var(--secondary-text-color); }
      .sr-empty-title { font-weight: 600; color: var(--primary-text-color); margin-bottom: 6px; }
      .sr-empty-body { font-size: 0.85rem; color: var(--secondary-text-color); }
    </style>`;
  }
}

customElements.define("sleepradar-card", SleepradarCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "sleepradar-card",
  name: "SleepRadar Card",
  description: "Live sleep phase, heart rate, and breathing from the SleepRadar add-on.",
});
