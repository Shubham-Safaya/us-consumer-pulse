# US Consumer Pulse

**Live:** https://shubham-safaya.github.io/us-consumer-pulse/

A daily-refreshing dashboard of the US consumer's macro identity: inflation (headline, food, gas, shelter), wages vs prices (real purchasing power), unemployment and participation, retail employment, and median household income by state.

## How it works

- `fetch_data.py` (stdlib only, no keys) pulls from the **BLS Public Data API** and **Census ACS** — free, official, public-domain US government statistics.
- A GitHub Action runs daily at 11:00 UTC, commits `data/data.json` if anything changed.
- `index.html` (GitHub Pages + Chart.js) renders tiles and charts straight from that JSON. No backend, no build step.
- Census occasionally rejects anonymous calls; the fetcher then keeps the previous values so the page never breaks.

## Data & legal

All sources are US federal government works in the **public domain (17 U.S.C. § 105)**, accessed via their official public APIs within published terms of use. The dashboard contains **aggregate statistics only — no personal data** is collected, stored, or processed (no CCPA/GDPR exposure). The page sets no cookies and runs no trackers.

| Series | Source |
|---|---|
| CPI all items / food / gasoline / shelter | BLS `CUUR0000SA0`, `SAF1`, `SETB01`, `SAH1` |
| Unemployment, participation | BLS `LNS14000000`, `LNS11300000` |
| Avg hourly earnings | BLS `CES0500000003` |
| Retail trade employment | BLS `CES4200000001` |
| Median household income & population by state | Census ACS 1-year `B19013_001E`, `B01003_001E` |

Built by [Shubham Safaya](https://shubham-safaya.github.io) — Senior PM, identity & ads personalization. MIT license.
