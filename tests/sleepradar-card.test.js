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
