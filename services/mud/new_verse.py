"""new_verse.py — scaffold a POKEMUD verse pack. 💜

    python services/mud/new_verse.py <id> --name "My Verse" [--tagline "..."]

Writes services/mud/verses/<id>/verse.json with a small runnable starter world
(two rooms, one Socratic teacher with a trial, one boss), then prints how to run
it and how to connect the node to the main hub. The full creation walkthrough —
including pacBOT's "imagine a verse" interview — is docs/VERSE-GUIDE.md.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
VERSES_DIR = os.environ.get("PA_VERSES_DIR", os.path.join(HERE, "verses"))


def template(vid: str, name: str, tagline: str) -> dict:
    prefix = re.sub(r"[^A-Z0-9]", "", name.upper())[:8] or vid.upper()[:8]
    return {
        "id": vid,
        "name": name,
        "tagline": tagline,
        "start_room": "landing",
        "ranks": [
            {"level": 1, "title": "Newcomer"},
            {"level": 5, "title": "Regular"},
            {"level": 12, "title": "Legend"},
        ],
        "home": {
            "default_name": "{name}'s Room",
            "desc": f"Your own room in {name}. Your soulbound runes hang on the wall; "
                    "frens you invite can drop by. The way back out is south.",
        },
        "rooms": {
            "landing": {
                "title": "The Landing",
                "desc": f"Welcome to {name}. Describe what a fren sees the moment they arrive — "
                        "this text IS your verse's first impression. A teacher waits north; "
                        "a challenge coils below.",
                "exits": {"north": "classroom", "down": "arena"},
                "npcs": [],
                "art": ["   *  your ascii  *", "   *  art here    *"],
            },
            "classroom": {
                "title": "The Classroom",
                "desc": "Your Socratic teacher holds court here. It never lectures — it only asks.",
                "exits": {"south": "landing"},
                "npcs": ["teacher"],
                "art": [],
            },
            "arena": {
                "title": "The Arena",
                "desc": "Your boss encounter lives here. Type  challenge  to face it.",
                "exits": {"up": "landing"},
                "npcs": ["guardian"],
                "art": [],
            },
        },
        "npcs": {
            "teacher": {
                "name": "the Teacher",
                "kind": "socratic",
                "persona": f"You are the Teacher of {name} — a Socratic educator in a MUD. "
                           "Say 'fren', never 'friend'. Reply in 1-3 warm sentences and end "
                           "with a probing question. Never lecture.",
                "fallback": "I answer questions with questions, fren. Ask me something real. "
                            "What's on your mind?",
                "trial": {
                    "question": "REPLACE ME: the one understanding-check question your verse "
                                "opens with. What must a fren truly grasp?",
                    "keys": ["replace", "me"],
                    "class": {"class_id": f"{vid}-101", "rune": f"{prefix}•101",
                              "title": f"{name} 101"},
                    "xp": 100,
                    "pass_line": "Understanding demonstrated, fren.",
                    "already": "You already hold this rune, fren — I don't etch a truth twice.",
                    "retry": "Close — feel the weight of it and try again:  answer <text>",
                },
            },
            "guardian": {
                "name": "the Guardian",
                "kind": "boss",
                "persona": f"You are the Guardian of {name} — a riddle-boss. Menacing but fair. "
                           "Two sentences max.",
                "question": "\"REPLACE ME: the riddle your boss asks. Name the answer — and I yield.\"",
                "keys": ["replace", "me"],
                "class": {"class_id": f"{vid}-boss", "rune": f"{prefix}•GUARDIAN",
                          "title": f"{name} Guardian Trial"},
                "xp": 150,
                "energy_win": 20,
                "energy_miss": -15,
                "fail_hint": "Think harder, fren.   answer <text>",
                "victory_line": "the Guardian yields",
                "already_lines": ["", "  No XP for a lesson you already own, fren."],
                "anim": [["", "  the Guardian stirs...", ""]],
                "defeat_anim": [["", "  the Guardian yields.", ""]],
            },
        },
        "strings": {
            "welcome": "Welcome to " + name + ", {who}. 💜",
            "welcome_back": "Welcome back, {who}.",
            "cant_go": "you can't go that way, fren",
            "goodnight": "Goodnight, {who}.",
            "come_back": "Come back soon, fren. 💜",
        },
        "gallery": [
            {"title": "first light", "artist": name,
             "art": ["   .  *  .", "  * verse *", "   .  *  ."]}
        ],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Scaffold a POKEMUD verse pack.")
    ap.add_argument("id", help="verse id (lowercase, dashes ok — e.g. degen-wonderland)")
    ap.add_argument("--name", required=True, help='display name, e.g. "Degen Wonderland"')
    ap.add_argument("--tagline", default="a P.O.K.E. verse", help="one-line tagline")
    ap.add_argument("--force", action="store_true", help="overwrite an existing pack")
    args = ap.parse_args()

    vid = args.id.strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", vid):
        print(f"! '{vid}' — use lowercase letters, digits and dashes")
        return 1
    dest = os.path.join(VERSES_DIR, vid, "verse.json")
    if os.path.exists(dest) and not args.force:
        print(f"! {dest} already exists (use --force to overwrite)")
        return 1

    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "w", encoding="utf-8") as f:
        json.dump(template(vid, args.name.strip(), args.tagline.strip()), f,
                  ensure_ascii=False, indent=2)
    print(f"▓ verse pack scaffolded: {dest}")
    print()
    print("  Next steps, fren:")
    print(f"   1. Edit the pack — rooms, NPCs, trials, art. Search for REPLACE ME.")
    print(f"   2. Run it:            PA_VERSE={vid} python services/mud/server.py")
    print(f"   3. Play it:           http://127.0.0.1:4001/play")
    print(f"   4. Join the hub:      set PA_FRENS_URL, then add your verse's relay in the")
    print(f"      node console (Knowledge Connections) so frens can find it.")
    print(f"   5. Get certified:     the issue-node-cert skill publishes your node to the map.")
    print()
    print("  Full walkthrough (incl. pacBOT's 'imagine a verse' interview): docs/VERSE-GUIDE.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
