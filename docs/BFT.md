# Bitcoin Federated Time (BFT)

> Time is the thing we sync to the block. Tick tock. — the design in one line.

The **stardate** was already the Bitcoin block height (Fleet Ops shows it). BFT turns that raw
height into a legible calendar: **13 perfect 28-day months, counted purely in blocks.** No
almanac, no leap-second committee — the network agrees on the height, so the network agrees on
the date. (Yes, BFT also reads as *Byzantine Fault Tolerance*. That's the joke, and the point.)

Reference implementation: [`services/common/bft.py`](../services/common/bft.py) — pure stdlib,
no deps, self-checking (`python services/common/bft.py`).

## The units — all exact, all block-native

| Unit | Blocks | ≈ solar | Note |
|---|---|---|---|
| **beat** | 1 | ~10 min | the tick — one block |
| **day** | 144 | ~1 day | |
| **week** | 1,008 | 7 days | |
| **fortnight** | 2,016 | ~14 days | **= one Bitcoin difficulty epoch** |
| **month** | 4,032 | ~28 days | **= two difficulty adjustments** |
| **year** | 52,416 | ~364 days | 13 months = **26 difficulty epochs** |

The elegance: a **month is two difficulty adjustments** — the page turns twice a month the way
the network re-tunes twice a month. A year is 364 days, so it drifts ~1.24 days/year against the
sun. **That drift is intentional** — BFT tracks the chain's heartbeat, not the earth's orbit
("the sun's difficulty changes too"). 13 perfect months, no leap hacks, no intercalary day. The
longest chain is the clock.

## Epoch

Genesis block (height 0, **2009-01-03**) starts the clock. On-chain dates are **After Bitcoin
(AB)**; the year is 0-based (AB 0 is the first year). **Before Bitcoin (BB)** is the label for
wall-clock dates before genesis — block heights are never negative, so on-chain time is always AB.

## Rendering

`format_bft(height)` →

- `"short"` (default): **`AB 16 · M05 · D23`**
- `"long"`: `AB 16 · M05 · D23  (block 858,000 · diff-epoch 425)`
- `"stardate"`: `STARDATE 858,000`

`bft_from_height(height)` returns the full decomposition (year, month 1–13, day 1–28,
day_of_year 1–364, beat 0–143 within the day, difficulty epoch, week-of-month, fortnight-of-month).
`bft_year_progress(height)` gives `blocks_to_next_month` / `blocks_to_next_year` — the cadence
hooks for the monthly awards ceremony and the morning briefing.

## Naming is deliberately NOT baked in

Month and day **names** are lore for the owner to bless — this module ships neutral (`M01`..`M13`).
When names are chosen, a verse supplies them via **`bft_months: [13 names]`** in its verse config
and the server picks them up (`_bft_month_names()` in `services/mud/server.py`) with **zero code
change**. Until then, everything renders numbered. (Naming held per owner's call, 2026-07-08.)

## Where it's wired

- `block_height()` (`services/mud/server.py`) now returns `bft` (the decomposition) and
  `bft_label` (the short string) alongside `height` + `source` — so every existing stardate
  consumer gets the date for free.
- `fleet_snapshot()` carries `stardate_bft`; the console header + ticket bar render
  `STARDATE <height> · AB y · Mmm · Ddd` (via `textContent`, so no markup injection).
- **Downstream hooks (not yet built):** date certs/runes and the monthly awards-ceremony muster
  roll against BFT; stamp the morning Ops-Review briefing with the BFT date; one ceremony per
  BFT month. See the program brief at `pacsarcade/design-briefs/program-vision-2026-07-08.md`.
