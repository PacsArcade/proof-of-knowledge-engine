"""
Calendar lore — where a birthday lands across two calendars, and which sign claims it.

Powers the MUD's hidden extra-credit room (the Observatory). Three honest lookups from a
plain Gregorian birthday (month, day):

1. **International Fixed Calendar (IFC)** — the real 13-month calendar from history (Cotsworth
   1902; Kodak ran on it 1928–1989). 13 months of exactly 28 days, with **Sol** inserted
   between June and July. This is the "where's my birthday in a 13-month year" answer. (It's a
   *civil* calendar aligned to Jan 1 — distinct from Bitcoin Federated Time in bft.py, which is
   block-timed. Different tools, same 13-month shape.)
2. **The 12 tropical signs** — Western astrology's fixed-to-the-seasons zodiac.
3. **The 13 astronomical signs** — the constellations the sun *actually* crosses, including the
   13th, **Ophiuchus** (the Serpent Bearer, ~Nov 29–Dec 17).

Honesty note (this is educational lore, not a horoscope service): astrology isn't science, and
the "13th sign" isn't a sign that got hidden or a date that "changed." Tropical astrology was
always tied to the equinox, on purpose; the 13-count simply reflects that the ecliptic passes
through 13 constellations, Ophiuchus included. We teach the difference, we don't sell the stars.

Pure stdlib. Self-checks with:  python services/common/calendar_lore.py
"""

from __future__ import annotations

from typing import Any, Optional

# Non-leap cumulative day-of-year, so a month/day birthday maps the same every year.
_MONTH_LEN = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
_MONTH_NAMES = ["January", "February", "March", "April", "May", "June",
                "July", "August", "September", "October", "November", "December"]
_MONTH_ALIAS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}

# International Fixed Calendar month names — Sol is inserted after June.
_IFC_MONTHS = ["January", "February", "March", "April", "May", "June", "Sol",
               "July", "August", "September", "October", "November", "December"]

# 12 tropical signs, as (name, glyph, start_month, start_day). A date belongs to the last
# entry whose start it is on/after (Capricorn wraps the year).
_TROPICAL = [
    ("Capricorn", "♑", 12, 22), ("Aquarius", "♒", 1, 20), ("Pisces", "♓", 2, 19),
    ("Aries", "♈", 3, 21), ("Taurus", "♉", 4, 20), ("Gemini", "♊", 5, 21),
    ("Cancer", "♋", 6, 21), ("Leo", "♌", 7, 23), ("Virgo", "♍", 8, 23),
    ("Libra", "♎", 9, 23), ("Scorpio", "♏", 10, 23), ("Sagittarius", "♐", 11, 22),
]

# 13 astronomical signs — the IAU constellation boundaries the sun actually crosses, including
# Ophiuchus. Dates are the widely-cited approximate crossings (the sun's real path, not a chart).
_ASTRONOMICAL = [
    ("Capricorn", "♑", 1, 20), ("Aquarius", "♒", 2, 16), ("Pisces", "♓", 3, 11),
    ("Aries", "♈", 4, 18), ("Taurus", "♉", 5, 13), ("Gemini", "♊", 6, 21),
    ("Cancer", "♋", 7, 20), ("Leo", "♌", 8, 10), ("Virgo", "♍", 9, 16),
    ("Libra", "♎", 10, 30), ("Scorpio", "♏", 11, 23), ("Ophiuchus", "⛎", 11, 29),
    ("Sagittarius", "♐", 12, 17),
]


def parse_date(text: str) -> Optional[tuple[int, int]]:
    """Best-effort birthday parse → (month, day). Accepts 'July 20', 'jul 20', '20 july',
    '7/20', '7-20', '20/7' (day-first only when the first number can't be a month)."""
    if not text:
        return None
    t = text.strip().lower().replace(",", " ")
    # numeric M/D or M-D
    for sep in ("/", "-", "."):
        if sep in t:
            a, _, b = t.partition(sep)
            a, b = a.strip(), b.strip()
            if a.isdigit() and b.isdigit():
                m, d = int(a), int(b)
                if m > 12 and d <= 12:      # they wrote day-first
                    m, d = d, m
                return _valid(m, d)
    # month-name forms
    toks = t.split()
    mon = day = None
    for tok in toks:
        key = tok[:4] if tok[:4] in _MONTH_ALIAS else tok[:3]
        if key in _MONTH_ALIAS:
            mon = _MONTH_ALIAS[key]
        elif tok.isdigit():
            day = int(tok)
    if mon and day:
        return _valid(mon, day)
    return None


def _valid(m: int, d: int) -> Optional[tuple[int, int]]:
    if m == 2 and d == 29:                     # leap birthday — welcome, fren
        return (2, 29)
    if 1 <= m <= 12 and 1 <= d <= _MONTH_LEN[m - 1]:
        return (m, d)
    return None


def day_of_year(month: int, day: int) -> int:
    """1..365 (non-leap basis)."""
    return sum(_MONTH_LEN[:month - 1]) + day


def _sign_for(month: int, day: int, table: list) -> tuple[str, str]:
    """Return the (name, glyph) whose start the date is on/after, wrapping the year. If the date
    is before every start in this year (early January), it belongs to the sign that started
    latest in December and carries across New Year (Capricorn tropically; Sagittarius by the
    real constellations)."""
    best = None
    best_key = -1
    key = month * 100 + day
    for name, glyph, sm, sd in table:
        sk = sm * 100 + sd
        if key >= sk and sk > best_key:
            best, best_key = (name, glyph), sk
    if best is not None:
        return best
    # before every start this year → the latest-starting (year-wrapping) sign
    n, g, _, _ = max(table, key=lambda e: e[2] * 100 + e[3])
    return (n, g)


def ifc_position(month: int, day: int) -> dict[str, Any]:
    """Map a Gregorian birthday into the 13-month International Fixed Calendar."""
    doy = day_of_year(month, day)
    if doy >= 365:                                  # Dec 31 (non-leap) → the monthless Year Day
        return {"month_index": None, "month": "Year Day", "day": None,
                "label": "Year Day", "note": "a day that belongs to no month — it caps the year"}
    idx = (doy - 1) // 28                            # 0..12
    d = (doy - 1) % 28 + 1                           # 1..28
    name = _IFC_MONTHS[idx]
    return {"month_index": idx, "month": name, "day": d, "label": f"{name} {d}",
            "note": "Sol is the 13th month, slipped in between June and July" if name == "Sol"
                    else ""}


def birthday_reading(month: int, day: int) -> dict[str, Any]:
    """The full Observatory reading for a Gregorian birthday."""
    greg = f"{_MONTH_NAMES[month - 1]} {day}"
    ifc = ifc_position(month, day)
    t_name, t_glyph = _sign_for(month, day, _TROPICAL)
    a_name, a_glyph = _sign_for(month, day, _ASTRONOMICAL)
    return {
        "gregorian": greg,
        "day_of_year": day_of_year(month, day),
        "ifc": ifc,
        "tropical": {"name": t_name, "glyph": t_glyph},
        "astronomical": {"name": a_name, "glyph": a_glyph},
        "is_ophiuchus": a_name == "Ophiuchus",
        "signs_differ": t_name != a_name,
    }


def format_reading(month: int, day: int) -> list[str]:
    """Plain text lines for the MUD (colouring is applied by the caller)."""
    r = birthday_reading(month, day)
    out = [
        f"  Birthday: {r['gregorian']}  (day {r['day_of_year']} of the year)",
        "",
        f"  12-month calendar (Gregorian):  {r['gregorian']}",
        f"  13-month calendar (Int'l Fixed): {r['ifc']['label']}",
    ]
    if r["ifc"]["note"]:
        out.append(f"      — {r['ifc']['note']}")
    out += [
        "",
        f"  Your sign (12, tropical):      {r['tropical']['glyph']} {r['tropical']['name']}",
        f"  Your sign (13, astronomical):  {r['astronomical']['glyph']} {r['astronomical']['name']}",
    ]
    if r["is_ophiuchus"]:
        out.append("      — you fall under OPHIUCHUS, the 13th sign, the Serpent Bearer ⛎")
    elif r["signs_differ"]:
        out.append("      — the two differ because one tracks the seasons, the other the real stars")
    out += [
        "",
        "  Why two answers? The 12 signs are fixed to the equinox (the seasons). The 13 are the",
        "  constellations the sun truly crosses — and it crosses 13, Ophiuchus included. Nothing",
        "  'changed'; they were always measuring different things. Stars are for wonder, fren,",
        "  never for finance — no chart predicts a price.  (extra credit: honest astronomy > astrology)",
    ]
    return out


if __name__ == "__main__":
    for probe in ("July 20", "12/17", "dec 5", "1/1", "12/31", "nov 30", "2/29"):
        pd = parse_date(probe)
        if not pd:
            print(f"{probe:>8} -> (unparseable)")
            continue
        r = birthday_reading(*pd)
        print(f"{probe:>8} -> Greg {r['gregorian']:<13} | IFC {r['ifc']['label']:<11} | "
              f"12: {r['tropical']['name']:<11} | 13: {r['astronomical']['name']}")
    # boundary checks
    assert birthday_reading(11, 30)["astronomical"]["name"] == "Ophiuchus"
    assert birthday_reading(12, 10)["astronomical"]["name"] == "Ophiuchus"
    assert birthday_reading(7, 20)["tropical"]["name"] in ("Cancer", "Leo")
    assert ifc_position(1, 1)["label"] == "January 1"
    assert ifc_position(12, 31)["month"] == "Year Day"
    assert parse_date("bogus") is None
    print("\nself-check: OK")
