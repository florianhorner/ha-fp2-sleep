const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const NOW = "2026-07-03T08:00:40.000Z";
const RealDate = Date;
let clockMs = RealDate.parse(NOW);
let nextIntervalId = 1;
const intervals = new Map();

class MockDate extends RealDate {
  static now() {
    return clockMs;
  }
}

class MockHTMLElement {
  attachShadow() {
    let html = "";
    this.shadowRoot = {
      writes: 0,
      get innerHTML() { return html; },
      set innerHTML(value) { html = value; this.writes += 1; },
    };
    return this.shadowRoot;
  }
}

const registeredElements = new Map();
const context = {
  Date: MockDate,
  HTMLElement: MockHTMLElement,
  clearInterval(id) {
    intervals.delete(id);
  },
  console,
  customElements: {
    define(name, klass) {
      registeredElements.set(name, klass);
    },
  },
  setInterval(callback, delay) {
    const id = nextIntervalId++;
    intervals.set(id, { callback, delay, nextAt: clockMs + delay });
    return id;
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

// Read rendered semantics, excluding selectors in the style element. Otherwise
// a data-phase selector could make an inactive phase appear to pass a test.
function markup(html) {
  return html.replace(/<style>[\s\S]*?<\/style>/g, "");
}

function heading(html) {
  const match = markup(html).match(/<h3\b[^>]*>([\s\S]*?)<\/h3>/);
  assert.ok(match, "a readout must have a semantic phase heading");
  return match[1].replace(/<[^>]*>/g, "").trim();
}

function metric(html, label) {
  const blocks = [...markup(html).matchAll(/<div class="sr-stat">([\s\S]*?)(?=<div class="sr-stat">|<div class="sr-footer">)/g)];
  const block = blocks.find((match) => match[1].includes(`>${label}</div>`));
  assert.ok(block, `the ${label} metric must be labeled`);
  return block[1];
}

function assertNeutral(html, message) {
  const body = markup(html);
  assert.doesNotMatch(body, /data-phase="(?:deep|light|rem)"/, message);
  if (body.includes('class="sr-card"')) {
    assert.match(body, /data-phase="unknown"/, message);
  }
}

function advanceClock(milliseconds) {
  const target = clockMs + milliseconds;
  while (true) {
    const due = [...intervals.values()]
      .filter((timer) => timer.nextAt <= target)
      .sort((a, b) => a.nextAt - b.nextAt)[0];
    if (!due) break;
    clockMs = due.nextAt;
    due.nextAt += due.delay;
    due.callback();
  }
  clockMs = target;
}

function assertValuesHidden(html, values, message) {
  for (const value of values) {
    assert.doesNotMatch(
      markup(html),
      new RegExp(`(^|\\D)${value}(\\D|$)`),
      `${message}: ${value} must not appear anywhere in the rendered markup`
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
assert.match(freshOutOfBed, /hidden while the bed is empty/);
assert.match(freshOutOfBed, /FP2 can retain its last in-bed values/);
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
assert.doesNotMatch(freshInBed, /Live now/);
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
assert.equal(heading(noOccupancyConfig), "Awake");
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
  /class="sr-badge sr-badge-neutral">/,
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
  /class="sr-badge sr-badge-neutral">not measuring/,
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
assert.equal(heading(occupiedCodeTwo), "In bed — stage unknown");
assert.match(occupiedCodeTwo, /does not establish a wake or stage label/);
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
assert.equal(
  heading(occupiedWithOldGateTimestamp),
  "In bed — stage unknown",
  "occupancy availability/state is trusted without imposing an age timeout"
);
assert.match(occupiedWithOldGateTimestamp, />69\s*<span class="sr-unit">bpm<\/span>/);
assert.match(occupiedWithOldGateTimestamp, />21\s*<span class="sr-unit">br\/min<\/span>/);

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
assert.equal(heading(occupiedCodeOne), "In bed — stage unknown");
assert.match(occupiedCodeOne, /does not establish a wake or stage label/);
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
assert.equal(heading(occupiedCodeZero), "In bed");
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
  /class="sr-badge sr-badge-neutral">/,
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
assert.match(staleOutOfBed, /Stale 4 min ago/);
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
// The fixture is a sanitized aggregate and records no respiration figures, so
// the breathing sentinel reuses the heart-rate range's other end. Both values
// only ever feed "this must not appear anywhere in the render" assertions —
// nothing here claims the FP2 reported them as a breathing rate.
const incidentHeartRate = String(ghostVitalsIncident.heart_rate.maximum_bpm);
const incidentBreathingSentinel = String(
  ghostVitalsIncident.heart_rate.minimum_bpm
);
for (const incidentCode of ghostVitalsIncident.sleep_state.reported_codes) {
  const incidentCard = render(
    withOccupancy(
      defaultStates({
        sleepState: String(incidentCode),
        heartRate: incidentHeartRate,
        respirationRate: incidentBreathingSentinel,
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
    [incidentHeartRate, incidentBreathingSentinel],
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
  assert.equal(
    heading(gatedUnmapped),
    "Unknown",
    `gated unmapped state ${unmappedState} must render as Unknown`
  );
  assert.match(gatedUnmapped, /unmapped code/);
  assert.match(gatedUnmapped, /mapped in-bed sleep state before showing live vitals/);
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

for (const [gatedCode, gatedLabel, phaseKind] of [
  ["3", "REM", "rem"],
  ["4", "Light sleep", "light"],
  ["5", "Deep sleep", "deep"],
]) {
  const gatedStage = render(
    withOccupancy(
      defaultStates({ sleepState: gatedCode, updated: "2026-07-03T08:00:00.000Z" }),
      "Schlafend"
    ),
    occupancyConfig
  );
  assert.equal(
    heading(gatedStage),
    gatedLabel,
    `gated code ${gatedCode} must keep the ${gatedLabel} stage label`
  );
  assert.match(markup(gatedStage), new RegExp(`data-phase="${phaseKind}"`));
  assert.match(
    markup(gatedStage),
    /<h3[^>]*><span class="sr-phase-mark" aria-hidden="true"><\/span>/,
    "the redundant shape is decorative; assistive technology reads the literal phase name"
  );
  assert.equal((gatedStage.match(/the sensor's best guess/g) || []).length, 1);
  assert.match(gatedStage, /class="sr-caption">the sensor's best guess<\/div>/);
  assert.match(gatedStage, /Sensor-reported vitals/);
  assert.doesNotMatch(gatedStage, /Live now/);
  assert.match(gatedStage, />54\s*<span class="sr-unit">bpm<\/span>/);
  assert.match(gatedStage, />11\s*<span class="sr-unit">br\/min<\/span>/);
}

// Compact provenance must still distinguish sensor-reported vitals from the
// estimated stage, without repeating the estimate in the footer.
const ungatedDeepSleep = render(
  defaultStates({ sleepState: "5", updated: "2026-07-03T08:00:00.000Z" })
);
assert.match(ungatedDeepSleep, /Sensor-reported vitals/);
assert.equal((ungatedDeepSleep.match(/the sensor's best guess/g) || []).length, 1);
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
assert.match(gatedStaleCodeZero, /Stale 4 min ago/);
assert.doesNotMatch(
  gatedStaleCodeZero,
  /not measuring/,
  "a stale gated card must show stale freshness, not a not-measuring badge"
);
assert.equal(heading(gatedStaleCodeZero), "In bed");
assert.match(gatedStaleCodeZero, /last reported/);
assert.doesNotMatch(gatedStaleCodeZero, /Out of bed/);

// --- Blocked-card header contract -----------------------------------------

assert.doesNotMatch(
  missingOccupancy,
  /<time>/,
  "a missing gate entity leaves the blocked header without a timestamp segment"
);
assert.doesNotMatch(
  markup(ghostVitalsBlocked),
  /(?:Updated|Stale|Freshness)/,
  "the blocked card reports the gate timestamp, not sleep-state freshness"
);
const gateTime = new RealDate("2026-07-03T08:00:00.000Z")
  .toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
assert.ok(ghostVitalsBlocked.includes(`<time>${gateTime}</time>`));
assert.doesNotMatch(ghostVitalsBlocked, /CURRENT STATUS/);

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

// --- connection problem -----------------------------------------------------
//
// The failure this covers: an eight-hour Aqara outage where the app detected
// the cause on the first poll, and the card still told the user to go check
// their entity ids. When the app has published a reason, the card must say it.

function withProblem(states, { state = "on", cause } = {}) {
  return {
    ...states,
    "binary_sensor.aqara_fp2_sleep_connection_problem": {
      state,
      last_updated: "2026-07-03T08:00:00.000Z",
      attributes: cause === undefined ? {} : { cause },
    },
  };
}

const outageCause =
  "Aqara didn't accept SleepRadar's sign-in. What to do: check aqara_password, " +
  "then restart the app. Technical details: Aqara code 810: Password incorrect.";
const outageStates = withProblem(
  defaultStates({ sleepState: "unavailable", updated: NOW }),
  { cause: outageCause }
);

const outageHtml = render(outageStates);
assert.match(
  outageHtml,
  /Aqara didn(?:'|&#39;|&#x27;)t accept SleepRadar(?:'|&#39;|&#x27;)s sign-in/,
  "the card must show the app's reported cause for an outage"
);
assert.doesNotMatch(
  outageHtml,
  /check Developer Tools/,
  "a known outage must not send the user hunting for a wrong entity id"
);

// Without the diagnostic entity (older app, renamed entity) nothing changes.
const legacyHtml = render(defaultStates({ sleepState: "unavailable", updated: NOW }));
assert.match(
  legacyHtml,
  /No data from sensor\.aqara_fp2_sleep_sleep_state yet/,
  "without the diagnostic entity the card keeps its original empty state"
);

// Problem flag off means the entity is healthy; do not hijack the empty state.
const clearedHtml = render(
  withProblem(defaultStates({ sleepState: "unavailable", updated: NOW }), {
    state: "off",
    cause: outageCause,
  })
);
assert.match(
  clearedHtml,
  /No data from sensor\.aqara_fp2_sleep_sleep_state yet/,
  "a cleared problem flag must not render a stale cause"
);

// Flag set but no cause text: fall back to naming the likeliest cause.
const causelessHtml = render(
  withProblem(defaultStates({ sleepState: "unavailable", updated: NOW }))
);
assert.match(
  causelessHtml,
  /cannot reach the Aqara cloud/,
  "a problem without a cause attribute still explains itself"
);

// The cause is user-controlled text reaching innerHTML; it must be escaped.
const injectionHtml = render(
  withProblem(defaultStates({ sleepState: "unavailable", updated: NOW }), {
    cause: '<img src=x onerror="alert(1)">',
  })
);
assert.doesNotMatch(
  injectionHtml,
  /<img src=x/,
  "the cause attribute must be html-escaped before it reaches innerHTML"
);
assert.match(injectionHtml, /&lt;img src=x/);

// An outage freezes every vitals sensor by definition, so the diagnostic
// entity is the only thing that changes. It must invalidate the re-render
// guard on its own or the card stays pinned on the pre-outage wording.
const problemGuardCard = new Card();
problemGuardCard.setConfig({});
const frozen = defaultStates({ sleepState: "unavailable", updated: NOW });
problemGuardCard.hass = { states: withProblem(frozen, { cause: "first cause" }) };
problemGuardCard.shadowRoot.innerHTML = "SENTINEL";
problemGuardCard.hass = { states: withProblem(frozen, { cause: "first cause" }) };
assert.equal(
  problemGuardCard.shadowRoot.innerHTML,
  "SENTINEL",
  "an unchanged problem state must not repaint the card"
);
problemGuardCard.hass = { states: withProblem(frozen, { cause: "second cause" }) };
assert.match(
  problemGuardCard.shadowRoot.innerHTML,
  /second cause/,
  "a cause-only change must invalidate the re-render guard"
);

// The occupancy-blocked card has its own health line; it must carry the cause
// too, or the most common daytime display state hides the outage.
const blockedHtml = render(
  withProblem(
    withOccupancy(
      defaultStates({ sleepState: "unavailable", updated: NOW }),
      "Leer"
    ),
    { cause: outageCause }
  ),
  occupancyConfig
);
assert.match(
  blockedHtml,
  /Aqara code 810/,
  "the occupancy-blocked card must also report the connection cause"
);

// An explicit override is honoured.
const overrideHtml = render(
  {
    ...defaultStates({ sleepState: "unavailable", updated: NOW }),
    "binary_sensor.custom_problem": {
      state: "on",
      last_updated: NOW,
      attributes: { cause: "custom entity cause" },
    },
  },
  { entities: { connection_problem: "binary_sensor.custom_problem" } }
);
assert.match(
  overrideHtml,
  /custom entity cause/,
  "entities.connection_problem must override the default entity id"
);

// A crashed poller flips the problem flag through the MQTT will straight away,
// but the vitals keep their last value until expire_after (up to 3 poll
// intervals). In that window the card must name the cause rather than report a
// merely "stale" feed.
const staleUpdated = "2026-07-03T07:50:00.000Z"; // ~10 min old at NOW
const staleHtml = render(
  withProblem(
    withOccupancy(
      defaultStates({ sleepState: "3", updated: staleUpdated }),
      "Leer"
    ),
    { cause: "SleepRadar stopped: the app is not running." }
  ),
  occupancyConfig
);
assert.match(
  staleHtml,
  /SleepRadar stopped: the app is not running\./,
  "the stale path must report a known connection cause"
);
assert.doesNotMatch(
  staleHtml,
  /The sleep-state feed is stale\./,
  "a known cause must replace the generic stale note"
);

// Stale with no problem flagged keeps the original wording.
const staleNoProblemHtml = render(
  withOccupancy(defaultStates({ sleepState: "3", updated: staleUpdated }), "Leer"),
  occupancyConfig
);
assert.match(
  staleNoProblemHtml,
  /The sleep-state feed is stale\./,
  "without a flagged problem the stale note is unchanged"
);

// --- Compact presentation: categories and non-color semantics --------------

for (const [code, label, category] of [
  ["3", "REM", "rem"],
  ["4", "Light sleep", "light"],
  ["5", "Deep sleep", "deep"],
]) {
  const html = render(defaultStates({ sleepState: code, updated: NOW }));
  assert.equal(heading(html), label);
  assert.match(markup(html), new RegExp(`data-phase="${category}"`));
  assert.equal((markup(html).match(/class="sr-phase-mark" aria-hidden="true"/g) || []).length, 1);
  assert.match(markup(html), /role="group" aria-label="Sensor-reported vital readings"/);
  assert.equal((html.match(/the sensor's best guess/g) || []).length, 1);
  assert.match(metric(html, "Heart rate"), />54\s*<span class="sr-unit">bpm<\/span>/);
  assert.match(metric(html, "Breathing"), />11\s*<span class="sr-unit">br\/min<\/span>/);
  assert.doesNotMatch(markup(html), /Live now|CURRENT STATUS|class="sr-readout"/);
}

for (const [name, html] of Object.entries({
  noData,
  freshOutOfBed,
  noOccupancyConfig,
  ghostVitalsBlocked,
  emptyBedWithoutAqaraData,
  emptyBedWithStaleAqaraData,
  occupiedCodeZero,
  occupiedCodeOne,
  occupiedCodeTwo,
  missingOccupancy,
  invalidOccupancy,
  staleOccupied,
  staleInBed,
  staleOutOfBed,
  freshUnknownCode,
  futureDatedInBed,
  gatedFutureDated,
  gatedStaleCodeZero,
  outageHtml,
  blockedHtml,
})) {
  assertNeutral(html, `${name} must not look like a fresh reported sleep phase`);
}
for (const malformedCode of ["3-bad", "3.5", "5oops", "-1"]) {
  const html = render(defaultStates({ sleepState: malformedCode, updated: NOW }));
  assert.equal(heading(html), "Unknown");
  assertNeutral(html, `malformed code ${malformedCode} must remain neutral`);
  assert.match(html, /unmapped code/);
  assertValuesHidden(html, ["54", "11"], `malformed code ${malformedCode}`);
}

// Each metric fails independently: an unavailable heart rate must not hide
// breathing, and a missing breathing value must not hide a valid heart rate.
const missingVitalCases = [
  ["missing entity", undefined],
  ["missing state", {}],
  ["unavailable", { state: "unavailable" }],
  ["unknown", { state: "unknown" }],
  ["null", { state: null }],
  ["stringified null", { state: "None" }],
  ["empty", { state: "" }],
  ["nonnumeric", { state: "not-a-number" }],
  ["unit-suffixed", { state: "54 bpm" }],
  ["nonfinite", { state: "Infinity" }],
];
for (const [key, label, otherLabel, healthyValue, healthyUnit] of [
  ["heart_rate", "Heart rate", "Breathing", "11", "br/min"],
  ["respiration_rate", "Breathing", "Heart rate", "54", "bpm"],
]) {
  for (const [caseName, entity] of missingVitalCases) {
    const states = defaultStates({ sleepState: "5", updated: NOW });
    const id = `sensor.aqara_fp2_sleep_${key}`;
    if (entity === undefined) delete states[id];
    else states[id] = { last_updated: NOW, ...entity };
    const html = render(states);
    const failed = metric(html, label);
    const healthy = metric(html, otherLabel);
    assert.match(failed, /class="sr-stat-value">—/, `${label}: ${caseName}`);
    assert.match(failed, /No value reported/, `${label}: ${caseName}`);
    assert.match(
      healthy,
      new RegExp(`>${healthyValue}\\s*<span class="sr-unit">${healthyUnit}</span>`),
      `${label}: ${caseName} must not suppress ${otherLabel}`
    );
    assert.doesNotMatch(healthy, /No value reported|Live now/);
    assert.equal((markup(html).match(/No value reported/g) || []).length, 1);
    assert.equal(heading(html), "Deep sleep");
    assert.match(markup(html), /data-phase="deep"/);
  }
}

// Missing/invalid timestamps must not become epoch dates or fresh phases.
// Confirmed occupancy cannot make an unusable sleep-state timestamp usable.
for (const timestamp of [undefined, null, 0, "", "not-a-date"]) {
  for (const gated of [false, true]) {
    let states = defaultStates({
      sleepState: "5",
      heartRate: "98765",
      respirationRate: "87654",
      updated: timestamp,
    });
    if (timestamp === undefined) {
      delete states["sensor.aqara_fp2_sleep_sleep_state"].last_updated;
    }
    if (gated) states = withOccupancy(states, "Schlafend");
    const html = render(states, gated ? occupancyConfig : {});
    const message = `timestamp ${String(timestamp)}, occupancy ${gated ? "confirmed" : "not configured"}`;
    assertNeutral(html, message);
    assert.equal(heading(html), "Deep sleep", message);
    assert.match(html, /class="sr-caption">last reported<\/div>/, message);
    assert.match(html, /Freshness unknown/, message);
    assert.match(html, /fresh sleep-state timestamp before showing live vitals/, message);
    assert.equal((html.match(/class="sr-stat-status">Freshness unknown/g) || []).length, 2, message);
    assert.doesNotMatch(markup(html), /<time>|the sensor's best guess/, message);
    assertValuesHidden(html, ["98765", "87654"], message);
  }
}

// A theme-only change has to repaint all render paths even when hass.states
// and every sensor object are identical. The Node harness verifies output and
// invalidation; computed contrast and actual shapes are checked in the browser.
for (const [name, states, config] of [
  ["fresh stage", defaultStates({ sleepState: "5", updated: NOW }), {}],
  ["blocked occupancy", withOccupancy(defaultStates({ sleepState: "5", updated: NOW }), "Leer"), occupancyConfig],
  ["missing feed", {}, {}],
  ["reported outage", outageStates, {}],
]) {
  const card = new Card();
  card.setConfig(config);
  card.hass = { states, themes: { darkMode: true } };
  const darkHtml = card.shadowRoot.innerHTML;
  const writes = card.shadowRoot.writes;
  card.hass = { states, themes: { darkMode: true } };
  assert.equal(card.shadowRoot.writes, writes, `${name}: unchanged state/theme skips rendering`);
  card.hass = { states, themes: { darkMode: false } };
  const lightHtml = card.shadowRoot.innerHTML;
  assert.equal(card.shadowRoot.writes, writes + 1, `${name}: dark to light repaints`);
  assert.notEqual(lightHtml, darkHtml, `${name}: theme mode changes palette output`);
  assert.equal(markup(lightHtml), markup(darkHtml), `${name}: theme must not change sensor semantics`);
  card.hass = { states, themes: { darkMode: true } };
  assert.equal(card.shadowRoot.writes, writes + 2, `${name}: light to dark repaints`);
  assert.equal(card.shadowRoot.innerHTML, darkHtml, `${name}: returning to dark restores the palette`);

  card.hass = { states };
  assert.equal(card.shadowRoot.writes, writes + 3, `${name}: unknown theme cannot reuse the dark palette`);
  const unknownHtml = card.shadowRoot.innerHTML;
  for (const kind of ["deep", "light", "rem"]) {
    assert.ok(
      unknownHtml.includes(`var(--sleepradar-${kind}-color, var(--sr-text))`),
      `${name}: absent mode uses inherited phase text ink for ${kind}`
    );
  }
  for (const themes of [{}, { darkMode: null }, { darkMode: "dark" }, { darkMode: 0 }]) {
    card.hass = { states, themes };
    assert.equal(card.shadowRoot.writes, writes + 3, `${name}: nonboolean theme metadata normalizes consistently`);
    assert.equal(card.shadowRoot.innerHTML, unknownHtml);
  }
}

// The timer must retire a once-fresh phase without another hass assignment.
// Exercise both the default threshold and a custom polling interval, including
// disconnect/reconnect so a detached card leaves no scheduled DOM work behind.
for (const pollIntervalSeconds of [60, 20]) {
  clockMs = RealDate.parse(NOW);
  const card = new Card();
  card.setConfig(pollIntervalSeconds === 60 ? {} : { poll_interval_seconds: pollIntervalSeconds });
  const hass = { states: defaultStates({ sleepState: "5", updated: NOW }), themes: { darkMode: true } };
  card.hass = hass;
  card.connectedCallback();
  assert.equal(intervals.size, 1, "a connected card schedules one stale check");
  advanceClock(pollIntervalSeconds * 3000);
  assert.match(markup(card.shadowRoot.innerHTML), /data-phase="deep"/, "the stale threshold remains strictly greater than three polls");
  assert.match(card.shadowRoot.innerHTML, />54\s*<span class="sr-unit">bpm<\/span>/);
  advanceClock(30000);
  assert.strictEqual(card._hass, hass, "the clock transition must not rely on a new hass object");
  assertNeutral(card.shadowRoot.innerHTML, "an elapsed stale timer retires the phase accent");
  assert.match(card.shadowRoot.innerHTML, /class="sr-caption">last reported<\/div>/);
  assert.match(card.shadowRoot.innerHTML, /Status stale/);
  assert.match(card.shadowRoot.innerHTML, /Status is stale\. Check the app and MQTT/);
  assert.doesNotMatch(markup(card.shadowRoot.innerHTML), /the sensor's best guess|class="sr-badge">stale/);
  assertValuesHidden(card.shadowRoot.innerHTML, ["54", "11"], "timer-driven stale transition");

  card.disconnectedCallback();
  assert.equal(intervals.size, 0, "disconnect clears the stale timer");
  const disconnectedWrites = card.shadowRoot.writes;
  advanceClock(60000);
  assert.equal(card.shadowRoot.writes, disconnectedWrites, "a disconnected card performs no timed DOM writes");
  card.connectedCallback();
  assert.equal(intervals.size, 1, "reconnect schedules one replacement timer");
  advanceClock(30000);
  assert.equal(card.shadowRoot.writes, disconnectedWrites + 1, "the replacement timer resumes checking");
  card.disconnectedCallback();
  assert.equal(intervals.size, 0, "the replacement timer is also cleaned up");
}
clockMs = RealDate.parse(NOW);
