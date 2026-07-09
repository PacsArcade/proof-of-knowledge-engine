"""
Bitcoin Federated Time (BFT) — the clock that syncs to the block, not the sun.

Pac's design (2026-07): time is the thing we sync to the chain. Tick tock. The stardate is
already the Bitcoin block height (Fleet Ops uses it); BFT turns that raw height into a legible
calendar of 13 perfect 28-day months, counted purely in blocks.

Why "Federated Time" — and yes, BFT also reads as Byzantine Fault Tolerance, which is the point:
the network agrees on the height, so the network agrees on the date. No almanac, no leap-second
committee — the longest chain IS the calendar.

## The units (all exact, all block-native)

    beat        = 1 block           (~10 min)   — the tick
    day         = 144 blocks        (~1 day)
    week        = 7 days   = 1,008 blocks
    fortnight   = 2,016 blocks      (= exactly one Bitcoin difficulty epoch)
    month       = 2 fortnights = 4,032 blocks = 28 days
    year        = 13 months = 52,416 blocks = 364 days

The elegance: a **month is two difficulty adjustments** — the calendar page turns twice a month
the way the network re-tunes twice a month. A **year is 26 difficulty epochs**. It's 364 days, so
it drifts ~1.24 days/year against the sun. That drift is a feature: BFT tracks the chain's
heartbeat, not the earth's orbit ("the sun's difficulty changes too" — Pac). 13 perfect months,
no leap hacks, no intercalary day. The chain is the clock.

## Epoch

Genesis block (height 0, 2009-01-03) starts the clock. Heights are **After Bitcoin (AB)**.
The concept of **Before Bitcoin (BB)** exists for wall-clock dates before genesis, but block
heights are never negative, so on-chain time is always AB.

## Naming

Month and day *names* are deliberately NOT baked in here — that lore is the owner's to bless.
Pass `month_names=[...]` (13 entries) to `format_bft(...)` when the names are chosen; until then
this renders neutral "Month 1..13". This module is pure stdlib and has no lore in it on purpose.
"""

from __future__ import annotations

from typing import Any, Optional

# --- exact block constants ---------------------------------------------------
BLOCKS_PER_DAY = 144
DAYS_PER_WEEK = 7
DAYS_PER_MONTH = 28
MONTHS_PER_YEAR = 13
BLOCKS_PER_DIFF_EPOCH = 2016          # one Bitcoin difficulty adjustment period

BLOCKS_PER_WEEK = BLOCKS_PER_DAY * DAYS_PER_WEEK          # 1,008
BLOCKS_PER_MONTH = BLOCKS_PER_DAY * DAYS_PER_MONTH        # 4,032  (= 2 difficulty epochs)
DAYS_PER_YEAR = DAYS_PER_MONTH * MONTHS_PER_YEAR          # 364
BLOCKS_PER_YEAR = BLOCKS_PER_DAY * DAYS_PER_YEAR          # 52,416 (= 26 difficulty epochs)

GENESIS_ISO = "2009-01-03"            # height 0 — the clock starts (informational)


def bft_from_height(height: Optional[int]) -> dict[str, Any]:
    """Decompose a Bitcoin block height into a Bitcoin Federated Time date.

    Everything is derived from integer block counts — no wall-clock, no floats in the date math,
    so two nodes at the same height always agree on the date. Returns a dict with 0-based indices
    (year_index, month_index, day_index_in_month) and human 1-based fields (month, day) plus
    difficulty-epoch context. Unknown height (None / negative) returns {"known": False}.
    """
    if height is None or height < 0:
        return {"known": False, "height": height}
    h = int(height)

    day_of_epoch = h // BLOCKS_PER_DAY            # whole days since genesis
    block_of_day = h % BLOCKS_PER_DAY             # 0..143 — the "watch" within the day

    year_index = day_of_epoch // DAYS_PER_YEAR    # 0-based AB year (AB 0 = first year)
    day_of_year = day_of_epoch % DAYS_PER_YEAR    # 0..363

    month_index = day_of_year // DAYS_PER_MONTH   # 0..12
    day_of_month = day_of_year % DAYS_PER_MONTH   # 0..27
    # which difficulty epoch within the month (first or second fortnight)
    fortnight_of_month = day_of_month // DAYS_PER_WEEK // 1  # 0 or 1 by half-month
    fortnight_of_month = 0 if day_of_month < (DAYS_PER_MONTH // 2) else 1

    return {
        "known": True,
        "height": h,                              # the raw stardate
        "epoch": "AB",                            # After Bitcoin
        "year": year_index,                       # AB year, 0-based
        "month": month_index + 1,                 # human 1..13
        "day": day_of_month + 1,                  # human 1..28
        "month_index": month_index,               # 0..12 (for indexing month_names)
        "day_of_year": day_of_year + 1,           # human 1..364
        "week_of_month": (day_of_month // DAYS_PER_WEEK) + 1,   # 1..4
        "beat": block_of_day,                     # 0..143, blocks into the day
        "day_progress": round(100 * block_of_day / BLOCKS_PER_DAY, 1),  # % through the day
        "diff_epoch": h // BLOCKS_PER_DIFF_EPOCH, # global difficulty-epoch number
        "fortnight_of_month": fortnight_of_month, # 0 = first adjustment, 1 = second
        "blocks_into_year": day_of_year * BLOCKS_PER_DAY + block_of_day,
    }


def format_bft(height: Optional[int], month_names: Optional[list[str]] = None,
               style: str = "short") -> str:
    """Render a BFT date. `month_names` (13 entries) supplies blessed month lore when it exists;
    otherwise months render as "M01".."M13". `style`: "short" → 'AB 16 · M05 · D23';
    "long" → adds the block and the difficulty epoch; "stardate" → just 'STARDATE <height>'."""
    d = bft_from_height(height)
    if not d.get("known"):
        return "STARDATE —" if style == "stardate" else "BFT —"
    if style == "stardate":
        return f"STARDATE {d['height']:,}"

    mi = d["month_index"]
    if month_names and len(month_names) >= MONTHS_PER_YEAR and month_names[mi]:
        month = str(month_names[mi])
    else:
        month = f"M{d['month']:02d}"

    short = f"{d['epoch']} {d['year']} · {month} · D{d['day']:02d}"
    if style == "long":
        return f"{short}  (block {d['height']:,} · diff-epoch {d['diff_epoch']})"
    return short


def bft_year_progress(height: Optional[int]) -> dict[str, Any]:
    """How far through the current BFT year we are — handy for the awards-ceremony cadence
    (one ceremony per month) and the morning briefing."""
    d = bft_from_height(height)
    if not d.get("known"):
        return {"known": False}
    return {
        "known": True,
        "year": d["year"],
        "month": d["month"],
        "day_of_year": d["day_of_year"],
        "year_pct": round(100 * d["day_of_year"] / DAYS_PER_YEAR, 1),
        "blocks_to_next_month": BLOCKS_PER_MONTH - (d["height"] % BLOCKS_PER_MONTH),
        "blocks_to_next_year": BLOCKS_PER_YEAR - (d["height"] % BLOCKS_PER_YEAR),
    }


if __name__ == "__main__":
    # Quick, dependency-free sanity demo: python services/common/bft.py
    samples = [0, 143, 144, 4032, 52416, 105000, 210000, 858000, 1050000]
    print(f"BFT · genesis={GENESIS_ISO} · {BLOCKS_PER_MONTH} blocks/month · {BLOCKS_PER_YEAR} blocks/year\n")
    for h in samples:
        d = bft_from_height(h)
        print(f"  height {h:>9,}  ->  {format_bft(h, style='long'):<44}"
              f"  y{d['year']} m{d['month']} d{d['day']} beat {d['beat']}/144")
    print()
    # boundaries
    assert bft_from_height(0)["year"] == 0 and bft_from_height(0)["month"] == 1 and bft_from_height(0)["day"] == 1
    assert bft_from_height(BLOCKS_PER_MONTH)["month"] == 2 and bft_from_height(BLOCKS_PER_MONTH)["day"] == 1
    assert bft_from_height(BLOCKS_PER_YEAR)["year"] == 1 and bft_from_height(BLOCKS_PER_YEAR)["month"] == 1
    assert bft_from_height(BLOCKS_PER_YEAR - BLOCKS_PER_DAY)["day_of_year"] == 364
    assert bft_from_height(None)["known"] is False
    print("  self-check: OK")
