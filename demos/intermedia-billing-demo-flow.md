# Rev.io Billing Demo Flow — Intermedia
**Prepared for:** Jamie Butler | **Audience:** Andrew (CDEO) + Engineering Team (Toronto)
**Format:** 90 minutes | **Focus:** Rev.io Billing ONLY (not PSA)
**Date:** May 2026

---

## 🎯 Framing & Strategy

**Their core pain:**
- 16–20 hour bill runs for 1.5M lines/licenses
- Billing can't complete before spilling into the next day
- They want to double to 3M by 2030 — their current platform can't get there
- 48-hour lag from invoice generation to customer visibility
- Previous migration attempt failed: tried to change everything at once

**Our positioning:**
- Charge generation engine first, Host Pilot invoicing continues — **phased, not rip-and-replace**
- Built for scale: show real enterprise performance numbers (get from Daryl ahead of demo)
- Engineering-grade: APIs, webhooks, configurable billing logic — not just a UI

**What Andrew liked about BluLogix:** The UI for pricing/account management adjustments. Mirror that — show we have a UI that could replace their internal screens, not just an API. Make it feel like a platform they could own, not just plumb into.

---

## ⏱️ Demo Agenda (90 Minutes)

### **[0:00–0:10] Opening — Land the Pain**
*Speaker: AE (Jamie)*

Open with their story, not our product. Something like:

> "We know you've tried this before. Five to ten years ago it didn't work — and the reason was clear: change everything at once, and nothing works. We're not going to propose that. What we want to show you today is how Rev.io becomes your charge generation engine first — plugging into Host Pilot — and grows from there on your terms."

Key stats to call out:
- 1.5M lines billing in 16–20 hours — ask Andrew to validate that number
- Goal: same or better throughput at 3M lines
- By 2030, double the customer base: billing has to scale with it

**Objective:** Get engineering heads nodding that we understand the real problem before a single screen is shown.

---

### **[0:10–0:20] Architecture Overview — How We Fit Into Their World**
*Speaker: SE*

Whiteboard/slide — show the integration architecture:

```
Intermedia systems
  └── PBX / Usage Data → Rev.io (CDR Ingestion via API)
  └── Orders / Provisioning → Rev.io (Subscription API)
  └── Rev.io (Charge Generation) → Host Pilot (Invoicing) ← Phase 1
  └── Rev.io (Charge Generation) → Rev.io Invoicing ← Phase 2 (future)
  └── Rev.io → Avalara (Tax — they're keeping this)
  └── Rev.io → NetSuite (GL reconciliation)
  └── Rev.io → Payment Processor (they're interested)
  └── Rev.io API → Their Data Warehouse / Data Hub (reporting stays theirs)
```

Key messages:
- We don't replace Avalara — we integrate with it natively
- NetSuite integration is built-in, not custom dev
- Their Data Warehouse keeps doing what it does — we don't need to own reporting
- CDR ingestion: show a generic CDR format, offer to share their PBX format for review

**Objective:** Engineering team sees we understand their stack and aren't asking them to nuke it.

---

### **[0:20–0:35] Performance Deep Dive — The Numbers They Care About**
*Speaker: SE + (Daryl's data pre-loaded)*

⚠️ **Pre-work required:** Get from Daryl a real production client at similar scale (1–2M accounts/subscriptions) and pull bill run metrics: min/median/max duration, bills per minute, throughput at scale.

Demo talking points:
- "Here's a production client at [X] accounts and [Y] subscriptions — here's what their last 3 bill cycles looked like"
- Bills per minute, duration, parallelism
- Show multi-threading / concurrent billing architecture
- "To get to 3M lines — here's how the math works, and here's a client that's trending that direction"

**Show in product:**
- Bill run dashboard — active run with status, progress, timing
- Bill run history — completion times, bills created, print batches
- Performance instrumentation they can actually monitor

**The big moment:** Put their numbers on screen. "16–20 hours today. Here's what our benchmark says for your volume."

**Objective:** Give Andrew and his architects a concrete answer to "can you handle 3M lines." Engineering buys on data, not claims.

---

### **[0:35–0:50] Billing Logic — Built for Their Model**
*Speaker: SE*

Walk through the billing scenarios that matter most to Intermedia:

**1. Multi-Tier Partner Model (Ascend BYOC)**
- Show account hierarchy: Intermedia → Reseller → End Customer
- Wholesale pricing vs. resale pricing in same system
- Tax exemption at partner level (Ascend / BYOC partners — no tax calc)
- Canada wholesale: calculate at resale amount, reseller handles GST
- Show how tax rules are applied conditionally by account type

**2. Multi-Currency, Multi-Entity**
- Intermedia US (USD), Intermedia Canada (CAD), Intermedia UK (GBP)
- Japan (JPY) and Australia (AUD) — set static pricing in currency, generate transactions, pass to regional invoicing
- Europe — no automated payment collection, no VAT for European customers (reseller responsibility)
- Show: setting prices per currency, generating transactions in that denomination
- Clarify: no live FX conversion (same as what they have today — **this is a match, not a gap**)

**3. Anniversary Billing**
- Walk through prorated start billing
- ⚠️ Flag internally: confirm exact workflow for "billing starts 1 week after order completion with prorated balance" — get product team input before demo
- If confirmed: show it live
- If not fully supported: "Here's how we handle anniversary billing, and here's what the phased roadmap looks like"

**4. Usage Rating / CDR**
- Show CDR ingestion — upload a sample, show how it rates against a product/rate plan
- "Here's the format we support natively — let us send it to your team to validate against your PBX output"

**Objective:** Engineering team sees billing logic is configurable, not hard-coded. They don't have to build this themselves.

---

### **[0:50–1:05] Product Catalog & Pricing UI — What Andrew Saw in BluLogix**
*Speaker: SE*

This is where we match what excited Andrew in the BluLogix demo — the UI for managing pricing, accounts, and products without writing code.

**Show:**
- Product catalog — create/edit a product, set pricing tiers, set per-currency pricing
- Rate plans — attach products, configure billing schedules, set promo pricing
- ⚠️ "First unit free" logic: confirm with product team if natively supported before demo — if not, show the nearest workaround (promo discount on first unit, tiered pricing starting at $0 for unit 1)
- Account management UI — subscription adjustments, mid-cycle changes, prorated credits/charges
- 1,000 SKU scale: be prepared to speak to catalog limits and any architecture choices needed for large catalogs; don't wing this

**The message to land:** "Rather than your team building more internal screens, here's a UI your billing ops team can actually own."

**Objective:** Andrew sees his "aha moment" from BluLogix replicated — plus an architecture his engineers can respect.

---

### **[1:05–1:15] Integrations & API Walk**
*Speaker: SE*

Engineering audience — show the API, don't just describe it.

- **NetSuite:** Show GL integration, reconciliation flow
- **Avalara:** Show tax call in action — they're keeping Avalara, show it's native
- **Payments:** Brief intro to Rev.io Payments — they're interested, plant the seed
- **API Documentation:** Pull up docs or Swagger live — "here's the subscription API, here's CDR ingestion, here's the billing engine webhook events"
- **Bill on Behalf (BOB):** Show hierarchy with a reseller who has BOB enabled, show branded invoice output — "not a day one requirement, but it's built, and here's what it looks like"

**Objective:** Engineers see real APIs, real documentation, real integration patterns — not a black box.

---

### **[1:15–1:25] GDPR / Data Residency — Address the Gap Honestly**
*Speaker: AE*

Don't hide this. Engineers will ask.

- Rev.io infrastructure is US-based
- UK gap is real — acknowledge it
- "We've had conversations internally about spinning up an Azure cluster in the UK for clients where data residency is a hard requirement — particularly for the Ascend brand and any healthcare/legal partners"
- Position as a roadmap conversation, not a blocker today — Phase 1 is charge gen, UK full deployment is further out

**Objective:** Trust through honesty. Engineers respect "here's the gap and here's the plan" over "we'll figure it out."

---

### **[1:25–1:35] ROI & Migration Approach — Close the Story**
*Speaker: AE*

**ROI framing:**
- BRM licensing may be low, but: support contracts, on-prem hardware, infrastructure, and most importantly — **developer time**
- They're parking billing improvement projects because they can't scale. What does that cost?
- If they double to 3M lines and bill runs go from 20 hours to [X hours], what does that free up?
- Kuldip flagged people cost is higher than our model — update the ROI with their actual dev headcount before this meeting

**Migration approach:**
- Phase 1: Charge generation only, Host Pilot invoicing stays
- No big bang. No rip-and-replace.
- Migration window: 12 months from signing (their target)
- We've done enterprise migrations at this scale — reference if you have one

**Objective:** Andrew leaves with a clear picture of ROI and a migration path that doesn't scare his engineering team.

---

### **[1:35–1:45] Q&A / Buffer**

Hold 10–15 minutes for questions. Engineering audiences always have them.

**Likely questions to prep for:**
- "What's the actual throughput on a 1.5M line bill run?"
- "How do we migrate existing subscriber data?"
- "What does the API authentication model look like?"
- "Can we see the CDR format spec?"
- "What's the SLA on bill run completion?"
- "How does multi-threading work — is it configurable?"
- "What happens if a bill run fails mid-way?"

---

## 📋 Pre-Demo Checklist

**Must have before the call:**
- [ ] Real bill run performance data from Daryl (comparable client, 1–2M scale)
- [ ] Confirmation from product on: anniversary billing exact workflow, "first unit free" logic, 1,000 SKU catalog scale
- [ ] Generic CDR format to share with Kuldip's team
- [ ] API documentation link ready
- [ ] Updated ROI model with higher people cost per Kuldip's feedback
- [ ] Demo environment prepped: multi-tier account hierarchy (Intermedia → Ascend reseller → end customer), multi-currency products, BOB example with branded invoice

**Nice to have:**
- [ ] Reference client they can call (similar scale, telco/UCaaS)
- [ ] Azure UK data residency roadmap note from product
- [ ] SharePoint Excel (Intermedia Requirements April 2026) — review for any additional requirements not captured in notes

---

## ⚠️ Known Gaps — Handle With Care

| Gap | Status | Recommended Approach |
|---|---|---|
| Anniversary billing (1 week delay + prorate) | Unclear — confirm with product | Get answer before demo; show if supported |
| Conditional DID billing suspension | Likely manual today | Acknowledge; position as config/roadmap |
| "First unit free" promo logic | Unclear | Confirm; show workaround if needed |
| ~1,000 SKU catalog scale | Known gap area | Get product input; don't guess |
| GDPR / UK data residency | Gap today | Address honestly; reference Azure cluster option |

---

## 🔑 Key Themes to Reinforce Throughout

1. **Phased, not big bang** — charge gen first, full migration second
2. **Engineering-grade** — real APIs, real performance data, real architecture
3. **Scale story** — 1.5M today → 3M by 2030, here's how
4. **You own the UI** — pricing, account management, billing ops without internal dev
5. **Partners are first-class** — Ascend BYOC, wholesale, BOB — it's built for their model
