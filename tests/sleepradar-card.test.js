const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const NOW = "2026-07-03T08:00:40.000Z";
const RealDate = Date;

class MockDate extends RealDate {
  static now() {
    return RealDate.parse(NOW);
  }
}

class MockHTMLElement {
  attachShadow() {
    this.shadowRoot = { innerHTML: "" };
    return this.shadowRoot;
  }
}

const registeredElements = new Map();
const context = {
  Date: MockDate,
  HTMLElement: MockHTMLElement,
  clearInterval() {},
  console,
  customElements: {
    define(name, klass) {
      registeredElements.set(name, klass);
    },
  },
  setInterval() {
    return 1;
  },
  window: { customCards: [] },
};

vm.createContext(context);
vm.runInContext(
  fs.readFileSync(path.join(__dirname, "../card/sleepradar-card.js"), "utf8"),
  context,
  { filename: "card/sleepradar-card.js" }
);

const Card = registeredElements.get("sleepradar-card");
assert.ok(Card, "sleepradar-card custom element should register");

function render(states, config = {}) {
  const card = new Card();
  card.setConfig(config);
  card.hass = { states };
  return card.shadowRoot.innerHTML;
}

function assertValuesHidden(html, values, message) {
  for (const value of values) {
    assert.doesNotMatch(
      html,
      new RegExp(`(^|\\D)${value}(\\D|$)`),
      `${message}: ${value} must not appear anywhere in the rendered card`
    );
  }
}

function defaultStates({ sleepState, heartRate = "54", respirationRate = "11", updated }) {
  return {
    "sensor.aqara_fp2_sleep_sleep_state": {
      state: sleepState,
      last_updated: updated,
    },
    "sensor.aqara_fp2_sleep_heart_rate": {
      state: heartRate,
      last_updated: updated,
    },
    "sensor.aqara_fp2_sleep_respiration_rate": {
      state: respirationRate,
      last_updated: updated,
    },
  };
}

function withOccupancy(states, state, updated = "2026-07-03T08:00:00.000Z") {
  return {
    ...states,
    "sensor.example_bed_status": {
      state,
      last_updated: updated,
    },
  };
}

const occupancyConfig = {
  bed_occupancy: {
    entity: "sensor.example_bed_status",
    occupied_states: ["Schlafend", "Wach"],
  },
};

assert.throws(
  () => new Card().setConfig({ bed_occupancy: null }),
  /bed_occupancy must be a mapping/
);
assert.throws(
  () => new Card().setConfig({ bed_occupancy: {} }),
  /bed_occupancy\.entity is required/
);
assert.throws(
  () =>
    new Card().setConfig({
      bed_occupancy: {
        entity: "sensor.example_bed_status",
        occupied_states: [],
      },
    }),
  /bed_occupancy\.occupied_states must be a non-empty array/
);
for (const invalidOccupiedStates of [[null], [1], [""], ["   "]]) {
  assert.throws(
    () =>
      new Card().setConfig({
        bed_occupancy: {
          entity: "sensor.example_bed_status",
          occupied_states: invalidOccupiedStates,
        },
      }),
    /bed_occupancy\.occupied_states must contain non-empty strings/
  );
}
assert.throws(
  () =>
    new Card().setConfig({
      bed_occupancy: {
        entity: "sensor.example_bed_status",
        occupied_states: "Wach",
      },
    }),
  /bed_occupancy\.occupied_states must be a non-empty array/
);
assert.throws(
  () =>
    new Card().setConfig({
      bed_occupancy: {
        entity: "sensor.example_bed_status",
      },
    }),
  /bed_occupancy\.occupied_states is required for non-binary entities/
);

// --- A gate that can never close is not a gate --------------------------------
// Both of these passed shape validation before and produced a permanently-open
// gate that rendered retained vitals over an empty bed.
assert.throws(
  () =>
    new Card().setConfig({
      bed_occupancy: {
        entity: "binary_sensor.bed_occupied",
        occupied_states: ["on", "off"],
      },
    }),
  /must not contain both 'on' and 'off'/,
  "listing both binary states leaves no state that means the bed is empty"
);
for (const reservedState of ["unknown", "unavailable", "none", "None"]) {
  assert.throws(
    () =>
      new Card().setConfig({
        bed_occupancy: {
          entity: "sensor.example_bed_status",
          occupied_states: ["Wach", reservedState],
        },
      }),
    /must not contain unknown, unavailable, none, or empty states/,
    `occupied_states must reject the reserved state ${reservedState}`
  );
}

// --- Entity overrides cannot smuggle a self-referential gate -------------------
// A non-string override is not strictly equal to the gate string, but coerces
// to the same key on a hass.states lookup, so it must be rejected outright.
for (const coercibleOverride of [
  ["sensor.aqara_fp2_sleep_sleep_state"],
  { toString: () => "sensor.aqara_fp2_sleep_sleep_state" },
  42,
]) {
  assert.throws(
    () =>
      new Card().setConfig({
        entities: { sleep_state: coercibleOverride },
        bed_occupancy: {
          entity: "sensor.aqara_fp2_sleep_sleep_state",
          occupied_states: ["on"],
        },
      }),
    /entities overrides must be entity id strings/,
    "a non-string entity override must be rejected, not coerced"
  );
}
assert.throws(
  () =>
    new Card().setConfig({
      entities: { sleep_state: "sensor.custom_sleep_state " },
      bed_occupancy: {
        entity: " sensor.custom_sleep_state ",
        occupied_states: ["on"],
      },
    }),
  /bed_occupancy\.entity must be independent/,
  "the self-reference check must normalize whitespace on both sides"
);
for (const sourceEntity of [
  "sensor.aqara_fp2_sleep_sleep_state",
  "sensor.aqara_fp2_sleep_heart_rate",
  "sensor.aqara_fp2_sleep_respiration_rate",
]) {
  assert.throws(
    () =>
      new Card().setConfig({
        bed_occupancy: {
          entity: sourceEntity,
          occupied_states: ["on"],
        },
      }),
    /bed_occupancy\.entity must be independent/,
    `direct gate self-reference must reject ${sourceEntity}`
  );
}
assert.throws(
  () =>
    new Card().setConfig({
      entities: {
        sleep_state: "sensor.custom_sleep_state",
      },
      bed_occupancy: {
        entity: "sensor.custom_sleep_state",
        occupied_states: ["occupied"],
      },
    }),
  /bed_occupancy\.entity must be independent/,
  "gate self-reference must honor entity overrides"
);

const noData = render({});
assert.match(noData, /No data from sensor\.aqara_fp2_sleep_sleep_state yet/);
assert.match(noData, /Home\s+Assistant pins entity ids when it first creates them/);
assert.match(noData, /entities: option/);

const freshOutOfBed = render(
  defaultStates({
    sleepState: "0",
    updated: "2026-07-03T08:00:00.000Z",
  })
);
assert.match(freshOutOfBed, /Out of bed/);
assert.match(freshOutOfBed, /Paused out of bed/);
assert.match(freshOutOfBed, /not currently measured/);
assert.match(freshOutOfBed, /sr-badge-neutral">not measuring/);
assert.doesNotMatch(
  freshOutOfBed,
  />54\s*<span class="sr-unit">bpm<\/span>/,
  "out-of-bed card must not render retained heart rate as live"
);
assert.doesNotMatch(
  freshOutOfBed,
  />11\s*<span class="sr-unit">br\/min<\/span>/,
  "out-of-bed card must not render retained breathing as live"
);

const freshInBed = render(
  defaultStates({
    sleepState: "3",
    updated: "2026-07-03T08:00:00.000Z",
  })
);
assert.match(freshInBed, /REM/);
assert.match(freshInBed, /Live now/);
assert.match(freshInBed, />54\s*<span class="sr-unit">bpm<\/span>/);
assert.match(freshInBed, />11\s*<span class="sr-unit">br\/min<\/span>/);

const noOccupancyConfig = render(
  defaultStates({
    sleepState: "2",
    heartRate: "69",
    respirationRate: "21",
    updated: "2026-07-03T08:00:00.000Z",
  })
);
assert.match(noOccupancyConfig, /Awake in bed — heart 69 bpm, breathing 21 br\/min/);
assert.match(noOccupancyConfig, /Awake label is kept for compatibility/);
assert.match(noOccupancyConfig, />69\s*<span class="sr-unit">bpm<\/span>/);
assert.match(noOccupancyConfig, />21\s*<span class="sr-unit">br\/min<\/span>/);

const ghostVitalsBlocked = render(
  withOccupancy(
    defaultStates({
      sleepState: "2",
      heartRate: "98765",
      respirationRate: "87654",
      updated: "2026-07-03T08:00:00.000Z",
    }),
    "Leer"
  ),
  occupancyConfig
);
assert.match(ghostVitalsBlocked, /Out of bed/);
assert.match(ghostVitalsBlocked, /sr-badge sr-badge-neutral">not measuring/);
assert.match(ghostVitalsBlocked, /Paused out of bed/);
assert.equal(
  (ghostVitalsBlocked.match(/<div class="sr-stat-value">—/g) || []).length,
  2,
  "an empty occupancy gate must render dashes for both vitals"
);
assertValuesHidden(
  ghostVitalsBlocked,
  ["98765", "87654"],
  "an empty occupancy gate must hide retained vitals"
);

const emptyBedWithoutAqaraData = render(
  withOccupancy({}, "Leer"),
  occupancyConfig
);
assert.match(emptyBedWithoutAqaraData, /Out of bed/);
assert.doesNotMatch(emptyBedWithoutAqaraData, /No data from/);

// --- The blocked card must not swallow sleep-state health ---------------------
// The bed is empty most of the day, so this is the dominant display state. A
// missing entity id or a dead poller must not look like a healthy empty bed.
assert.match(
  emptyBedWithoutAqaraData,
  /class="sr-badge">no sensor data/,
  "a closed gate with no sleep-state entity must still report the missing feed"
);
assert.match(
  emptyBedWithoutAqaraData,
  /not reporting a sleep state/,
  "the blocked card must name the missing sleep-state feed in its footer"
);
assert.doesNotMatch(
  emptyBedWithoutAqaraData,
  /<div class="sr-badge sr-badge-neutral">/,
  "a dead sleep-state feed must not render the benign not-measuring badge"
);

const emptyBedWithStaleAqaraData = render(
  withOccupancy(
    defaultStates({
      sleepState: "3",
      heartRate: "98765",
      respirationRate: "87654",
      updated: "2026-07-03T07:56:00.000Z",
    }),
    "Leer"
  ),
  occupancyConfig
);
assert.match(
  emptyBedWithStaleAqaraData,
  /class="sr-badge">stale/,
  "a closed gate with a stale sleep-state feed must surface the stale badge"
);
assertValuesHidden(
  emptyBedWithStaleAqaraData,
  ["98765", "87654"],
  "a stale blocked card must still hide retained vitals"
);
// A healthy empty bed stays calm — the fault badges above must not fire here.
assert.match(
  ghostVitalsBlocked,
  /<div class="sr-badge sr-badge-neutral">not measuring/,
  "a healthy empty bed keeps the neutral badge"
);

const occupiedCodeTwo = render(
  withOccupancy(
    defaultStates({
      sleepState: "2",
      heartRate: "69",
      respirationRate: "21",
      updated: "2026-07-03T08:00:00.000Z",
    }),
    "Wach"
  ),
  occupancyConfig
);
assert.match(
  occupiedCodeTwo,
  /In bed — stage unknown; heart 69 bpm, breathing 21 br\/min/
);
assert.match(occupiedCodeTwo, /unverified sleep code/);
assert.doesNotMatch(occupiedCodeTwo, /Awake/);
assert.match(occupiedCodeTwo, />69\s*<span class="sr-unit">bpm<\/span>/);
assert.match(occupiedCodeTwo, />21\s*<span class="sr-unit">br\/min<\/span>/);

const occupiedWithOldGateTimestamp = render(
  withOccupancy(
    defaultStates({
      sleepState: "2",
      heartRate: "69",
      respirationRate: "21",
      updated: "2026-07-03T08:00:00.000Z",
    }),
    "Wach",
    "2020-01-01T00:00:00.000Z"
  ),
  occupancyConfig
);
assert.match(
  occupiedWithOldGateTimestamp,
  /In bed — stage unknown; heart 69 bpm, breathing 21 br\/min/,
  "occupancy availability/state is trusted without imposing an age timeout"
);

const occupiedCodeOne = render(
  withOccupancy(
    defaultStates({
      sleepState: "1",
      heartRate: "68",
      respirationRate: "20",
      updated: "2026-07-03T08:00:00.000Z",
    }),
    "Wach"
  ),
  occupancyConfig
);
assert.match(
  occupiedCodeOne,
  /In bed — stage unknown; heart 68 bpm, breathing 20 br\/min/
);
assert.doesNotMatch(occupiedCodeOne, /Awake/);
assert.match(occupiedCodeOne, />68\s*<span class="sr-unit">bpm<\/span>/);
assert.match(occupiedCodeOne, />20\s*<span class="sr-unit">br\/min<\/span>/);

const occupiedCodeZero = render(
  withOccupancy(
    defaultStates({
      sleepState: "0",
      heartRate: "98765",
      respirationRate: "87654",
      updated: "2026-07-03T08:00:00.000Z",
    }),
    "Wach"
  ),
  occupancyConfig
);
assert.match(occupiedCodeZero, /<div class="sr-phase">In bed/);
assert.match(occupiedCodeZero, /occupancy confirmed/);
assert.match(occupiedCodeZero, /sr-badge sr-badge-neutral">not measuring/);
assert.match(occupiedCodeZero, /not reporting a usable stage or live vitals/);
assert.doesNotMatch(occupiedCodeZero, /Out of bed/);
assert.equal(
  (occupiedCodeZero.match(/<div class="sr-stat-value">—/g) || []).length,
  2,
  "occupied code 0 must render dashes for both vitals"
);
assertValuesHidden(
  occupiedCodeZero,
  ["98765", "87654"],
  "occupied code 0 must hide sensor-reported vitals"
);

const missingOccupancy = render(
  defaultStates({
    sleepState: "2",
    heartRate: "69",
    respirationRate: "21",
    updated: "2026-07-03T08:00:00.000Z",
  }),
  occupancyConfig
);
assert.match(missingOccupancy, /Occupancy unknown/);
// A broken gate is a fault, not a calm empty bed: it must not wear the neutral
// badge that means "the bed is empty and that is fine".
assert.match(missingOccupancy, /class="sr-badge">occupancy fault/);
assert.doesNotMatch(
  missingOccupancy,
  /<div class="sr-badge sr-badge-neutral">/,
  "a missing occupancy entity must not render the benign not-measuring badge"
);
assert.equal(
  (missingOccupancy.match(/<div class="sr-stat-value">—/g) || []).length,
  2,
  "unknown occupancy must render dashes for both vitals"
);
assertValuesHidden(
  missingOccupancy,
  ["69", "21"],
  "unknown occupancy must hide retained vitals"
);

for (const unavailableState of ["unavailable", "unknown", "None", "none", ""]) {
  const unavailableOccupancy = render(
    withOccupancy(
      defaultStates({
        sleepState: "2",
        heartRate: "69",
        respirationRate: "21",
        updated: "2026-07-03T08:00:00.000Z",
      }),
      unavailableState
    ),
    occupancyConfig
  );
  assert.match(
    unavailableOccupancy,
    /Occupancy unknown/,
    `occupancy state ${JSON.stringify(unavailableState)} must fail closed`
  );
  assert.doesNotMatch(unavailableOccupancy, />69\s*<span class="sr-unit">bpm<\/span>/);
  assert.doesNotMatch(unavailableOccupancy, />21\s*<span class="sr-unit">br\/min<\/span>/);
}

const invalidOccupancy = render(
  withOccupancy(
    defaultStates({
      sleepState: "2",
      heartRate: "69",
      respirationRate: "21",
      updated: "2026-07-03T08:00:00.000Z",
    }),
    1
  ),
  occupancyConfig
);
assert.match(invalidOccupancy, /Occupancy unknown/);
assertValuesHidden(
  invalidOccupancy,
  ["69", "21"],
  "invalid occupancy must hide retained vitals"
);

const wrongCaseOccupancy = render(
  withOccupancy(
    defaultStates({
      sleepState: "2",
      heartRate: "69",
      respirationRate: "21",
      updated: "2026-07-03T08:00:00.000Z",
    }),
    "wach"
  ),
  occupancyConfig
);
assert.match(wrongCaseOccupancy, /Out of bed/);
assertValuesHidden(
  wrongCaseOccupancy,
  ["69", "21"],
  "a non-occupied exact-state mismatch must hide retained vitals"
);

const defaultOnOccupancy = render(
  {
    ...defaultStates({
      sleepState: "3",
      updated: "2026-07-03T08:00:00.000Z",
    }),
    "binary_sensor.bed_occupied": {
      state: "on",
      last_updated: "2026-07-03T08:00:00.000Z",
    },
  },
  {
    bed_occupancy: {
      entity: "binary_sensor.bed_occupied",
    },
  }
);
assert.match(defaultOnOccupancy, />54\s*<span class="sr-unit">bpm<\/span>/);
assert.match(defaultOnOccupancy, />11\s*<span class="sr-unit">br\/min<\/span>/);

const defaultOffOccupancy = render(
  {
    ...defaultStates({
      sleepState: "3",
      updated: "2026-07-03T08:00:00.000Z",
    }),
    "binary_sensor.bed_occupied": {
      state: "off",
      last_updated: "2026-07-03T08:00:00.000Z",
    },
  },
  {
    bed_occupancy: {
      entity: "binary_sensor.bed_occupied",
    },
  }
);
assert.match(defaultOffOccupancy, /Out of bed/);
assert.doesNotMatch(defaultOffOccupancy, />54\s*<span class="sr-unit">bpm<\/span>/);

const signatureCard = new Card();
signatureCard.setConfig(occupancyConfig);
signatureCard.hass = {
  states: withOccupancy(
    defaultStates({
      sleepState: "2",
      updated: "2026-07-03T08:00:00.000Z",
    }),
    "Wach",
    "2026-07-03T08:00:01.000Z"
  ),
};
assert.match(signatureCard._lastSignature, /Wach/);
assert.match(signatureCard._lastSignature, /2026-07-03T08:00:01\.000Z/);
assert.match(signatureCard.shadowRoot.innerHTML, />54\s*<span class="sr-unit">bpm<\/span>/);

signatureCard.hass = {
  states: withOccupancy(
    defaultStates({
      sleepState: "2",
      updated: "2026-07-03T08:00:00.000Z",
    }),
    "Leer",
    "2026-07-03T08:00:02.000Z"
  ),
};
assert.match(signatureCard._lastSignature, /Leer/);
assert.match(signatureCard._lastSignature, /2026-07-03T08:00:02\.000Z/);
assert.match(signatureCard.shadowRoot.innerHTML, /Out of bed/);
assert.doesNotMatch(
  signatureCard.shadowRoot.innerHTML,
  />54\s*<span class="sr-unit">bpm<\/span>/
);

const staleOccupied = render(
  withOccupancy(
    defaultStates({
      sleepState: "3",
      updated: "2026-07-03T07:56:00.000Z",
    }),
    "Schlafend"
  ),
  occupancyConfig
);
assert.match(staleOccupied, /stale/);
assert.doesNotMatch(staleOccupied, />54\s*<span class="sr-unit">bpm<\/span>/);
assert.doesNotMatch(staleOccupied, />11\s*<span class="sr-unit">br\/min<\/span>/);

const staleInBed = render(
  defaultStates({
    sleepState: "3",
    updated: "2026-07-03T07:56:00.000Z",
  })
);
assert.match(staleInBed, /stale/);
assert.match(staleInBed, /Status stale/);
assert.doesNotMatch(
  staleInBed,
  />54\s*<span class="sr-unit">bpm<\/span>/,
  "stale card must not render retained heart rate as live"
);
assert.doesNotMatch(
  staleInBed,
  />11\s*<span class="sr-unit">br\/min<\/span>/,
  "stale card must not render retained breathing as live"
);

const staleOutOfBed = render(
  defaultStates({
    sleepState: "0",
    updated: "2026-07-03T07:56:00.000Z",
  })
);
assert.match(staleOutOfBed, /stale/);
assert.match(staleOutOfBed, /last reported/);
assert.match(staleOutOfBed, /Status stale/);
assert.match(staleOutOfBed, /Status is stale/);
assert.match(staleOutOfBed, /class="sr-badge">stale/);
assert.doesNotMatch(staleOutOfBed, /Paused out of bed/);
assert.doesNotMatch(staleOutOfBed, /bed is empty/);
assert.doesNotMatch(staleOutOfBed, /sr-badge-neutral">stale/);

const freshUnknownCode = render(
  defaultStates({
    sleepState: "9",
    updated: "2026-07-03T08:00:00.000Z",
  })
);
assert.match(freshUnknownCode, /Unknown/);
assert.match(freshUnknownCode, /unmapped code/);
assert.match(freshUnknownCode, /mapped in-bed sleep state/);
assert.doesNotMatch(freshUnknownCode, /measured directly by the sensor/);
assert.doesNotMatch(
  freshUnknownCode,
  />54\s*<span class="sr-unit">bpm<\/span>/,
  "unmapped sleep code must not render retained heart rate as live"
);

const futureDatedInBed = render(
  defaultStates({
    sleepState: "3",
    updated: "2026-07-03T08:01:00.000Z",
  })
);
assert.match(futureDatedInBed, /Freshness unknown/);
assert.doesNotMatch(
  futureDatedInBed,
  />54\s*<span class="sr-unit">bpm<\/span>/,
  "unknown freshness must not render retained heart rate as live"
);
assert.doesNotMatch(
  futureDatedInBed,
  />11\s*<span class="sr-unit">br\/min<\/span>/,
  "unknown freshness must not render retained breathing as live"
);

// --- Occupancy gate config validation edge cases --------------------------

for (const invalidMapping of ["sensor.example_bed_status", 5, [], true, undefined]) {
  assert.throws(
    () => new Card().setConfig({ bed_occupancy: invalidMapping }),
    /bed_occupancy must be a mapping/,
    `bed_occupancy ${JSON.stringify(invalidMapping)} must fail closed as a mapping`
  );
}

for (const invalidEntity of [42, "", "   ", null, {}, ["sensor.x"]]) {
  assert.throws(
    () =>
      new Card().setConfig({
        bed_occupancy: { entity: invalidEntity, occupied_states: ["on"] },
      }),
    /bed_occupancy\.entity is required/,
    `bed_occupancy.entity ${JSON.stringify(invalidEntity)} must be rejected`
  );
}

assert.throws(
  () =>
    new Card().setConfig({
      bed_occupancy: {
        entity: "  sensor.aqara_fp2_sleep_heart_rate  ",
        occupied_states: ["on"],
      },
    }),
  /bed_occupancy\.entity must be independent/,
  "a padded gate entity must be trimmed before the self-reference check"
);

const mutableOccupiedStates = ["Wach"];
const mutationCard = new Card();
mutationCard.setConfig({
  bed_occupancy: {
    entity: "sensor.example_bed_status",
    occupied_states: mutableOccupiedStates,
  },
});
mutableOccupiedStates.length = 0;
mutableOccupiedStates.push("Leer");
mutationCard.hass = {
  states: withOccupancy(
    defaultStates({ sleepState: "3", updated: "2026-07-03T08:00:00.000Z" }),
    "Wach"
  ),
};
assert.match(
  mutationCard.shadowRoot.innerHTML,
  />54\s*<span class="sr-unit">bpm<\/span>/,
  "occupied_states must be copied so later config mutation cannot flip the gate"
);

// An inverted helper (occupied when the binary sensor is "off") is a real
// wiring shape; the explicit occupied_states list must win over the "on"
// default that binary_sensor entities otherwise get.
const invertedGateConfig = {
  bed_occupancy: { entity: "binary_sensor.bed_empty", occupied_states: ["off"] },
};
function withInvertedGate(state) {
  return {
    ...defaultStates({
      sleepState: "3",
      heartRate: "98765",
      respirationRate: "87654",
      updated: "2026-07-03T08:00:00.000Z",
    }),
    "binary_sensor.bed_empty": {
      state,
      last_updated: "2026-07-03T08:00:00.000Z",
    },
  };
}
const invertedOccupied = render(withInvertedGate("off"), invertedGateConfig);
assert.match(invertedOccupied, />98765\s*<span class="sr-unit">bpm<\/span>/);
assert.match(invertedOccupied, />87654\s*<span class="sr-unit">br\/min<\/span>/);
assert.doesNotMatch(invertedOccupied, /Occupancy unknown/);
const invertedEmpty = render(withInvertedGate("on"), invertedGateConfig);
assert.match(invertedEmpty, /Out of bed/);
assertValuesHidden(
  invertedEmpty,
  ["98765", "87654"],
  "an inverted gate reporting empty must hide retained vitals"
);

// --- Ghost-vitals incident regression -------------------------------------
// tests/fixtures/ghost-vitals-incident.json records ~150 min of continuously
// empty occupancy while the FP2 kept reporting sleep codes 4/5/3 and moving
// heart rates. The gated card must surface neither the stage label nor the
// vitals for any code in that recorded sequence.
const ghostVitalsIncident = JSON.parse(
  fs.readFileSync(path.join(__dirname, "fixtures/ghost-vitals-incident.json"), "utf8")
);
assert.equal(
  ghostVitalsIncident.occupancy.continuous_state,
  "empty",
  "the incident fixture must describe a continuously empty bed"
);
const incidentHeartRate = String(ghostVitalsIncident.heart_rate.maximum_bpm);
const incidentBreathing = String(ghostVitalsIncident.heart_rate.minimum_bpm);
for (const incidentCode of ghostVitalsIncident.sleep_state.reported_codes) {
  const incidentCard = render(
    withOccupancy(
      defaultStates({
        sleepState: String(incidentCode),
        heartRate: incidentHeartRate,
        respirationRate: incidentBreathing,
        updated: "2026-07-03T08:00:00.000Z",
      }),
      "Leer"
    ),
    occupancyConfig
  );
  assert.match(
    incidentCard,
    /Out of bed/,
    `incident code ${incidentCode} must still read as out of bed`
  );
  for (const stageLabel of ["REM", "Light sleep", "Deep sleep"]) {
    assert.doesNotMatch(
      incidentCard,
      new RegExp(stageLabel),
      `incident code ${incidentCode} must not leak the stage label ${stageLabel}`
    );
  }
  assert.equal(
    (incidentCard.match(/<div class="sr-stat-value">—/g) || []).length,
    2,
    `incident code ${incidentCode} must render dashes for both vitals`
  );
  assertValuesHidden(
    incidentCard,
    [incidentHeartRate, incidentBreathing],
    `incident code ${incidentCode} must hide ghost vitals`
  );
}

// --- Gated rendering for codes the gate cannot relabel ---------------------

for (const unmappedState of ["9", "3-bad", "-1"]) {
  const gatedUnmapped = render(
    withOccupancy(
      defaultStates({
        sleepState: unmappedState,
        heartRate: "98765",
        respirationRate: "87654",
        updated: "2026-07-03T08:00:00.000Z",
      }),
      "Wach"
    ),
    occupancyConfig
  );
  assert.match(
    gatedUnmapped,
    /<div class="sr-phase">Unknown/,
    `gated unmapped state ${unmappedState} must render as Unknown`
  );
  assert.match(gatedUnmapped, /unmapped code/);
  assert.match(gatedUnmapped, /cannot map this sleep state yet/);
  assert.doesNotMatch(
    gatedUnmapped,
    /Out of bed/,
    `gated unmapped state ${unmappedState} must never claim an empty bed`
  );
  assertValuesHidden(
    gatedUnmapped,
    ["98765", "87654"],
    `gated unmapped state ${unmappedState} must hide vitals`
  );
}

for (const missingSleepState of [undefined, "unavailable", "None"]) {
  const states =
    missingSleepState === undefined
      ? {}
      : defaultStates({
          sleepState: missingSleepState,
          heartRate: "98765",
          respirationRate: "87654",
          updated: "2026-07-03T08:00:00.000Z",
        });
  const openGateNoData = render(withOccupancy(states, "Wach"), occupancyConfig);
  assert.match(
    openGateNoData,
    /No data from sensor\.aqara_fp2_sleep_sleep_state yet/,
    `an open gate with sleep state ${String(missingSleepState)} must still show onboarding help`
  );
  assertValuesHidden(
    openGateNoData,
    ["98765", "87654"],
    "the onboarding card must not leak retained vitals"
  );
}

const gatedFutureDated = render(
  withOccupancy(
    defaultStates({
      sleepState: "3",
      heartRate: "98765",
      respirationRate: "87654",
      updated: "2026-07-03T08:01:00.000Z",
    }),
    "Wach"
  ),
  occupancyConfig
);
assert.match(gatedFutureDated, /Freshness unknown/);
assert.match(gatedFutureDated, /last reported/);
assertValuesHidden(
  gatedFutureDated,
  ["98765", "87654"],
  "confirmed occupancy must not override an unusable sleep-state timestamp"
);

const gatedCodeZeroStatus = render(
  withOccupancy(
    defaultStates({ sleepState: "0", updated: "2026-07-03T08:00:00.000Z" }),
    "Wach"
  ),
  occupancyConfig
);
assert.match(gatedCodeZeroStatus, /Not measuring/);
assert.doesNotMatch(
  gatedCodeZeroStatus,
  /Paused out of bed/,
  "a confirmed-occupancy code 0 must not claim vitals are paused out of bed"
);
assert.match(gatedCodeZeroStatus, /Independent occupancy confirms someone is in bed/);

for (const [gatedCode, gatedLabel] of [
  ["3", "REM"],
  ["4", "Light sleep"],
  ["5", "Deep sleep"],
]) {
  const gatedStage = render(
    withOccupancy(
      defaultStates({ sleepState: gatedCode, updated: "2026-07-03T08:00:00.000Z" }),
      "Schlafend"
    ),
    occupancyConfig
  );
  assert.match(
    gatedStage,
    new RegExp(`<div class="sr-phase">${gatedLabel}`),
    `gated code ${gatedCode} must keep the ${gatedLabel} stage label`
  );
  assert.match(gatedStage, /the sensor's best guess/);
  assert.match(gatedStage, /sensor-reported measurements/);
  assert.match(gatedStage, /Live now/);
  assert.match(
    gatedStage,
    new RegExp(`${gatedLabel} — heart 54 bpm, breathing 11 br\\/min`)
  );
}

// The ungated footer wording changed from "measured directly by the sensor"
// to "sensor-reported measurements"; pin it so it cannot drift back.
const ungatedDeepSleep = render(
  defaultStates({ sleepState: "5", updated: "2026-07-03T08:00:00.000Z" })
);
assert.match(ungatedDeepSleep, /sensor-reported measurements/);
assert.match(ungatedDeepSleep, /Sleep stage is the device's best guess/);
assert.doesNotMatch(
  ungatedDeepSleep,
  /measured directly by the sensor/,
  "the ungated footer must not reassert direct measurement"
);

const gatedStaleCodeZero = render(
  withOccupancy(
    defaultStates({ sleepState: "0", updated: "2026-07-03T07:56:00.000Z" }),
    "Wach"
  ),
  occupancyConfig
);
assert.match(gatedStaleCodeZero, /class="sr-badge">stale/);
assert.doesNotMatch(
  gatedStaleCodeZero,
  /not measuring/,
  "a stale gated card must show the stale badge, not the neutral one"
);
assert.match(gatedStaleCodeZero, /<div class="sr-phase">In bed/);
assert.match(gatedStaleCodeZero, /last reported/);
assert.doesNotMatch(gatedStaleCodeZero, /Out of bed/);

// --- Blocked-card header contract -----------------------------------------

assert.match(
  missingOccupancy,
  /sr-eyebrow">CURRENT STATUS<\/div>/,
  "a missing gate entity leaves the blocked header without a timestamp segment"
);
assert.doesNotMatch(
  ghostVitalsBlocked,
  /CURRENT STATUS · (?:Updated|Stale|Freshness)/,
  "the blocked card reports the gate timestamp, not sleep-state freshness"
);
assert.match(ghostVitalsBlocked, /sr-eyebrow">CURRENT STATUS · /);

// --- Gate recovery and the cheap re-render guard ---------------------------

const recoveryCard = new Card();
recoveryCard.setConfig(occupancyConfig);
recoveryCard.hass = {
  states: withOccupancy(
    defaultStates({ sleepState: "3", updated: "2026-07-03T08:00:00.000Z" }),
    "Leer",
    "2026-07-03T07:59:00.000Z"
  ),
};
assert.match(recoveryCard.shadowRoot.innerHTML, /Out of bed/);
recoveryCard.hass = {
  states: withOccupancy(
    defaultStates({ sleepState: "3", updated: "2026-07-03T08:00:00.000Z" }),
    "Schlafend",
    "2026-07-03T08:00:05.000Z"
  ),
};
assert.doesNotMatch(
  recoveryCard.shadowRoot.innerHTML,
  /Out of bed/,
  "reopening the gate must clear the blocked card"
);
assert.match(
  recoveryCard.shadowRoot.innerHTML,
  />54\s*<span class="sr-unit">bpm<\/span>/,
  "reopening the gate must restore live vitals"
);

const guardCard = new Card();
guardCard.setConfig(occupancyConfig);
const guardStates = withOccupancy(
  defaultStates({ sleepState: "3", updated: "2026-07-03T08:00:00.000Z" }),
  "Schlafend"
);
guardCard.hass = { states: guardStates };
guardCard.shadowRoot.innerHTML = "SENTINEL";
guardCard.hass = { states: guardStates };
assert.equal(
  guardCard.shadowRoot.innerHTML,
  "SENTINEL",
  "an unchanged gated state must not repaint the card"
);
guardCard.hass = {
  states: withOccupancy(
    defaultStates({ sleepState: "3", updated: "2026-07-03T08:00:00.000Z" }),
    "Leer"
  ),
};
assert.notEqual(
  guardCard.shadowRoot.innerHTML,
  "SENTINEL",
  "a gate-only change must invalidate the re-render guard"
);
assert.match(guardCard.shadowRoot.innerHTML, /Out of bed/);
