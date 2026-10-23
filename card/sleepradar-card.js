// SleepRadar Card — the "Now" readout from the app's own MQTT sensors.
//
// Zero dependencies, no build step. Reads the three sensors that already
// exist once the SleepRadar app is running:
//   sensor.<node>_sleep_state
//   sensor.<node>_heart_rate
//   sensor.<node>_respiration_rate
//
// Install: copy this file to /config/www/sleepradar-card.js, then add it as
// a Lovelace resource (Settings > Dashboards > Resources):
//   URL: /local/sleepradar-card.js, Type: JavaScript module
// Then add a card with type: custom:sleepradar-card.

const DEFAULT_NODE_ID = "aqara_fp2_sleep";

// Suffixes match the app's own discovery object ids
// (aqara_fp2_sleep/aqara_fp2_sleep_poller.py). Keep these three in sync with
// the poller's SENSORS list; scripts/validate_repository.py checks this.
const ENTITY_SUFFIXES = {
  sleep_state: "sleep_state",
  heart_rate: "heart_rate",
  respiration_rate: "respiration_rate",
};

// The app's diagnostic entity. Kept outside ENTITY_SUFFIXES: those are all
// sensor.* vitals that the card requires, this is a binary_sensor.* that only
// explains an outage. Absent (older app, or the user renamed it) the card
// behaves as it did before.
const PROBLEM_SUFFIX = "connection_problem";

// Legacy raw Aqara sleep_state labels used when no independent occupancy gate
// is configured. Codes 1 and 2 remain "Awake" in that compatibility mode.
//
// This mapping is COMMUNITY-DERIVED AND UNVERIFIED. Aqara's public resource
// documentation does not publish the FP2 sleep_state enumeration. The
// community mapping reviewed by this project reads code 1 as "In Bed", not
// "Awake", so the legacy label is a compatibility choice rather than a spec.
// The reviewed labels for codes 3/4/5 agree; that is label consistency, not a
// claim that the device's stage estimate is accurate.
//
// With bed_occupancy configured, independent occupancy is authoritative:
// code 0 cannot claim an empty bed, and codes 1/2 cannot claim wakefulness.
const PHASES = {
  0: "Out of bed",
  1: "Awake",
  2: "Awake",
  3: "REM",
  4: "Light sleep",
  5: "Deep sleep",
};

const IN_BED_SLEEP_CODES = new Set([1, 2, 3, 4, 5]);

// "None"/"none" cover a real Home Assistant gotcha: the poller's
// value_template is `{{ value_json.attr | default('unknown') }}`, and
// Jinja's default() filter only replaces Undefined, not a literal null —
// so a null value from the Aqara API (e.g. sleep_state during a data gap)
// renders as the literal text "None" instead of "unknown".
const UNAVAILABLE_STATES = new Set([
  "unavailable",
  "unknown",
  "",
  "None",
  "none",
  undefined,
  null,
]);

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

// Mirrors the app's own sanitize_node_id() (aqara_fp2_sleep_poller.py) so
// a card config pasted straight from mqtt_node_id (e.g. "Bedroom FP2") maps
// to the same entity ids the app actually publishes, instead of a
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

function isInBedCode(code) {
  return IN_BED_SLEEP_CODES.has(code);
}

// Entity ids arrive from user YAML, so they are normalized once here and the
// normalized value is what both hass.states lookups and the bed_occupancy
// independence check see. Rejecting non-strings outright is deliberate: a
// silent String() coercion is what let an array override slip past the
// independence check while still resolving to a real entity.
function resolveEntityId(override, fallback) {
  if (override === undefined || override === null) return fallback;
  if (typeof override !== "string") {
    throw new Error("entities overrides must be entity id strings");
  }
  return override.trim() || fallback;
}

function formatAge(ageMs) {
  if (!Number.isFinite(ageMs) || ageMs < 0) return "";
  const seconds = Math.floor(ageMs / 1000);
  if (seconds < 10) return "just now";
  if (seconds < 60) return `${seconds} sec ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} hr ago`;
  const days = Math.floor(hours / 24);
  return `${days} d ago`;
}

function describeFreshness(ageMs, isStale) {
  const age = formatAge(ageMs);
  if (!age) return "Freshness unknown";
  return `${isStale ? "Stale" : "Updated"} ${age}`;
}

function describeVitalStatus(code, isFresh, isStale, value, occupancyConfirmed) {
  if (isInBedCode(code) && isFresh && value !== null) return "Live now";
  if (isInBedCode(code) && isFresh) return "No value reported";
  if (isStale) return "Status stale";
  if (!isFresh) return "Freshness unknown";
  if (code === 0) return occupancyConfirmed ? "Not measuring" : "Paused out of bed";
  return "Sleep state unknown";
}

function describeFooter(code, isFresh, isStale, occupancyConfirmed) {
  if (isStale) {
    return "Status is stale. Check the app and MQTT before trusting live vitals.";
  }
  if (!isFresh) {
    return "SleepRadar needs a fresh sleep-state timestamp before showing live vitals.";
  }
  if (code === 0) {
    if (occupancyConfirmed) {
      return (
        "Independent occupancy confirms someone is in bed, but SleepRadar " +
        "is not reporting a usable stage or live vitals."
      );
    }
    return (
      "Heart rate and breathing are hidden while the bed is empty because " +
      "the FP2 can retain its last in-bed values."
    );
  }
  if (!isInBedCode(code)) {
    return "SleepRadar needs a mapped in-bed sleep state before showing live vitals.";
  }
  if (code === 1 || code === 2) {
    if (occupancyConfirmed) {
      return (
        "Heart rate and breathing are sensor-reported. Occupancy is confirmed, " +
        "but this sleep-state code does not establish a wake or stage label."
      );
    }
    return (
      "Heart rate and breathing are sensor-reported. The Awake label is kept " +
      "for compatibility and does not establish occupancy or wakefulness."
    );
  }
  // The phase caption already qualifies the stage estimate.
  return "Sensor-reported vitals";
}

function displayPhase(code, occupancyConfirmed) {
  if (occupancyConfirmed && code === 0) return "In bed";
  if (occupancyConfirmed && (code === 1 || code === 2)) {
    return "In bed — stage unknown";
  }
  return PHASES[code] || "Unknown";
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
    // Overrides must be normalized to trimmed strings BEFORE they are compared
    // against bed_occupancy.entity below. A non-string override (e.g. the
    // one-element YAML array `sleep_state: [sensor.x]`) is not strictly equal
    // to the gate string, but coerces to the same key on a hass.states lookup —
    // so without this the gate could resolve to the very entity it arbitrates.
    this._entityIds = {
      sleep_state: resolveEntityId(overrides.sleep_state, defaults.sleep_state),
      heart_rate: resolveEntityId(overrides.heart_rate, defaults.heart_rate),
      respiration_rate: resolveEntityId(
        overrides.respiration_rate,
        defaults.respiration_rate
      ),
    };
    // Not part of _entityIds: that object is what bed_occupancy.entity is
    // checked against for independence, and the diagnostic entity carries no
    // occupancy signal to be confused with.
    this._problemEntityId = resolveEntityId(
      overrides.connection_problem,
      `binary_sensor.${nodeId}_${PROBLEM_SUFFIX}`
    );
    const hasBedOccupancyConfig =
      config && Object.prototype.hasOwnProperty.call(config, "bed_occupancy");
    if (hasBedOccupancyConfig) {
      const bedOccupancy = config.bed_occupancy;
      if (!bedOccupancy || typeof bedOccupancy !== "object" || Array.isArray(bedOccupancy)) {
        throw new Error("bed_occupancy must be a mapping");
      }
      if (typeof bedOccupancy.entity !== "string" || !bedOccupancy.entity.trim()) {
        throw new Error("bed_occupancy.entity is required");
      }
      const entity = bedOccupancy.entity.trim();
      if (Object.values(this._entityIds).includes(entity)) {
        throw new Error(
          "bed_occupancy.entity must be independent from the configured SleepRadar entities"
        );
      }
      let occupiedStates = bedOccupancy.occupied_states;
      if (occupiedStates === undefined) {
        if (!entity.startsWith("binary_sensor.")) {
          throw new Error(
            "bed_occupancy.occupied_states is required for non-binary entities"
          );
        }
        occupiedStates = ["on"];
      }
      if (!Array.isArray(occupiedStates) || occupiedStates.length === 0) {
        throw new Error("bed_occupancy.occupied_states must be a non-empty array");
      }
      if (
        occupiedStates.some(
          (state) => typeof state !== "string" || state.trim().length === 0
        )
      ) {
        throw new Error(
          "bed_occupancy.occupied_states must contain non-empty strings"
        );
      }
      // Stored trimmed: the comparison at render time is a strict includes(),
      // so an untrimmed " on " would validate here and then never match a real
      // state — a gate that is silently dead rather than loudly wrong.
      const normalizedStates = occupiedStates.map((state) => state.trim());
      // A gate that treats every state as occupied is not a gate. Both of these
      // passed shape validation before and produced a permanently-open gate
      // that rendered retained vitals over an empty bed.
      if (normalizedStates.some((state) => UNAVAILABLE_STATES.has(state))) {
        throw new Error(
          "bed_occupancy.occupied_states must not contain unknown, unavailable, " +
            "none, or empty states; those always mean uncertain occupancy"
        );
      }
      if (normalizedStates.includes("on") && normalizedStates.includes("off")) {
        throw new Error(
          "bed_occupancy.occupied_states must not contain both 'on' and 'off'; " +
            "that leaves no state that means the bed is empty"
        );
      }
      this._bedOccupancy = {
        entity,
        occupiedStates: normalizedStates,
      };
    } else {
      this._bedOccupancy = null;
    }
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
    // this, a card whose watched entities stop updating (app hung, still
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
    const occupancyObj = this._bedOccupancy
      ? this._hass.states[this._bedOccupancy.entity]
      : null;

    // Cheap re-render guard: skip DOM work if nothing relevant changed.
    const darkMode = this._hass.themes && this._hass.themes.darkMode;
    const signatureValues = [
      typeof darkMode === "boolean" ? darkMode : null,
      stateObj && [stateObj.state, stateObj.last_updated],
      hrObj && [hrObj.state, hrObj.last_updated],
      brObj && [brObj.state, brObj.last_updated],
    ];
    if (this._bedOccupancy) {
      signatureValues.push(occupancyObj && [occupancyObj.state, occupancyObj.last_updated]);
    }
    // The diagnostic entity changes the rendered text without any vitals
    // changing, since an outage freezes all three of them by definition.
    // Leaving it out of the signature would pin the card on the pre-outage
    // wording.
    const problemObj = this._hass.states[this._problemEntityId];
    signatureValues.push(
      problemObj && [problemObj.state, problemObj.attributes && problemObj.attributes.cause]
    );
    const signature = JSON.stringify(signatureValues);
    if (signature === this._lastSignature) return;
    this._lastSignature = signature;

    if (this._bedOccupancy) {
      const occupancyIsKnown =
        occupancyObj &&
        typeof occupancyObj.state === "string" &&
        !UNAVAILABLE_STATES.has(occupancyObj.state);
      const occupancyIsOccupied =
        occupancyIsKnown &&
        this._bedOccupancy.occupiedStates.includes(occupancyObj.state);
      if (!occupancyIsOccupied) {
        // The bed is empty most of the day, so this is the card's dominant
        // display state. It must not also swallow the sleep-state health
        // signals: a missing entity id or a dead poller would otherwise look
        // exactly like a healthy empty bed for ~16h a day.
        this._renderOccupancyBlocked(
          !occupancyIsKnown,
          occupancyObj,
          this._sleepStateHealth(stateObj)
        );
        return;
      }
    }
    const occupancyConfirmed = Boolean(this._bedOccupancy);

    if (!stateObj || UNAVAILABLE_STATES.has(stateObj.state)) {
      // When the app has published why it stopped, show that instead of the
      // entity-id troubleshooting walkthrough. "No data yet" sends users
      // hunting for a config mistake that isn't there.
      const problemCause = this._connectionProblemCause();
      const body = problemCause
        ? `${escapeHtml(problemCause)}
              Sensors stay unavailable until this is resolved.`
        : `No data from ${escapeHtml(this._entityIds.sleep_state)} yet.
              Check that the SleepRadar app is running and the sensor exists.
              If the app is running but this entity id is wrong, Home
              Assistant pins entity ids when it first creates them and will
              not rename them later if you change mqtt_node_id or upgrade the
              app — check Developer Tools &gt; States for the real id and
              set it with this card's entities: option (see README).`;
      this.shadowRoot.innerHTML = this._styles() + `
        <ha-card>
          <div class="sr-empty">
            <div class="sr-empty-title">SleepRadar</div>
            <div class="sr-empty-body">
              ${body}
            </div>
          </div>
        </ha-card>`;
      return;
    }

    // parseInt() alone would accept garbage-suffixed states like "3-bad" as
    // code 3 (REM) instead of surfacing them as unknown; require the whole
    // string to be a clean integer first.
    const code = /^-?\d+$/.test(stateObj.state) ? parseInt(stateObj.state, 10) : NaN;
    const phase = displayPhase(code, occupancyConfirmed);
    const hr = numericStateOrNull(hrObj);
    const br = numericStateOrNull(brObj);

    const ageMs = Date.now() - parseTimestampMs(stateObj.last_updated);
    const hasUsableFreshness = Number.isFinite(ageMs) && ageMs >= 0;
    const staleAfterMs = this._pollIntervalSeconds * 1000 * 3;
    const isStale = hasUsableFreshness && ageMs > staleAfterMs;
    const isFresh = hasUsableFreshness && !isStale;
    const canShowLiveVitals = isInBedCode(code) && isFresh;
    const shownHr = canShowLiveVitals ? hr : null;
    const shownBr = canShowLiveVitals ? br : null;

    const freshness = describeFreshness(ageMs, isStale);
    const time = formatTime(stateObj.last_updated);
    // Freshness already names stale data; reserve the extra badge for a
    // distinct state instead of repeating the same warning twice.
    const badge = !isStale && code === 0 ? "not measuring" : "";
    const phaseCaption =
      !isFresh
        ? "last reported"
        : occupancyConfirmed && code === 0
          ? "occupancy confirmed"
          : code === 0
          ? "bed empty"
          : occupancyConfirmed && (code === 1 || code === 2)
            ? "unverified sleep code"
          : isInBedCode(code)
            ? "the sensor's best guess"
            : "unmapped code";
    const footer = describeFooter(code, isFresh, isStale, occupancyConfirmed);

    // Presentation reuses the parsed code and existing freshness decision.
    // Occupancy-blocked paths returned above and can never reach this accent.
    const phaseKind = isFresh ? ({ 3: "rem", 4: "light", 5: "deep" }[code] || "unknown") : "unknown";
    this._renderReadout({
      phase, phaseCaption, phaseKind, freshness, time, badge, footer,
      heartRate: shownHr,
      breathing: shownBr,
      heartStatus: describeVitalStatus(code, isFresh, isStale, shownHr, occupancyConfirmed),
      breathingStatus: describeVitalStatus(code, isFresh, isStale, shownBr, occupancyConfirmed),
    });
  }

  // The app's own explanation for why data stopped, when it published one.
  // Returns null when there is no problem, or when the diagnostic entity is
  // absent (older app, renamed entity). Callers then keep the generic wording,
  // which is what the card said before this entity existed.
  _connectionProblemCause() {
    const obj = this._hass && this._hass.states[this._problemEntityId];
    if (!obj || UNAVAILABLE_STATES.has(obj.state)) return null;
    if (String(obj.state).toLowerCase() !== "on") return null;
    const cause = obj.attributes && obj.attributes.cause;
    if (typeof cause !== "string" || !cause.trim()) {
      // The flag is set but carries no text, so name the likeliest cause.
      return "SleepRadar cannot reach the Aqara cloud. Check the app log.";
    }
    return cause.trim();
  }

  // Health of the sleep-state feed, evaluated independently of the occupancy
  // gate so the blocked card can report it. Returns "ok" only when the entity
  // exists, is available, and its timestamp is inside the stale window.
  _sleepStateHealth(stateObj) {
    if (!stateObj || UNAVAILABLE_STATES.has(stateObj.state)) {
      return {
        status: "missing",
        note:
          this._connectionProblemCause() ||
          "SleepRadar is not reporting a sleep state. Check that the app is " +
            "running and that this card points at the right entity id.",
      };
    }
    const ageMs = Date.now() - parseTimestampMs(stateObj.last_updated);
    const staleAfterMs = this._pollIntervalSeconds * 1000 * 3;
    if (Number.isFinite(ageMs) && ageMs >= 0 && ageMs > staleAfterMs) {
      return {
        status: "stale",
        // A crashed poller flips the problem flag through the MQTT will
        // immediately, but the vitals stay available until expire_after (up to
        // 3 poll intervals). In that window the feed reads as merely stale
        // although the app has already published why it died, so prefer the
        // cause.
        note:
          this._connectionProblemCause() ||
          "The sleep-state feed is stale. Occupancy is still being read, but " +
            "check the app and MQTT.",
      };
    }
    return { status: "ok", note: "" };
  }

  _renderOccupancyBlocked(isUnknown, occupancyObj, sleepHealth) {
    const health = sleepHealth || { status: "ok", note: "" };
    const phase = isUnknown ? "Occupancy unknown" : "Out of bed";
    const phaseCaption = isUnknown ? "occupancy unavailable" : "bed empty";
    const vitalStatus = isUnknown ? "Occupancy unknown" : "Paused out of bed";
    const baseFooter = isUnknown
      ? "Heart rate and breathing are hidden because the independent bed-occupancy state is unavailable."
      : // Deliberately does not say the sensor "reports the bed is empty". Any
        // state outside occupied_states lands here, including device states
        // like offline, error or calibrating, and attributing an empty-bed
        // reading to the sensor in those cases would be a claim it never made.
        "Heart rate and breathing are hidden because the independent " +
        "bed-occupancy sensor is not reporting an occupied state.";
    const footer = health.note ? `${baseFooter} ${health.note}` : baseFooter;
    const time = formatTime(occupancyObj && occupancyObj.last_updated);
    // An empty bed is expected and stays calm; a broken gate or a dead
    // sleep-state feed is a fault and must not wear the same neutral badge.
    // Each badge carries its own word, so the state never depends on hue alone.
    const badge = isUnknown
      ? "occupancy fault"
      : health.status === "stale"
        ? "stale"
        : health.status === "missing"
          ? "no sensor data"
          : "not measuring";
    this._renderReadout({
      phase, phaseCaption, time, badge, footer,
      heartRate: null,
      breathing: null,
      heartStatus: vitalStatus,
      breathingStatus: vitalStatus,
    });
  }

  _renderReadout({
    phase, phaseCaption, phaseKind = "unknown", freshness = "", time,
    badge, footer, heartRate, breathing, heartStatus, breathingStatus,
  }) {
    const metrics = [
      { label: "Heart rate", value: heartRate, unit: "bpm", status: heartStatus },
      { label: "Breathing", value: breathing, unit: "br/min", status: breathingStatus },
    ];
    const badgeClass = badge === "not measuring" ? " sr-badge-neutral" : "";
    this.shadowRoot.innerHTML = this._styles() + `
      <ha-card>
        <div class="sr-card" data-phase="${phaseKind}">
          <div class="sr-header">
            <div class="sr-header-left">
              <h3 class="sr-phase"><span class="sr-phase-mark" aria-hidden="true"></span>${escapeHtml(phase)}</h3>
              <div class="sr-caption">${escapeHtml(phaseCaption)}</div>
            </div>
            <div class="sr-freshness">
              ${freshness ? `<span>${escapeHtml(freshness)}</span>` : ""}
              ${time ? `<time>${escapeHtml(time)}</time>` : ""}
              ${badge ? `<span class="sr-badge${badgeClass}">${escapeHtml(badge)}</span>` : ""}
            </div>
          </div>
          <div class="sr-stats" role="group" aria-label="Sensor-reported vital readings">
            ${metrics.map(({ label, value, unit, status }) => `
              <div class="sr-stat">
                <div class="sr-stat-label">${label}</div>
                <div class="sr-stat-value">${value !== null ? escapeHtml(value) : "—"}
                  <span class="sr-unit">${unit}</span>
                </div>
                ${status && status !== "Live now" ? `<div class="sr-stat-status">${escapeHtml(status)}</div>` : ""}
              </div>`).join("")}
          </div>
          <div class="sr-footer">${escapeHtml(footer)}</div>
        </div>
      </ha-card>`;
  }

  _styles() {
    // HA's dashboard mode may differ from the operating-system preference.
    // Missing theme metadata falls back to the inherited primary text color.
    const mode = this._hass && this._hass.themes && this._hass.themes.darkMode;
    const dark = mode === true;
    const inks = typeof mode !== "boolean"
      ? { deep: "var(--sr-text)", light: "var(--sr-text)", rem: "var(--sr-text)" }
      : dark
        ? { deep: "#9bb9ff", light: "#8ec4ff", rem: "#f4c773" }
        : { deep: "#2758d8", light: "#216dd8", rem: "#925600" };
    return `<style>
      :host {
        display: block;
        --sr-text: var(--primary-text-color, ${dark ? "#e8e8ea" : "#202936"});
        --sr-muted: var(--secondary-text-color, ${dark ? "#abb2be" : "#4c596b"});
        --sr-border: var(--divider-color, ${dark ? "#2b2d31" : "#dce1e8"});
        --sr-blue: ${dark ? "#5aa2ff" : "#216dd8"};
        --sr-heart: ${dark ? "#ff4d57" : "#bd3041"};
        font-family: var(--paper-font-body1_-_font-family, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif);
        letter-spacing: 0;
      }
      ha-card {
        padding: 0; overflow: hidden; border-radius: 8px;
        color: var(--sr-text);
        background: var(--ha-card-background, var(--card-background-color, ${dark ? "#1b1c1e" : "#ffffff"}));
      }
      .sr-card {
        --sr-phase-ink: var(--sr-text); --sr-phase-rail: var(--sr-border);
        display: flex; flex-direction: column;
      }
      .sr-card[data-phase="deep"] {
        --sr-phase-ink: var(--sleepradar-deep-color, ${inks.deep});
        --sr-phase-rail: #2758d8;
      }
      .sr-card[data-phase="light"] {
        --sr-phase-ink: var(--sleepradar-light-color, ${inks.light});
        --sr-phase-rail: var(--sr-blue);
      }
      .sr-card[data-phase="rem"] {
        --sr-phase-ink: var(--sleepradar-rem-color, ${inks.rem});
        --sr-phase-rail: #f5a623;
      }
      .sr-header {
        display: flex; justify-content: space-between; align-items: flex-start;
        flex-wrap: wrap; gap: 10px; padding: 15px 16px 12px;
        border-top: 2px solid var(--sr-phase-rail);
      }
      .sr-header-left { min-width: 0; flex: 1 1 160px; }
      .sr-phase {
        margin: 0; font-size: 1.375rem; font-weight: 600; line-height: 1.25;
        color: var(--sr-phase-ink); overflow-wrap: anywhere;
      }
      .sr-phase-mark {
        display: inline-block; width: 10px; height: 10px; box-sizing: border-box;
        margin-inline-end: 9px; vertical-align: 2px; border-radius: 50%;
        background: currentColor; border: 2px solid currentColor;
      }
      [data-phase="light"] .sr-phase-mark { background: transparent; }
      [data-phase="rem"] .sr-phase-mark { border-radius: 1px; transform: rotate(45deg); }
      [data-phase="unknown"] .sr-phase-mark {
        height: 2px; border: 0; border-radius: 0; vertical-align: 6px;
      }
      .sr-caption {
        margin: 5px 0 0 19px; font-size: 0.8125rem; line-height: 1.4;
        color: var(--sr-muted); overflow-wrap: anywhere;
      }
      .sr-freshness {
        display: flex; flex-direction: column; align-items: flex-end;
        padding-top: 1px; font-size: 0.75rem; line-height: 1.5;
        color: var(--sr-muted); font-variant-numeric: tabular-nums;
      }
      .sr-badge { font-weight: 600; }
      .sr-badge-neutral { font-weight: 400; }
      .sr-stats {
        display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
        gap: 16px; margin: 14px 16px 12px;
      }
      .sr-stat { min-width: 0; }
      .sr-stat + .sr-stat { padding-inline-start: 16px; border-inline-start: 1px solid var(--sr-border); }
      .sr-stat-label {
        display: flex; align-items: center; gap: 5px;
        font-size: 0.8125rem; line-height: 1.4; color: var(--sr-muted);
      }
      .sr-stat-label::before {
        content: ""; width: 5px; height: 5px; border-radius: 50%;
        flex: 0 0 auto; background: var(--sr-heart);
      }
      .sr-stat + .sr-stat .sr-stat-label::before { background: var(--sr-blue); }
      .sr-stat-value {
        display: flex; align-items: baseline; flex-wrap: wrap; gap: 6px;
        margin-top: 5px; font-size: 2rem; font-weight: 600; line-height: 1.15;
        font-variant-numeric: tabular-nums; overflow-wrap: anywhere;
      }
      .sr-unit { font-size: 0.8125rem; font-weight: 400; line-height: 1.4; color: var(--sr-muted); }
      .sr-stat-status { margin-top: 5px; font-size: 0.75rem; line-height: 1.4; color: var(--sr-muted); }
      .sr-footer {
        margin-inline: 16px; padding: 8px 0 10px; border-top: 1px solid var(--sr-border);
        font-size: 0.75rem; line-height: 1.4; color: var(--sr-muted); overflow-wrap: anywhere;
      }
      .sr-empty { padding: 16px; }
      .sr-empty-title { font-weight: 600; margin-bottom: 6px; }
      .sr-empty-body { font-size: 0.85rem; line-height: 1.5; overflow-wrap: anywhere; }
    </style>`;
  }
}

customElements.define("sleepradar-card", SleepradarCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "sleepradar-card",
  name: "SleepRadar Card",
  description: "Live sleep phase, heart rate, and breathing from the SleepRadar app.",
});
