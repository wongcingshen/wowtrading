# WoW Forever Auction House Indicator

Hourly price and supply tracker for the World of Warcraft: Forever auction house
(US, PvP ruleset, Alliance), with a buy / sell score per item, a dashboard, and
email alerts for major signals.

## How it runs

| Part | Where | What it does |
|---|---|---|
| Collector | GitHub Actions (`.github/workflows/collect.yml`), every hour | Pulls the auction snapshot from Blizzard's API, stores one compact row per item in `data/hourly/`, scores every item, writes `site/data/latest.json`, emails major signals |
| Dashboard | Vercel, serving the `site/` folder | Reads `latest.json` and shows signals, market and events |

## Secrets (GitHub repo → Settings → Secrets and variables → Actions)

| Name | Value |
|---|---|
| `BLIZZARD_CLIENT_ID` | from develop.battle.net |
| `BLIZZARD_CLIENT_SECRET` | from develop.battle.net |
| `RESEND_API_KEY` | from resend.com (email sending) |
| `ALERT_EMAIL` | address that receives alerts (must be the Resend account's own address unless a domain is verified) |

Optional variable (Variables tab): `DASHBOARD_URL` = your Vercel address, added to alert emails.

## Continuous learning

Each hour the model scores every 24-hour-old observation with what actually happened
(net return after the auction house cut) and updates its component weights
(`collector/learner.py`, state in `data/state/model.json`). Learned weights are blended
with the starting weights in proportion to accumulated evidence. Every signal shown is
also logged and checked 24 and 72 hours later (`data/state/signal_log.json`); the
dashboard's Learning tab shows both.

## Backtest

`collector/backtest.py` replays the recorded history every hour with the starting weights
(buy at score >= 45, sell at the normal price or after 72 hours, net of the cut) and
compares it with buying blindly. Results are on the dashboard's Learning tab.

## Tuning

- `config/settings.yaml`: market selection, weights, thresholds, alert level.
- `config/events.yaml`: scheduled events (raid openings, patches) and the item categories they affect.
- `config/substitutes.yaml`: manual substitute groups. Gear is grouped automatically.

## Testing without the real API

`python -m tests.simulate 60` runs the full pipeline against a simulated auction house.

## Known limits

- Sales are estimated from listings that disappear between snapshots (a lower bound).
- Weights start as assumptions and shift toward learned values as evidence accumulates; signal thresholds are not learned yet.
- Blizzard's Forever API is new and undocumented. Its auction house list does not state
  which house belongs to which ruleset, so the collector records every candidate house
  until one is confirmed in `config/settings.yaml` (`house_id`).
