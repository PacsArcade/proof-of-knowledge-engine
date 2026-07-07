"""mud/server.py — Pac's Arcade MUD (ANSI / 8-bit aesthetic). 💜

The MUD is a text front-end into the SAME world Luanti renders. In PRODUCTION it reads/writes
world state through `state-sync` (never touching DB-2 directly) and streams Oracle dialogue from
the local inference endpoint — so a `pull lever` here and a lever pull in the voxel verse mutate
identical state. Tier: HOT (world commands < 50 ms, node-local). No COLD calls on the command path.

  ── DEV MODE (this file, runnable today) ─────────────────────────────────────────────────────
  Run it with NO dependencies and NO stack — just Python 3.11 stdlib:

      python services/mud/server.py            # serves on localhost:4000
      python services/mud/play.py              # a tiny client (or use telnet / a MUD client)

  Dev mode keeps the world in memory (no Postgres), and the Oracle uses your local LLM if
  PA_INFERENCE_BASE_URL is reachable, otherwise a scripted pacbot-flavoured fallback so it works
  with zero setup. The production path (state-sync + streamed inference) is stubbed where marked.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone

# Windows consoles default to cp1252 and choke on the box-drawing/emoji in our prints.
# Socket traffic is always explicit UTF-8; this only fixes server-side stdout logging.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# --- config ------------------------------------------------------------------
MUD_HOST = os.environ.get("PA_MUD_HOST", "127.0.0.1")
MUD_PORT = int(os.environ.get("PA_MUD_PORT", "4000"))
STATE_SYNC_URL = os.environ.get("PA_STATE_SYNC_URL", "")          # empty => dev mode
INFERENCE_BASE_URL = os.environ.get("PA_INFERENCE_BASE_URL", "")  # empty => scripted Oracle
GEN_MODEL = os.environ.get("PA_GEN_MODEL", "")

# --- ANSI 8-bit palette ------------------------------------------------------
R = "\x1b[0m"
BOLD = "\x1b[1m"
AMBER = "\x1b[38;5;214m"     # arcade amber (prompts, headings)
GREEN = "\x1b[38;5;46m"      # terminal green (world text)
CYAN = "\x1b[38;5;51m"       # exits / directions
MAG = "\x1b[38;5;201m"       # 💜 accents / the Oracle
GREY = "\x1b[38;5;245m"      # hints
RED = "\x1b[38;5;196m"
GOLD = "\x1b[38;5;220m"      # loot / runes


def c(color: str, s: str) -> str:
    return f"{color}{s}{R}"


# --- the world (in-memory for dev) -------------------------------------------
# Each room: title, desc, exits {dir: room_id}, npcs, features.
ROOMS = {
    "entrance": {
        "title": "The Arcade Entrance",
        "desc": (
            "CRT cabinets hum in the dark, their attract-mode demos throwing blue light across the\n"
            "carpet. A neon sign buzzes: PAC'S ARCADE — KNOWLEDGE IS THE HIGH SCORE. The air smells of\n"
            "solder and bubblegum. A worn token-slot glows, waiting."
        ),
        "exits": {"north": "alcove", "east": "vault"},
        "npcs": [],
        "features": {},
    },
    "alcove": {
        "title": "The Oracle's Alcove",
        "desc": (
            "A single cabinet stands apart, its screen a calm violet. No coin slot — just a worn\n"
            "brass plate that reads ASK, AND DEMONSTRATE. This is where the Oracle holds court, trading\n"
            "questions for understanding. It never lectures. It only asks."
        ),
        "exits": {"south": "entrance"},
        "npcs": ["oracle"],
        "features": {},
    },
    "vault": {
        "title": "The Puzzle Vault",
        "desc": (
            "Cold stone, warmer than it looks. A great iron LEVER juts from the wall beside a sealed\n"
            "chest banded in gold. Etched above the chest: 'What is written here, only you may keep. Lose\n"
            "the scroll, lose the treasure.' The lever is a logic gate — pull it and see what opens."
        ),
        "exits": {"west": "entrance"},
        "npcs": [],
        "features": {"lever": False},
    },
}

PLAYERS: dict[asyncio.StreamWriter, "Player"] = {}


class Player:
    def __init__(self, writer: asyncio.StreamWriter):
        self.writer = writer
        self.name = "a nameless fren"
        self.room = "entrance"
        self.inventory: list[str] = []
        self.certs: list[dict] = []
        self.oracle_pending = False   # awaiting an answer to the Oracle's question

    async def send(self, text: str) -> None:
        self.writer.write(text.encode("utf-8", "replace"))
        await self.writer.drain()

    async def stream(self, text: str, delay: float = 0.012) -> None:
        """Stream text word-by-word — perceived latency is time-to-first-word, the MUD's native feel."""
        for i, word in enumerate(text.split(" ")):
            self.writer.write((("" if i == 0 else " ") + word).encode("utf-8", "replace"))
            await self.writer.drain()
            await asyncio.sleep(delay)
        self.writer.write(b"\n")
        await self.writer.drain()

    async def prompt(self) -> None:
        room = ROOMS[self.room]
        await self.send(c(AMBER, f"\n[{room['title']}] ") + c(GREY, "» "))


# --- rendering ---------------------------------------------------------------
def render_room(p: Player) -> str:
    room = ROOMS[p.room]
    out = ["", c(BOLD + AMBER, f"══ {room['title']} " + "═" * max(0, 40 - len(room['title'])))]
    out.append(c(GREEN, room["desc"]))
    if room["npcs"]:
        who = ", ".join(c(MAG, n.title()) for n in room["npcs"])
        out.append(c(GREY, "Here stands: ") + who + c(GREY, "  (try: ") + c(CYAN, "talk oracle") + c(GREY, ")"))
    others = [pl.name for w, pl in PLAYERS.items() if pl.room == p.room and pl is not p]
    if others:
        out.append(c(GREY, "Also here: ") + ", ".join(c(CYAN, o) for o in others))
    exits = ", ".join(c(CYAN, d) for d in room["exits"])
    out.append(c(GREY, "Exits: ") + (exits or c(GREY, "none")))
    return "\n".join(out) + "\n"


BANNER = "\n".join([
    "",
    c(MAG, "  ╔═══════════════════════════════════════════════════════════╗"),
    c(MAG, "  ║") + c(BOLD + GOLD, "        P A C ' S   A R C A D E   —   the MUD            ") + c(MAG, "  ║"),
    c(MAG, "  ║") + c(GREEN, "        The Federated Knowledge Engine  ·  play to learn ") + c(MAG, "║"),
    c(MAG, "  ╚═══════════════════════════════════════════════════════════╝"),
    c(GREY, "  Type ") + c(CYAN, "help") + c(GREY, " at any time. Type ") + c(CYAN, "quit") + c(GREY, " to leave. Welcome, fren. 💜"),
    "",
])

HELP = "\n".join([
    c(BOLD + AMBER, "── How to play ──"),
    c(CYAN, "  look") + c(GREY, " (l)         — look around the room"),
    c(CYAN, "  north/south/…") + c(GREY, "     — move (also: n s e w, or 'go north')"),
    c(CYAN, "  talk oracle") + c(GREY, "       — speak with the Oracle (it asks; you answer)"),
    c(CYAN, "  answer <text>") + c(GREY, "     — answer the Oracle's question"),
    c(CYAN, "  ask oracle <q>") + c(GREY, "    — ask the Oracle anything (uses your local LLM if running)"),
    c(CYAN, "  pull lever") + c(GREY, "        — operate a feature in the room"),
    c(CYAN, "  say <message>") + c(GREY, "     — speak aloud to other frens in the room"),
    c(CYAN, "  certs") + c(GREY, "             — show the class runes you've earned"),
    c(CYAN, "  who / inventory / i") + c(GREY, "  — who's online / what you carry"),
    c(GREY, "  The Oracle trades understanding for a soulbound class rune. Go earn one. 🎓"),
])


# --- the Oracle --------------------------------------------------------------
ORACLE_QUESTION = (
    "Tell me, fren: with a bitcoin wallet, there is ONE secret that is yours alone — lose it and the "
    "coins are gone, share it and they're stolen. What is that secret called?"
)
# Accept any of these as 'demonstrated understanding' for the demo.
ORACLE_KEYS = ("seed", "recovery phrase", "recovery-phrase", "private key", "privatekey", "mnemonic", "seed phrase")


async def oracle_open(p: Player) -> None:
    await p.send(c(MAG, "The Oracle's screen warms from violet to gold. It speaks, unhurried:\n"))
    await p.stream(c(MAG, "\"" + ORACLE_QUESTION + "\""))
    await p.send(c(GREY, "  (answer with: ") + c(CYAN, "answer <your words>") + c(GREY, ")\n"))
    p.oracle_pending = True


async def oracle_judge(p: Player, ans: str) -> None:
    p.oracle_pending = False
    low = ans.lower()
    if any(k in low for k in ORACLE_KEYS):
        await p.stream(c(MAG, "\"Yes. The seed phrase — your twenty-four words. Not a password you can reset; "
                             "the treasure itself. You didn't recite a definition. You understood the stakes.\""))
        await mint_class_rune(p, "PACS•SELF•CUSTODY", "Bitcoin Self-Custody 101")
    else:
        await p.stream(c(MAG, "\"Close, but feel for the weight of it. It is not your address, not your PIN. "
                             "It is the one string of words that IS the money. Try again — ") + c(CYAN, "answer <text>") + c(MAG, ".\""))
        p.oracle_pending = True


async def oracle_freeform(p: Player, question: str) -> None:
    """Free-form Socratic reply. Uses the local LLM if reachable; else a scripted fallback."""
    if INFERENCE_BASE_URL and GEN_MODEL:
        reply = await asyncio.get_event_loop().run_in_executor(None, _llm_reply, question)
        if reply:
            await p.stream(c(MAG, "\"" + reply.strip() + "\""))
            return
    # scripted pacbot-flavoured fallback (works with zero setup)
    await p.stream(c(MAG, "\"A fine question. I won't hand you the answer — that's not how the high score is earned. "
                         "Start here: what would you have to be TRUE for that to make sense? Reason it aloud, and I'll "
                         "tell you when you're warm. (Run a local model and set PA_GEN_MODEL to hear me think freely.)\""))


def _llm_reply(question: str) -> str:
    """Blocking OpenAI-compatible call (run in an executor). Best-effort; returns '' on any failure."""
    try:
        body = json.dumps({
            "model": GEN_MODEL,
            "messages": [
                {"role": "system", "content": "You are the Oracle at Pac's Arcade — a Socratic bitcoin/nostr "
                 "educator. Say 'fren', never 'friend'. Be brief (2-3 sentences), ask a probing question, never lecture."},
                {"role": "user", "content": question},
            ],
            "max_tokens": 160, "temperature": 0.7,
        }).encode()
        req = urllib.request.Request(INFERENCE_BASE_URL.rstrip("/") + "/chat/completions",
                                     data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read())
        return data["choices"][0]["message"]["content"]
    except Exception:
        return ""


async def mint_class_rune(p: Player, rune: str, title: str) -> None:
    """DEV: mint a MOCK soulbound class rune so you can see the whole reward loop end-to-end.
    In production this calls services/bitcoin-bridge/runes.py (regtest ord) — see docs/RUNES.md."""
    now = datetime.now(timezone.utc)
    wallet = "bcrt1q" + "pac5arcade0riginal0wallet".ljust(30, "0")[:30]
    block = 21_000 + len(p.certs)
    cert = {"rune": rune, "title": title, "earned": now.strftime("%Y-%m-%d %H:%M UTC"),
            "block": block, "wallet": wallet}
    p.certs.append(cert)
    await asyncio.sleep(0.4)
    card = "\n".join([
        "",
        c(GOLD, "   ┌─ SOULBOUND CLASS RUNE ─────────────────────────────┐"),
        c(GOLD, "   │ ") + c(BOLD + GOLD, "🎓 " + rune.ljust(48)) + c(GOLD, "│"),
        c(GOLD, "   │ ") + c(GREEN, ("Class:   " + title).ljust(50)) + c(GOLD, "│"),
        c(GOLD, "   │ ") + c(GREEN, ("Earned:  " + cert['earned'] + f"  (block {block})").ljust(50)) + c(GOLD, "│"),
        c(GOLD, "   │ ") + c(GREEN, ("Wallet:  " + wallet).ljust(50)) + c(GOLD, "│"),
        c(GOLD, "   │ ") + c(GREY, "soulbound · non-transferable · regtest (mock demo)".ljust(50)) + c(GOLD, "│"),
        c(GOLD, "   └────────────────────────────────────────────────────┘"),
        c(MAG, "  A rune settles into your wallet, fren. Block time and your wallet are"),
        c(MAG, "  written on-chain — so even if it's ever moved, everyone knows YOU earned it. 💜"),
    ])
    await p.send(card + "\n")


# --- command dispatch --------------------------------------------------------
DIRS = {"north", "south", "east", "west", "up", "down"}
DIR_ALIAS = {"n": "north", "s": "south", "e": "east", "w": "west", "u": "up", "d": "down"}


async def broadcast_room(room: str, text: str, exclude: Player | None = None) -> None:
    for w, pl in list(PLAYERS.items()):
        if pl.room == room and pl is not exclude:
            try:
                await pl.send(text)
            except Exception:
                pass


async def dispatch(p: Player, line: str) -> bool:
    """Handle one command. Returns False if the player wants to quit."""
    verb, _, rest = line.strip().partition(" ")
    verb = verb.lower()
    rest = rest.strip()

    if verb in ("quit", "exit", "q"):
        await p.send(c(MAG, "The cabinets dim. Come back soon, fren. 💜\n"))
        return False
    if verb in ("help", "?", "commands"):
        await p.send(HELP + "\n")
    elif verb in ("look", "l"):
        await p.send(render_room(p))
    elif verb in ("go", "move", "walk"):
        await move(p, rest)
    elif verb in DIRS or verb in DIR_ALIAS:
        await move(p, DIR_ALIAS.get(verb, verb))
    elif verb == "exits":
        await p.send(c(GREY, "Exits: ") + ", ".join(c(CYAN, d) for d in ROOMS[p.room]["exits"]) + "\n")
    elif verb == "talk":
        target = rest.lower() or (ROOMS[p.room]["npcs"][0] if ROOMS[p.room]["npcs"] else "")
        if target == "oracle" and "oracle" in ROOMS[p.room]["npcs"]:
            await oracle_open(p)
        else:
            await p.send(c(GREEN, "There's no one by that name to talk to here.\n"))
    elif verb == "answer":
        if p.oracle_pending:
            await oracle_judge(p, rest)
        else:
            await p.send(c(GREY, "The Oracle hasn't asked you anything yet. Try ") + c(CYAN, "talk oracle") + c(GREY, ".\n"))
    elif verb == "ask":
        tgt, _, q = rest.partition(" ")
        if tgt.lower() == "oracle" and "oracle" in ROOMS[p.room]["npcs"]:
            await oracle_freeform(p, q.strip() or "teach me something about bitcoin")
        elif "oracle" not in ROOMS[p.room]["npcs"]:
            await p.send(c(GREEN, "The Oracle is in its Alcove (north from the entrance).\n"))
        else:
            await p.send(c(GREY, "Ask whom? Try: ") + c(CYAN, "ask oracle <your question>") + "\n")
    elif verb == "pull":
        await pull(p, rest)
    elif verb == "say":
        if rest:
            await p.send(c(GREEN, "You say: ") + c(BOLD, rest) + "\n")
            await broadcast_room(p.room, c(CYAN, f"\n{p.name} says: ") + c(BOLD, rest) + "\n", exclude=p)
        else:
            await p.send(c(GREY, "Say what?\n"))
    elif verb in ("certs", "runes", "certificates"):
        await show_certs(p)
    elif verb in ("inventory", "inv", "i"):
        inv = ", ".join(p.inventory) if p.inventory else "nothing but curiosity"
        await p.send(c(GREEN, "You carry: ") + inv + "\n")
    elif verb == "who":
        names = ", ".join(pl.name for pl in PLAYERS.values())
        await p.send(c(GREEN, f"Frens in the arcade ({len(PLAYERS)}): ") + names + "\n")
    elif verb in ("name", "whoami"):
        await p.send(c(GREEN, f"You are {p.name}.\n"))
    elif p.oracle_pending:
        # If the Oracle is waiting, treat a bare line as the answer (forgiving parser).
        await oracle_judge(p, line.strip())
    else:
        await p.send(c(GREEN, f"You aren't sure how to '{verb}', fren. Try ") + c(CYAN, "help") + c(GREEN, ".\n"))
    return True


async def move(p: Player, direction: str) -> None:
    direction = DIR_ALIAS.get(direction.lower(), direction.lower())
    exits = ROOMS[p.room]["exits"]
    if direction in exits:
        await broadcast_room(p.room, c(GREY, f"\n{p.name} heads {direction}.\n"), exclude=p)
        p.room = exits[direction]
        await broadcast_room(p.room, c(GREY, f"\n{p.name} arrives.\n"), exclude=p)
        await p.send(render_room(p))
    else:
        await p.send(c(GREEN, "You can't go that way, fren.\n"))


async def pull(p: Player, thing: str) -> None:
    if "lever" in thing.lower() and p.room == "vault":
        room = ROOMS["vault"]
        room["features"]["lever"] = not room["features"]["lever"]
        if room["features"]["lever"]:
            await p.send(c(GOLD, "You heave the lever. Gears grind; the gold-banded chest clicks. Inside: a SCROLL.\n"))
            await p.stream(c(GREY, "(A lever pulled here is exactly the event a lever pull in the Luanti voxel world "
                                  "would send — one world, two windows. In production this routes through state-sync.)"))
            if "the scroll (keep it secret)" not in p.inventory:
                p.inventory.append("the scroll (keep it secret)")
        else:
            await p.send(c(GREEN, "You return the lever. The chest re-seals with a sigh.\n"))
    else:
        await p.send(c(GREEN, "There's nothing like that to pull here.\n"))


async def show_certs(p: Player) -> None:
    if not p.certs:
        await p.send(c(GREY, "No class runes yet. The Oracle's Alcove is where they're earned. 🎓\n"))
        return
    await p.send(c(BOLD + GOLD, "\nYour soulbound class runes:\n"))
    for cert in p.certs:
        await p.send(c(GOLD, f"  🎓 {cert['rune']}  ") + c(GREEN, f"— {cert['title']}  ")
                     + c(GREY, f"(earned {cert['earned']}, block {cert['block']})\n"))
    await p.send(c(MAG, "  Non-transferable by design. Move one and provenance still names you as the earner. 💜\n"))


# --- connection handling -----------------------------------------------------
def clean_line(raw: bytes) -> str:
    # strip telnet IAC negotiation bytes (0xFF ...) and control chars, keep it simple
    out = bytearray()
    i = 0
    while i < len(raw):
        b = raw[i]
        if b == 0xFF:      # IAC: skip the 2 bytes that follow a command
            i += 3
            continue
        if b in (0x08, 0x7F):  # backspace/delete — ignore (client-side editing assumed)
            i += 1
            continue
        out.append(b)
        i += 1
    return out.decode("utf-8", "replace").strip()


async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    p = Player(writer)
    PLAYERS[writer] = p
    try:
        await p.send(BANNER)
        await p.send(c(AMBER, "By what name shall the arcade know you, fren? ") )
        raw = await reader.readline()
        name = clean_line(raw)
        if name:
            p.name = name[:24]
        await p.send(c(MAG, f"\nWelcome, {p.name}. The high score is understanding. 💜\n"))
        await broadcast_room(p.room, c(GREY, f"\n{p.name} steps in from the street.\n"), exclude=p)
        await p.send(render_room(p))
        await p.prompt()

        while not reader.at_eof():
            raw = await reader.readline()
            if not raw:
                break
            line = clean_line(raw)
            if not line:
                await p.prompt()
                continue
            keep = await dispatch(p, line)
            if not keep:
                break
            await p.prompt()
    except (ConnectionResetError, asyncio.IncompleteReadError):
        pass
    finally:
        PLAYERS.pop(writer, None)
        await broadcast_room(p.room, c(GREY, f"\n{p.name} fades from the arcade.\n"))
        try:
            writer.close()
        except Exception:
            pass


async def main() -> None:
    mode = "production (state-sync)" if STATE_SYNC_URL else "DEV (in-memory world)"
    oracle = "local LLM" if (INFERENCE_BASE_URL and GEN_MODEL) else "scripted pacbot fallback"
    server = await asyncio.start_server(handle_client, MUD_HOST, MUD_PORT)
    print(f"▓ Pac's Arcade MUD listening on {MUD_HOST}:{MUD_PORT}  [{mode}, Oracle: {oracle}] 💜")
    print(f"  Connect:  python services/mud/play.py    (or: telnet {MUD_HOST} {MUD_PORT})")
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n▓ MUD shutting down. GG, fren. 💜")
