"""verses.py — data-driven verse packs for POKEMUD. 💜

A VERSE is the world a pokenode hosts: rooms, art, NPCs (Socratic teachers and bosses),
strings, ranks, and gallery pieces — all data, no code. Every website that runs a node
ships its own verse pack; the engine stays identical.

    services/mud/verses/<id>/verse.json      (+ optional art/ frames)

Select with PA_VERSE (default: pacsarcade). Unknown/broken packs fall back to the
built-in pacsarcade verse so a node never boots into a void.

Scaffold a new pack with:  python services/mud/new_verse.py <id> --name "My Verse"
The creation walkthrough (pacBOT's 'imagine a verse' interview) lives in
docs/VERSE-GUIDE.md.
"""

from __future__ import annotations

import copy
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
VERSES_DIR = os.environ.get("PA_VERSES_DIR", os.path.join(HERE, "verses"))

# Everything a verse MAY override; anything missing falls back to these.
DEFAULTS: dict = {
    "tagline": "Proof of Knowledge Engine",
    "start_room": None,               # default: first room in the pack
    "ranks": [],                      # [{"level": 1, "title": "Ensign"}, ...] highest match wins
    "home": {
        "default_name": "{name}'s Quarters",
        "desc": ("Your own corner of the arcade. Your soulbound runes hang on the wall; "
                 "frens you invite can drop by. The floor is south."),
    },
    "strings": {
        "welcome": "Welcome, {who}. The high score is understanding. 💜",
        "welcome_back": "Welcome back, {who}. Your progress was kept.",
        "cant_go": "you can't go that way, fren",
        "goodnight": "Goodnight, {who}.",
        "come_back": "Come back and we'll pick up right where you left off. 💜",
    },
    "gallery": [],                    # [{"title", "artist", "art": [lines], "media": {"kind","url"}}]
}

REQUIRED_NPC_TRIAL = ("question", "keys", "class")


def _norm_npc(nid: str, npc: dict) -> dict:
    npc = dict(npc)
    npc.setdefault("name", nid.title())
    npc.setdefault("kind", "socratic")           # socratic | boss
    npc.setdefault("persona", "")
    npc.setdefault("fallback", "")
    if npc["kind"] == "boss":
        npc.setdefault("anim", [])
        npc.setdefault("defeat_anim", [])
        npc.setdefault("xp", 150)
    return npc


def _validate(data: dict, path: str) -> dict:
    for key in ("id", "name", "rooms"):
        if key not in data:
            raise ValueError(f"verse pack {path} is missing '{key}'")
    if not data["rooms"]:
        raise ValueError(f"verse pack {path} has no rooms")
    merged = copy.deepcopy(DEFAULTS)
    for k, v in data.items():
        if isinstance(v, dict) and isinstance(merged.get(k), dict):
            merged[k].update(v)
        else:
            merged[k] = v
    merged.setdefault("npcs", {})
    merged["npcs"] = {nid: _norm_npc(nid, n) for nid, n in merged["npcs"].items()}
    if not merged.get("start_room"):
        merged["start_room"] = next(iter(merged["rooms"]))
    for rid, room in merged["rooms"].items():
        room.setdefault("exits", {})
        room.setdefault("npcs", [])
        room.setdefault("art", [])
        for npc in room["npcs"]:
            if npc not in merged["npcs"]:
                raise ValueError(f"room '{rid}' references unknown npc '{npc}'")
    return merged


def available() -> list[str]:
    try:
        return sorted(d for d in os.listdir(VERSES_DIR)
                      if os.path.isfile(os.path.join(VERSES_DIR, d, "verse.json")))
    except OSError:
        return []


def load(verse_id: "str | None" = None) -> dict:
    vid = (verse_id or os.environ.get("PA_VERSE", "pacsarcade")).strip()
    path = os.path.join(VERSES_DIR, vid, "verse.json")
    try:
        with open(path, encoding="utf-8") as f:
            return _validate(json.load(f), path)
    except Exception as e:
        if vid != "pacsarcade":
            print(f"! verse '{vid}' failed to load ({e}); falling back to pacsarcade")
            return load("pacsarcade")
        raise


def rank_for(verse: dict, level: int) -> str:
    """Highest rank whose level requirement the player meets ('' when the verse has none)."""
    title = ""
    for r in sorted(verse.get("ranks", []), key=lambda r: r.get("level", 0)):
        if level >= r.get("level", 0):
            title = r.get("title", "")
    return title
