const fs = require("fs");

const SF_INSTANCE = "https://rev-io.my.salesforce.com";
const SF_CLIENT_ID = "3MVG91ftikjGaMd.NAf5_nx2GISRurI0fIm1aTgGSe.jNIN4bOdlqn95rfrur3RACkqjIZlDG8iCTnKzFRa.N";
const SF_CLIENT_SECRET = "FA7C3F3F72D6A1786F374CF966B505DB9B07AE43D69A6D54F127B2397713716E";
const AE_CAPACITY_REPS = [
  "Jamie Butler",
  "Andy Whisenant",
  "Connor Flynn",
  "Jake Borah",
  "Husam Zalmiyar",
  "Patrick Davies",
  "Jaylin Bender"
];
const AE_QUERY_NAMES = [...new Set([...AE_CAPACITY_REPS, "Andrew Whisenant"])];
const NAME_ALIASES = { "Andrew Whisenant": "Andy Whisenant" };
const PROSPECT_MEETING_TYPES = [
  "1-Discovery Call",
  "2-Initial DEMO",
  "3-Follow Up DEMO / Meeting",
  "4-Pricing / Negotiation Call",
  "Tradeshow Meeting"
];
const EXCLUDED_CLOSED_LOST_REASONS = new Set(["Unknown", "No Decision / Non-Responsive"]);

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

function normalizeName(name) {
  const clean = (name || "").trim();
  return NAME_ALIASES[clean] || clean;
}

function normalizeProduct(value) {
  const product = value || "Other / Not Set";
  if (product === "Billing" || product === "Billing Add-on" || product === "Billing / Odin" || product === "Billing/Odin" || product === "Odin") return "Billing/Odin";
  if (product === "Payments AR" || product === "Payments AP" || product === "Payments") return "Payments";
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
    wins: options.wins,
    total: options.total,
    breakdown: breakdown || []
  };
}

function soqlString(value) {
  return `'${String(value).replace(/\\/g, "\\\\").replace(/'/g, "\\'")}'`;
}

async function sfAuth() {
  const params = new URLSearchParams({
    grant_type: "client_credentials",
    client_id: SF_CLIENT_ID,
    client_secret: SF_CLIENT_SECRET
  });
  const response = await fetch(`${SF_INSTANCE}/services/oauth2/token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: params
  });
  if (!response.ok) throw new Error(`Salesforce auth failed: ${response.status} ${await response.text()}`);
  const payload = await response.json();
  return { base: payload.instance_url, token: payload.access_token };
}

async function sfQuery(base, token, query) {
  let url = `${base}/services/data/v59.0/query?q=${encodeURIComponent(query.trim())}`;
  const records = [];
  while (url) {
    const response = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });
    if (!response.ok) throw new Error(`Salesforce query failed: ${response.status} ${await response.text()}`);
    const payload = await response.json();
    records.push(...(payload.records || []));
    url = payload.nextRecordsUrl ? `${base}${payload.nextRecordsUrl}` : null;
  }
  return records;
}

async function fetchProspectMeetings() {
  const { base, token } = await sfAuth();
  const query = `
    SELECT Id, ActivityDate, Owner.Name
    FROM Event
    WHERE ActivityDate >= 2026-01-01
      AND ActivityDate <= 2026-12-31
      AND IsDeleted = false
      AND Type IN (${PROSPECT_MEETING_TYPES.map(soqlString).join(", ")})
      AND Appointment_Status__c = 'Completed'
      AND Owner.Name IN (${AE_QUERY_NAMES.map(soqlString).join(", ")})
  `;
  return sfQuery(base, token, query);
}

async function fetchSdrInfluencedOpportunities() {
  const { base, token } = await sfAuth();
  const query = `
    SELECT Id, CreatedDate, SDR_Influence__c
    FROM Opportunity
    WHERE CreatedDate >= 2026-01-01T00:00:00Z
      AND CreatedDate < 2027-01-01T00:00:00Z
      AND IsDeleted = false
      AND SDR_Influence__c != null
      AND SDR_Influence__c != 'None'
  `;
  return sfQuery(base, token, query);
}

async function fetchOpportunityRows() {
  const { base, token } = await sfAuth();
  const fields = `
    Id, Name, Amount, StageName, Product_Type__c, Probability,
    CloseDate, CreatedDate, Lead_Direction__c, Marketing_Source__c,
    Marketing_Sub_source__c, Loss_Reason__c, Account.Name, Owner.Name
  `;
  const [created, won, lost] = await Promise.all([
    sfQuery(base, token, `
      SELECT ${fields}
      FROM Opportunity
      WHERE CreatedDate >= 2026-01-01T00:00:00Z
        AND CreatedDate < 2026-07-01T00:00:00Z
        AND IsDeleted = false
    `),
    sfQuery(base, token, `
      SELECT ${fields}
      FROM Opportunity
      WHERE CloseDate >= 2026-01-01
        AND CloseDate <= 2026-06-30
        AND StageName = 'Closed Won'
        AND IsDeleted = false
    `),
    sfQuery(base, token, `
      SELECT ${fields}
      FROM Opportunity
      WHERE CloseDate >= 2026-01-01
        AND CloseDate <= 2026-06-30
        AND StageName = 'Closed Lost'
        AND IsDeleted = false
    `)
  ]);
  return { created: created.map(flattenOpportunity), won: won.map(flattenOpportunity), lost: lost.map(flattenOpportunity) };
}

function flattenOpportunity(row) {
  return {
    Id: row.Id,
    Name: row.Name || "",
    Amount: Number(row.Amount || 0),
    StageName: row.StageName || "",
    Product_Type__c: row.Product_Type__c || "",
    Probability: row.Probability,
    CloseDate: row.CloseDate || "",
    CreatedDate: row.CreatedDate || "",
    Lead_Direction__c: row.Lead_Direction__c || "",
    Marketing_Source__c: row.Marketing_Source__c || "",
    Marketing_Sub_source__c: row.Marketing_Sub_source__c || "",
    Loss_Reason__c: row.Loss_Reason__c || "",
    Account: row.Account?.Name || "",
    Owner: normalizeName(row.Owner?.Name || "")
  };
}

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
    id: "win-rate-by-product",
    name: "Calendar Close Rate by Product",
    category: "Pipeline Creation",
    metric: "Calendar Close Rate",
    unit: "percent",
    source: "Salesforce closed-won opportunities by CloseDate / nonzero opportunities by CreatedDate"
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
    id: "sdr-influenced-opps-created-by-month",
    name: "SDR Influenced Opportunities Created",
    category: "Pipeline Creation",
    metric: "Opportunities",
    unit: "count",
    source: "Salesforce opportunities by CreatedDate where SDR_Influence__c is populated",
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
    id: "prospect-meetings-by-rep",
    name: "Prospect Meetings by Rep",
    category: "Meetings",
    metric: "Completed prospect meetings",
    unit: "count",
    source: "Salesforce completed prospect Event types; seven-AE capacity roster",
    importance: "High"
  })
];

async function main() {
const { created, won, lost } = await fetchOpportunityRows();
const juneCreatedReps = new Set(
  created
    .filter(row => monthKey(row.CreatedDate) === "2026-06")
    .map(row => row.Owner)
    .filter(Boolean)
);
const prospectMeetings = await fetchProspectMeetings();
const sdrInfluencedOpps = await fetchSdrInfluencedOpportunities();

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
  const createdRowsWithAmount = createdRows.filter(row => Number(row.Amount || 0) > 0);
  const createdByProduct = {};
  for (const row of createdRowsWithAmount) addBreakdown(createdByProduct, normalizeProduct(row.Product_Type__c), 1);
  setMonth(feeds[2], index, createdRowsWithAmount.length, topBreakdown(createdByProduct), {
    status,
    reports: createdRowsWithAmount.length ? 1 : 0,
    notes: index === 5 ? "Filtered to opportunities with Amount > 0, per Ryan's requirement." : undefined
  });

  const winRateByProduct = {};
  for (const row of createdRowsWithAmount) {
    const product = normalizeProduct(row.Product_Type__c);
    if (!winRateByProduct[product]) winRateByProduct[product] = { label: product, wins: 0, total: 0 };
    winRateByProduct[product].total += 1;
  }
  for (const row of wonRows.filter(row => Number(row.Amount || 0) > 0)) {
    const product = normalizeProduct(row.Product_Type__c);
    if (!winRateByProduct[product]) winRateByProduct[product] = { label: product, wins: 0, total: 0 };
    winRateByProduct[product].wins += 1;
  }
  const winRateBreakdown = Object.values(winRateByProduct)
    .filter(item => item.total > 0)
    .map(item => ({ ...item, value: item.wins / item.total * 100 }))
    .sort((a, b) => b.value - a.value || b.total - a.total || a.label.localeCompare(b.label));
  const winRateWins = winRateBreakdown.reduce((sum, item) => sum + item.wins, 0);
  const winRateTotal = winRateBreakdown.reduce((sum, item) => sum + item.total, 0);
  setMonth(feeds[3], index, winRateTotal ? winRateWins / winRateTotal * 100 : 0, winRateBreakdown, {
    status,
    reports: winRateTotal ? 1 : 0,
    wins: winRateWins,
    total: winRateTotal,
    notes: index === 5 ? "Calendar close rate: closed-won opportunities in the month divided by opportunities created in the month with Amount > 0." : undefined
  });

  const bySource = {};
  for (const row of createdRows) addBreakdown(bySource, sourceName(row), 1);
  setMonth(feeds[4], index, Object.values(bySource).reduce((sum, value) => sum + value, 0), topBreakdown(bySource), { status, reports: createdRows.length ? 1 : 0 });

  const byRep = {};
  for (const row of createdRowsWithAmount) addBreakdown(byRep, row.Owner, 1);
  setMonth(feeds[5], index, Object.values(byRep).reduce((sum, value) => sum + value, 0), topBreakdown(byRep, 15), {
    status,
    reports: Object.keys(byRep).length ? 1 : 0,
    notes: index === 5 ? "Filtered to opportunities with Amount > 0, per Ryan's requirement." : undefined
  });

  const sdrRows = sdrInfluencedOpps.filter(row => monthKey(row.CreatedDate) === ym);
  const bySdr = {};
  for (const row of sdrRows) addBreakdown(bySdr, row.SDR_Influence__c, 1);
  setMonth(feeds[6], index, sdrRows.length, topBreakdown(bySdr, 20), {
    status,
    reports: Object.keys(bySdr).length ? 1 : 0,
    notes: index === 5 ? "Counts opportunities created in the month with SDR_Influence__c populated and not None." : undefined
  });

  const lostRows = lost.filter(row => monthKey(row.CloseDate) === ym);
  const byReason = {};
  for (const row of lostRows) {
    const reason = row.Loss_Reason__c || "Unknown";
    if (!EXCLUDED_CLOSED_LOST_REASONS.has(reason)) addBreakdown(byReason, reason, 1);
  }
  setMonth(feeds[7], index, Object.values(byReason).reduce((sum, value) => sum + value, 0), topBreakdown(byReason), { status, reports: Object.keys(byReason).length ? 1 : 0 });

  const meetingRows = prospectMeetings.filter(row => monthKey(row.ActivityDate) === ym);
  const byMeetingRep = {};
  for (const row of meetingRows) {
    const owner = normalizeName(row.Owner?.Name);
    if (AE_CAPACITY_REPS.includes(owner)) addBreakdown(byMeetingRep, owner, 1);
  }
  setMonth(feeds[8], index, Object.values(byMeetingRep).reduce((sum, value) => sum + value, 0), topBreakdown(byMeetingRep, 20), {
    status,
    reports: Object.keys(byMeetingRep).length ? 1 : 0,
    notes: index === 5 ? "Prospect meetings use the AE capacity dashboard ruleset and seven-AE roster." : undefined
  });
}

const output = {
  title: "Sales KPIs - Monthly Pacing Dashboard",
  year: 2026,
  asOf: new Date().toISOString().slice(0, 10),
  summaryLabel: "Ryan's starting report set",
  feeds
};

fs.writeFileSync("monthly-api-pacing-data.json", JSON.stringify(output, null, 2) + "\n");
console.log(`Wrote monthly-api-pacing-data.json with ${feeds.length} reports`);
}

main().catch(error => {
  console.error(error);
  process.exit(1);
});
