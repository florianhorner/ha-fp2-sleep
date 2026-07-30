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
assert.match(missingOccupancy, /sr-badge sr-badge-neutral">not measuring/);
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
