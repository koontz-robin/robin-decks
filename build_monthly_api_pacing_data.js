const fs = require("fs");

const MONTHS = [
  ["jan", "2026-01", "Jan"],
  ["feb", "2026-02", "Feb"],
  ["mar", "2026-03", "Mar"],
  ["apr", "2026-04", "Apr"],
  ["may", "2026-05", "May"],
  ["jun", "2026-06", "Jun"],
  ["jul", "2026-07", "Jul"],
  ["aug", "2026-08", "Aug"],
  ["sep", "2026-09", "Sep"],
  ["oct", "2026-10", "Oct"],
  ["nov", "2026-11", "Nov"],
  ["dec", "2026-12", "Dec"]
];

const SCORECARD = {
  discoveryComplete: [97, 94, 94, 112, 102, 37, null, null, null, null, null, null],
  initialDemoComplete: [50, 49, 57, 50, 53, 16, null, null, null, null, null, null]
};

function readJson(path, fallback) {
  try {
    return JSON.parse(fs.readFileSync(path, "utf8"));
  } catch {
    return fallback;
  }
}

function monthKey(dateValue) {
  if (!dateValue) return null;
  return String(dateValue).slice(0, 7);
}

function normalizeProduct(value) {
  const product = value || "Other / Not Set";
  if (product === "Billing" || product === "Billing Add-on" || product === "Billing / Odin" || product === "Odin") return "Billing";
  if (product === "PSA") return "PSA 2.0";
  return product;
}

function sourceName(row) {
  const source = row.Marketing_Source__c || row.Marketing_Sub_source__c || row.Lead_Direction__c || "Other / Not Set";
  if (source === "Sales Generated") return "Sales";
  return source;
}

function addBreakdown(map, label, value) {
  const clean = label || "Other / Not Set";
  map[clean] = (map[clean] || 0) + Number(value || 0);
}

function topBreakdown(map, limit = 12) {
  return Object.entries(map)
    .filter(([, value]) => value > 0)
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .slice(0, limit)
    .map(([label, value]) => ({ label, value }));
}

function emptyMonths() {
  return Object.fromEntries(MONTHS.map(([short]) => [short, { actual: 0, target: 0, status: "future", reports: 0, breakdown: [] }]));
}

function feed({ id, name, category, metric, unit, source, owner = "Sales Ops", importance = "Critical", target = 0 }) {
  return {
    id,
    name,
    category,
    owner,
    metric,
    unit,
    source,
    annualTarget: target,
    importance,
    months: emptyMonths()
  };
}

function setMonth(feed, monthIndex, actual, breakdown, options = {}) {
  const [short] = MONTHS[monthIndex];
  const final = monthIndex <= 4;
  const current = monthIndex === 5;
  feed.months[short] = {
    actual,
    target: options.target || 0,
    status: options.status || (actual || final ? (current ? "mtd" : "final") : "missing"),
    reports: options.reports ?? (actual ? 1 : 0),
    notes: options.notes,
    breakdown: breakdown || []
  };
}

const deck = readJson("sf_june_deck_data.json", {});
const pace = readJson("sf_2026_pipeline_pace.json", {});
const created = deck.created_2026_jan_jun || [];
const won = deck.closed_won_2026_jan_jun || [];
const lost = deck.closed_lost_2026_jan_jun || [];
const juneCreatedReps = new Set(
  created
    .filter(row => monthKey(row.CreatedDate) === "2026-06")
    .map(row => row.Owner)
    .filter(Boolean)
);

const feeds = [
  feed({
    id: "closed-won-mrr-by-product",
    name: "Closed Won MRR by Product",
    category: "Closed Won",
    metric: "MRR",
    unit: "currency",
    source: "Salesforce opportunities by CloseDate"
  }),
  feed({
    id: "closed-won-mrr-by-rep-june-created",
    name: "Closed Won MRR by Rep",
    category: "Closed Won",
    metric: "MRR",
    unit: "currency",
    source: "Salesforce closed-won opportunities; reps with June-created opps only",
    importance: "Critical"
  }),
  feed({
    id: "opps-created-by-product",
    name: "Opportunities Created by Product",
    category: "Pipeline Creation",
    metric: "Opportunities",
    unit: "count",
    source: "Salesforce opportunities by CreatedDate"
  }),
  feed({
    id: "opps-created-by-marketing-source",
    name: "Opportunities Created by Marketing Source",
    category: "Pipeline Creation",
    metric: "Opportunities",
    unit: "count",
    source: "Salesforce Marketing_Source__c"
  }),
  feed({
    id: "opps-created-by-rep-nonzero",
    name: "Opportunities Created by Rep",
    category: "Pipeline Creation",
    metric: "Opportunities",
    unit: "count",
    source: "Salesforce opportunities with Amount > 0",
    importance: "Critical"
  }),
  feed({
    id: "closed-lost-by-loss-reason",
    name: "Closed Lost Opportunities by Loss Reason",
    category: "Closed Lost",
    metric: "Opportunities",
    unit: "count",
    source: "Salesforce closed-lost opportunities by CloseDate"
  }),
  feed({
    id: "discovery-calls-completed-by-rep",
    name: "Discovery Calls Completed by Rep",
    category: "Meetings",
    metric: "Completed calls",
    unit: "count",
    source: "PSA team tracker scorecard totals",
    importance: "High"
  }),
  feed({
    id: "initial-demos-completed-by-rep",
    name: "Initial Demos Completed by Rep",
    category: "Meetings",
    metric: "Completed demos",
    unit: "count",
    source: "PSA team tracker scorecard totals",
    importance: "High"
  })
];

for (let index = 0; index < MONTHS.length; index++) {
  const [, ym] = MONTHS[index];
  const status = index <= 4 ? "final" : index === 5 ? "mtd" : "future";

  const wonRows = won.filter(row => monthKey(row.CloseDate) === ym);
  const wonByProduct = {};
  for (const row of wonRows) addBreakdown(wonByProduct, normalizeProduct(row.Product_Type__c), row.Amount);
  setMonth(feeds[0], index, wonRows.reduce((sum, row) => sum + Number(row.Amount || 0), 0), topBreakdown(wonByProduct), { status, reports: wonRows.length ? 1 : 0 });

  const wonRowsForJuneCreatedReps = wonRows.filter(row => juneCreatedReps.has(row.Owner));
  const wonByRep = {};
  for (const row of wonRowsForJuneCreatedReps) addBreakdown(wonByRep, row.Owner, row.Amount);
  setMonth(feeds[1], index, wonRowsForJuneCreatedReps.reduce((sum, row) => sum + Number(row.Amount || 0), 0), topBreakdown(wonByRep, 20), {
    status,
    reports: Object.keys(wonByRep).length ? 1 : 0,
    notes: index === 5 ? "Rows are limited to reps who have at least one opportunity created in June." : undefined
  });

  const createdRows = created.filter(row => monthKey(row.CreatedDate) === ym);
  const createdByProduct = {};
  for (const row of createdRows) addBreakdown(createdByProduct, normalizeProduct(row.Product_Type__c), 1);
  setMonth(feeds[2], index, createdRows.length, topBreakdown(createdByProduct), { status, reports: createdRows.length ? 1 : 0 });

  const bySource = {};
  for (const row of createdRows) addBreakdown(bySource, sourceName(row), 1);
  setMonth(feeds[3], index, Object.values(bySource).reduce((sum, value) => sum + value, 0), topBreakdown(bySource), { status, reports: createdRows.length ? 1 : 0 });

  const byRep = {};
  for (const row of createdRows.filter(row => Number(row.Amount || 0) > 0)) addBreakdown(byRep, row.Owner, 1);
  setMonth(feeds[4], index, Object.values(byRep).reduce((sum, value) => sum + value, 0), topBreakdown(byRep, 15), {
    status,
    reports: Object.keys(byRep).length ? 1 : 0,
    notes: index === 5 ? "Filtered to opportunities with Amount > 0, per Ryan's requirement." : undefined
  });

  const lostRows = lost.filter(row => monthKey(row.CloseDate) === ym);
  const byReason = {};
  for (const row of lostRows) addBreakdown(byReason, row.Loss_Reason__c || "Unknown", 1);
  setMonth(feeds[5], index, lostRows.length, topBreakdown(byReason), { status, reports: lostRows.length ? 1 : 0 });

  const discovery = SCORECARD.discoveryComplete[index];
  setMonth(feeds[6], index, discovery || 0, [], {
    status: discovery == null ? "missing" : status,
    reports: discovery == null ? 0 : 1,
    notes: discovery == null ? "Needs rep-level event export to split by rep." : "Monthly total loaded; rep-level split needs the event export."
  });

  const demos = SCORECARD.initialDemoComplete[index];
  setMonth(feeds[7], index, demos || 0, [], {
    status: demos == null ? "missing" : status,
    reports: demos == null ? 0 : 1,
    notes: demos == null ? "Needs rep-level event export to split by rep." : "Monthly total loaded; rep-level split needs the event export."
  });
}

const output = {
  title: "Monthly Report Pacing Dashboard",
  year: 2026,
  asOf: "2026-06-15",
  summaryLabel: "Ryan's starting report set",
  feeds
};

fs.writeFileSync("monthly-api-pacing-data.json", JSON.stringify(output, null, 2) + "\n");
console.log(`Wrote monthly-api-pacing-data.json with ${feeds.length} reports`);
