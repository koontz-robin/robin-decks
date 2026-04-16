# Roamer — Dashboard Link Migration Guide

> **Attention Roamer:** Your dashboard links are outdated and being flagged as malicious by enterprise email security tools. Read this document in full and update all links immediately.

## Summary

All Rev.io sales dashboards have been migrated from third-party proxy services to GitHub Pages. Any bot or system still using old URLs needs to update to the new format immediately.

---

## What Changed and Why

### Old URLs (DO NOT USE — flagged as malicious)

These URLs use third-party proxy services that are blocked by enterprise email security tools (Proofpoint, etc.):

```
# DEPRECATED — will be flagged as malicious
https://htmlpreview.github.io/?https://github.com/koontz-robin/robin-decks/blob/master/[file].html
https://raw.githack.com/koontz-robin/robin-decks/master/[file].html
https://htmlpreview.github.io/?https://raw.githubusercontent.com/koontz-robin/robin-decks/master/[file].html
```

### New URL (USE THIS)

GitHub Pages is now enabled on the `koontz-robin/robin-decks` repository. All dashboards are served directly from GitHub's own CDN — trusted by all enterprise security tools.

```
# CORRECT — use this format for all dashboards
https://koontz-robin.github.io/robin-decks/[filename].html
```

---

## How GitHub Pages Was Enabled

1. Navigated to `github.com/koontz-robin/robin-decks`
2. Settings → Pages
3. Source: **Deploy from a branch** → Branch: **master** → Folder: **/ (root)**
4. Saved — GitHub automatically serves all HTML files at `koontz-robin.github.io/robin-decks/`

No additional configuration required. Every file pushed to the `master` branch is automatically available at the GitHub Pages URL within 1-2 minutes.

---

## Updated Dashboard URLs

| Dashboard | URL |
|---|---|
| April 2026 Forecast | `https://koontz-robin.github.io/robin-decks/forecast-april-2026.html` |
| AE Capacity | `https://koontz-robin.github.io/robin-decks/ae-capacity-dashboard.html` |
| Q2 Apollo 2 Tracker | `https://koontz-robin.github.io/robin-decks/q2-reengagement-tracker.html` |
| Sales BEACON | `https://koontz-robin.github.io/robin-decks/beacon.html` |
| PSA Onboarding Tracker | `https://koontz-robin.github.io/robin-decks/psa-onboarding-tracker.html` |
| Closed Loss Analysis | `https://koontz-robin.github.io/robin-decks/closed-loss-feb-vs-mar.html` |
| MSP PSA Requirements | `https://koontz-robin.github.io/robin-decks/msp-psa-requirements.html` |
| Robin Business Impact | `https://koontz-robin.github.io/robin-decks/robin-impact.html` |
| Full Library / Index | `https://koontz-robin.github.io/robin-decks/index.html` |

---

## Rules Going Forward

1. **Never use htmlpreview.github.io or raw.githack.com** — these are third-party domains and will get flagged
2. **Always use `koontz-robin.github.io/robin-decks/[file].html`** for any new dashboards
3. **When pushing a new dashboard file to `master`**, it is automatically live at the GitHub Pages URL within 1-2 minutes — no additional steps needed
4. **If a link appears broken**, check that the file was pushed to the `master` branch (not a different branch) and wait up to 2 minutes for GitHub Pages to deploy

---

## Testing a Link

```bash
curl -s -o /dev/null -w "%{http_code}" "https://koontz-robin.github.io/robin-decks/forecast-april-2026.html"
# Should return: 200
```

Any response other than 200 means the file hasn't been pushed to master yet or GitHub Pages is still deploying.

---

*Migration completed April 14, 2026. All 13 existing dashboard files updated.*
