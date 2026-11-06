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
        "Someone is in bed, but this sleep-state code does not say whether " +
        "they are awake or asleep."
      );
    }
    return (
      "Awake does not confirm that someone is in bed."
    );
  }
  // A healthy stage needs no footer: the phase caption already says the
  // stage is estimated.
  return "";
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
    if (!this.shadowRoot) {
      this.attachShadow({ mode: "open" });
      // One delegated listener survives every innerHTML re-render. Buttons
      // give Enter/Space activation for free, so click is the only event
      // needed. It opens Home Assistant's own more-info dialog: history, exact
      // last-changed time and attributes for the entity behind the tapped area.
      this.shadowRoot.addEventListener("click", (event) => {
        const target = event.target.closest("[data-entity]");
        if (!target) return;
        this.dispatchEvent(
          new CustomEvent("hass-more-info", {
            bubbles: true,
            composed: true,
            detail: { entityId: target.getAttribute("data-entity") },
          })
        );
      });
    }
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

  // Sections view: a full section by default, never narrower than half of
  // one. Rows are left to HA so caveat text can grow the card.
  getGridOptions() {
    return { columns: 12, min_columns: 6 };
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
      this._lastHtml = null;
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
        ? "Last reported"
        : occupancyConfirmed && code === 0
          ? "Occupancy confirmed"
          : code === 0
          ? "Bed empty"
          : occupancyConfirmed && (code === 1 || code === 2)
            ? "Unverified sleep code"
          : isInBedCode(code)
            ? "Estimated sleep stage"
            : "Unmapped code";
    const footer = describeFooter(code, isFresh, isStale, occupancyConfirmed);

    // Presentation reuses the parsed code and existing freshness decision.
    // Occupancy-blocked paths returned above and can never reach this accent.
    const phaseKind = isFresh ? ({ 3: "rem", 4: "light", 5: "deep" }[code] || "unknown") : "unknown";
    this._renderReadout({
      phase, phaseCaption, phaseKind, freshness, time, badge, footer,
      freshnessIso: stateObj.last_updated,
      phaseEntity: this._entityIds.sleep_state,
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
    const phaseCaption = isUnknown ? "Occupancy unavailable" : "Bed empty";
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
    const occupancyTime = formatTime(occupancyObj && occupancyObj.last_updated);
    // One freshness line: when the occupancy state began, as clock time.
    const freshness = occupancyTime ? `Since ${occupancyTime}` : "";
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
      phase, phaseCaption, freshness, badge, footer,
      freshnessIso: occupancyObj && occupancyObj.last_updated,
      // The heading reports the occupancy gate, so its history is the one
      // that explains it.
      phaseEntity: this._bedOccupancy.entity,
      heartRate: null,
      breathing: null,
      heartStatus: vitalStatus,
      breathingStatus: vitalStatus,
    });
  }

  _renderReadout({
    phase, phaseCaption, phaseKind = "unknown", freshness = "", time = "",
    freshnessIso = "", phaseEntity = "", badge, footer, heartRate, breathing,
    heartStatus, breathingStatus,
  }) {
    const metrics = [
      {
        label: "Heart rate", value: heartRate, unit: "bpm", status: heartStatus,
        icon: ICON_HEART, entity: this._entityIds.heart_rate,
      },
      {
        label: "Breathing", value: breathing, unit: "breaths/min", status: breathingStatus,
        icon: ICON_LUNGS, entity: this._entityIds.respiration_rate,
      },
    ];
    const badgeClass = badge === "not measuring" ? " sr-badge-neutral" : "";
    // One freshness line. The exact clock time sits in the tooltip and in the
    // entity's more-info dialog rather than competing with the relative age.
    // A <time> element only when the timestamp is real; "Freshness unknown"
    // stays plain text.
    const freshnessMs = parseTimestampMs(freshnessIso);
    const freshnessHtml = !freshness
      ? ""
      : Number.isNaN(freshnessMs)
        ? `<span>${escapeHtml(freshness)}</span>`
        : `<time datetime="${escapeHtml(new Date(freshnessMs).toISOString())}"` +
          `${time ? ` title="${escapeHtml(time)}"` : ""}>${escapeHtml(freshness)}</time>`;
    const html = this._styles() + `
      <ha-card>
        <div class="sr-card" data-phase="${phaseKind}">
          <div class="sr-header">
            <div class="sr-header-left sr-zone">
              <h3 class="sr-phase">${tapTarget(phaseEntity, `<span class="sr-phase-mark" aria-hidden="true"></span>${escapeHtml(phase)}`)}</h3>
              <div class="sr-caption">${escapeHtml(phaseCaption)}</div>
            </div>
            <div class="sr-freshness">
              ${freshnessHtml}
              ${badge ? `<span class="sr-badge${badgeClass}">${escapeHtml(badge)}</span>` : ""}
            </div>
          </div>
          <div class="sr-stats" role="group" aria-label="Sensor-reported vital readings">
            ${metrics.map(({ label, value, unit, status, icon, entity }) => `
              <div class="sr-stat sr-zone">
                <div class="sr-stat-label">${svgIcon(icon)}${tapTarget(entity, label)}</div>
                <div class="sr-stat-value">${value !== null ? escapeHtml(value) : "—"}
                  <span class="sr-unit">${unit}</span>
                </div>
                ${status && status !== "Live now" ? `<div class="sr-stat-status">${escapeHtml(status)}</div>` : ""}
              </div>`).join("")}
          </div>
          ${footer ? `<div class="sr-footer">${escapeHtml(footer)}</div>` : ""}
        </div>
      </ha-card>`;
    // The 30 s stale check re-renders on a timer. Rewriting identical markup
    // would drop keyboard focus and hover from the tap zones for nothing.
    // Compared against our own last string: reading innerHTML back returns
    // the browser's re-serialization, which never matches the source.
    if (html === this._lastHtml) return;
    this._lastHtml = html;
    // The age text changes every minute, so a real rewrite still happens
    // regularly. Put focus back on the same tap zone so keyboard users stay put.
    const focused = this.shadowRoot.activeElement;
    const focusedEntity = focused ? focused.getAttribute("data-entity") : null;
    this.shadowRoot.innerHTML = html;
    if (focusedEntity) {
      const next = [...this.shadowRoot.querySelectorAll("[data-entity]")]
        .find((element) => element.getAttribute("data-entity") === focusedEntity);
      if (next) next.focus();
    }
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
        font-family: var(--paper-font-body1_-_font-family, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif);
        letter-spacing: 0;
      }
      ha-card {
        padding: 0; overflow: hidden; border-radius: 8px;
        color: var(--sr-text);
        background: var(--ha-card-background, var(--card-background-color, ${dark ? "#1b1c1e" : "#ffffff"}));
        display: block; container: sleepradar / inline-size;
      }
      .sr-card {
        --sr-phase-ink: var(--sr-text); --sr-phase-rail: var(--sr-border);
        display: flex; flex-direction: column;
        border-top: 2px solid var(--sr-phase-rail);
        padding: 15px 16px 14px;
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
        flex-wrap: wrap; gap: 6px 12px;
      }
      .sr-header-left { min-width: 0; flex: 1 1 160px; }
      .sr-phase {
        margin: 0; font-size: 1.375rem; font-weight: 600; line-height: 1.25;
        color: var(--sr-phase-ink); overflow-wrap: anywhere;
      }
      .sr-phase-mark {
        /* em-sized so the shape cue grows with large text, not only colour */
        display: inline-block; width: 0.455em; height: 0.455em; box-sizing: border-box;
        margin-inline-end: 0.41em; vertical-align: 0.09em; border-radius: 50%;
        background: currentColor; border: max(2px, 0.09em) solid currentColor;
      }
      [data-phase="light"] .sr-phase-mark { background: transparent; }
      [data-phase="rem"] .sr-phase-mark { border-radius: 1px; transform: rotate(45deg); }
      [data-phase="unknown"] .sr-phase-mark {
        height: max(2px, 0.09em); border: 0; border-radius: 0; vertical-align: 0.27em;
      }
      .sr-caption {
        margin: 4px 0 0 1.1875rem; font-size: 0.8125rem; line-height: 1.4;
        color: var(--sr-muted); overflow-wrap: anywhere;
      }
      .sr-freshness {
        display: flex; flex-direction: column; align-items: flex-end; gap: 2px;
        padding-top: 3px; font-size: 0.75rem; line-height: 1.4;
        color: var(--sr-muted); font-variant-numeric: tabular-nums;
      }
      .sr-badge { font-weight: 600; }
      .sr-badge-neutral { font-weight: 400; }
      .sr-stats {
        display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
        gap: 16px; margin-top: 16px;
      }
      .sr-stat { min-width: 0; }
      .sr-stat + .sr-stat { padding-inline-start: 16px; border-inline-start: 1px solid var(--sr-border); }
      .sr-stat-label {
        display: flex; align-items: center; gap: 6px;
        font-size: 0.8125rem; line-height: 1.4; color: var(--sr-muted);
      }
      .sr-icon { width: 1.1em; height: 1.1em; flex: 0 0 auto; fill: currentColor; opacity: 0.85; }
      .sr-stat-value {
        display: flex; align-items: baseline; flex-wrap: wrap; gap: 4px 6px;
        margin-top: 4px; font-size: 2rem; font-weight: 600; line-height: 1.15;
        font-variant-numeric: tabular-nums; overflow-wrap: anywhere;
      }
      .sr-unit { font-size: 0.8125rem; font-weight: 400; line-height: 1.4; color: var(--sr-muted); }
      .sr-stat-status { margin-top: 4px; font-size: 0.75rem; line-height: 1.4; color: var(--sr-muted); }
      .sr-footer {
        margin-top: 12px; font-size: 0.75rem; line-height: 1.45;
        color: var(--sr-muted); overflow-wrap: anywhere; max-width: 60ch;
      }
      /* Each zone opens its entity. The button keeps native focus and
         keyboard activation; its ::after stretches the hit area over the zone. */
      .sr-zone { position: relative; }
      .sr-hit {
        font: inherit; color: inherit; letter-spacing: inherit; text-align: inherit;
        background: none; border: 0; padding: 0; margin: 0; cursor: pointer;
        -webkit-tap-highlight-color: transparent;
      }
      .sr-hit::after {
        content: ""; position: absolute; inset: -6px -8px; border-radius: 8px;
        transition: background-color 140ms cubic-bezier(0.16, 1, 0.3, 1);
      }
      .sr-stat + .sr-stat .sr-hit::after { inset-inline-start: 8px; }
      .sr-hit:focus { outline: none; }
      .sr-hit:focus-visible::after { outline: 2px solid var(--primary-color, var(--sr-blue)); outline-offset: 0; }
      .sr-hit:active::after { background: color-mix(in srgb, var(--sr-text) 10%, transparent); }
      @media (hover: hover) {
        .sr-hit:hover::after { background: color-mix(in srgb, var(--sr-text) 6%, transparent); }
      }
      @media (prefers-reduced-motion: reduce) { .sr-hit::after { transition: none; } }
      /* Narrow columns (half-width sections, small masonry columns) and large
         text. rem keeps the breakpoints tied to the user's text size. */
      @container sleepradar (max-width: 16rem) {
        .sr-freshness { flex-direction: row; flex-wrap: wrap; align-items: baseline; gap: 2px 8px; }
        .sr-stats { grid-template-columns: minmax(0, 1fr); gap: 12px; margin-top: 14px; }
        .sr-stat + .sr-stat {
          padding-inline-start: 0; border-inline-start: 0;
          padding-top: 12px; border-top: 1px solid var(--sr-border);
        }
        .sr-stat + .sr-stat .sr-hit::after { inset-inline-start: -8px; inset-block-start: 6px; }
      }
      /* Wide panels and full-width sections: phase and vitals share one row. */
      @container sleepradar (min-width: 35rem) {
        .sr-card {
          display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1.25fr);
          column-gap: 24px; align-items: center;
        }
        .sr-stats { margin-top: 0; }
        .sr-footer { grid-column: 1 / -1; }
      }
      .sr-empty { padding: 16px; }
      .sr-empty-title { font-weight: 600; margin-bottom: 6px; }
      .sr-empty-body { font-size: 0.85rem; line-height: 1.5; overflow-wrap: anywhere; }
    </style>`;
  }
}

// Metric icons: mdiHeartPulse and mdiLungs from Material Design Icons
// (@mdi/js 7.4.47, Apache-2.0, https://pictogrammers.com), the family Home
// Assistant itself uses. Inlined so the card keeps zero dependencies.
const ICON_HEART =
  "M7.5,4A5.5,5.5 0 0,0 2,9.5C2,10 2.09,10.5 2.22,11H6.3L7.57,7.63C7.87,6.83 9.05,6.75 9.43,7.63L11.5,13L12.09,11.58C12.22,11.25 12.57,11 13,11H21.78C21.91,10.5 22,10 22,9.5A5.5,5.5 0 0,0 16.5,4C14.64,4 13,4.93 12,6.34C11,4.93 9.36,4 7.5,4V4M3,12.5A1,1 0 0,0 2,13.5A1,1 0 0,0 3,14.5H5.44L11,20C12,20.9 12,20.9 13,20L18.56,14.5H21A1,1 0 0,0 22,13.5A1,1 0 0,0 21,12.5H13.4L12.47,14.8C12.07,15.81 10.92,15.67 10.55,14.83L8.5,9.5L7.54,11.83C7.39,12.21 7.05,12.5 6.6,12.5H3Z";
const ICON_LUNGS =
  "M15.47 3.11C15 2.85 14.37 3.05 14.11 3.54C14.04 3.68 14 3.84 14 4V6.59L13.29 5.88C13.1 5.69 13 5.44 13 5.18V1H11V5.17C11 5.44 10.9 5.69 10.71 5.88L10 6.59V4C10 3.44 9.54 3 9 3C8.83 3 8.67 3.04 8.53 3.11C4.72 5 2 9.97 2 15.77C2 17.67 2.33 19.55 3 21.32C3.19 21.85 3.76 22.13 4.29 21.94C4.34 21.92 4.39 21.9 4.44 21.87L9.5 19.07C9.81 18.9 10 18.56 10 18.19V9.41L11.3 8.12C11.69 7.73 12.32 7.73 12.71 8.12L14 9.42V18.2C14 18.56 14.21 18.9 14.5 19.08L19.58 21.88C20.07 22.14 20.68 21.96 20.94 21.46C20.96 21.42 21 21.37 21 21.32C21.67 19.55 22 17.67 22 15.77C22 9.97 19.29 5 15.47 3.11Z";

function svgIcon(path) {
  return `<svg class="sr-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="${path}"/></svg>`;
}

// Wraps a label in a button that opens the entity's more-info dialog; plain
// text when there is no entity to open.
function tapTarget(entity, content) {
  return entity
    ? `<button class="sr-hit" type="button" data-entity="${escapeHtml(entity)}">${content}</button>`
    : content;
}

customElements.define("sleepradar-card", SleepradarCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "sleepradar-card",
  name: "SleepRadar Card",
  description: "Live sleep phase, heart rate, and breathing from the SleepRadar app.",
});
