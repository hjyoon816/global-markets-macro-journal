import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const source = fs.readFileSync("app.js", "utf8").replace(/\ninit\(\);\s*$/, "\n");
const context = {
  console,
  Date,
  Map,
  Number,
  Object,
  RegExp,
  String,
  URL,
  window: { location: { href: "http://localhost/" } },
  document: { getElementById: () => null, body: { insertAdjacentHTML: () => {} } },
};

vm.createContext(context);
vm.runInContext(source, context);

const now = Date.parse("2026-09-07T12:00:00Z");
const instrument = (timestamp, frequency, verified = true) => ({
  latest: 100,
  timestamp,
  frequency,
  verified,
});

assert.equal(
  context.classifyInstrumentFreshness(instrument("2026-09-04", "daily"), Date.parse("2026-09-06T12:00:00Z")).key,
  "fresh",
  "Friday daily observations should remain fresh during a normal weekend",
);

assert.equal(
  context.classifyInstrumentFreshness(instrument("2026-09-01", "daily"), now).key,
  "stale",
  "Old daily observations should become stale",
);

assert.equal(
  context.classifyInstrumentFreshness(instrument("2026-07-20", "monthly"), now).key,
  "fresh",
  "Monthly observations should use a longer freshness threshold",
);

assert.equal(
  context.classifyInstrumentFreshness(instrument("2026-09-05T12:00:00Z", "intraday"), now).key,
  "stale",
  "Intraday and crypto-style observations should stale faster",
);

const mixed = context.classifyDataStatus({}, [
  instrument("2026-09-06", "daily"),
  instrument("2026-09-01", "daily"),
  instrument("—", "daily", false),
], now);
assert.equal(mixed.key, "mixed");
assert.equal(mixed.counts, "1 fresh verified / 1 stale verified / 1 unavailable");

const staleOnly = context.classifyDataStatus({}, [instrument("2026-09-01", "daily")], now);
assert.equal(staleOnly.key, "stale");

const setup = context.classifyDataStatus({}, [instrument("—", "daily", false)], now);
assert.equal(setup.key, "setup");

console.log("Freshness status tests passed.");
