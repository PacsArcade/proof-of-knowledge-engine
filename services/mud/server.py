"""mud/server.py — Pac's Arcade · Proof of Knowledge Engine (P.O.K.E.) — the MUD. 💜

The MUD is a text front-end into the SAME world Luanti renders. In PRODUCTION it reads/writes
world state through `state-sync` and streams Oracle dialogue from the local inference endpoint —
a `pull lever` here and a lever pull in the voxel verse mutate identical state. Tier: HOT.

  ── DEV MODE (this file, runnable today) ─────────────────────────────────────────────────────
      python services/mud/server.py            # serves on 127.0.0.1:4000
      python services/mud/play.py              # a tiny client (or use telnet / a MUD client)

  Dev mode persists the world in a local SQLite file (services/common/world_store.py) and uses
  your local LLM if PA_INFERENCE_BASE_URL is reachable, else a scripted pacbot fallback.
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import sys
import textwrap
import threading
import time
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# --- config ------------------------------------------------------------------
MUD_HOST = os.environ.get("PA_MUD_HOST", "127.0.0.1")
MUD_PORT = int(os.environ.get("PA_MUD_PORT", "4000"))
STATE_SYNC_URL = os.environ.get("PA_STATE_SYNC_URL", "")
INFERENCE_BASE_URL = os.environ.get("PA_INFERENCE_BASE_URL", "")
GEN_MODEL = os.environ.get("PA_GEN_MODEL", "")

# --- persistence (shared with state-sync) ------------------------------------
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "common"))
import world_store  # noqa: E402

try:
    STORE = world_store.open_store()
except Exception as e:
    print(f"! persistence backend failed ({e}); falling back to the SQLite dev store")
    os.environ["PA_GAMESTATE_BACKEND"] = "sqlite"
    STORE = world_store.open_store()

# --- operator console / admin state ------------------------------------------
# The MUD is a node an operator runs, not a black box: live stats, knowledge-swarm
# health, and safe reboot/shutdown — from the local terminal, from inside the MUD
# (admin token), or over an HTTP control surface the web-admin techstack can drive.
SERVER_START = time.time()
ADMIN_TOKEN = os.environ.get("PA_ADMIN_TOKEN") or secrets.token_hex(4)
ADMIN_TOKEN_GENERATED = "PA_ADMIN_TOKEN" not in os.environ
RUNES_ETCHED = 0                              # runes etched this session (stat)

# Web-admin "rails": a localhost HTTP control surface (stdlib, token-auth) so the main
# techstack admin page can view stats and broadcast/kick/reboot/shutdown the node.
ADMIN_HTTP_HOST = os.environ.get("PA_MUD_ADMIN_HOST", "127.0.0.1")   # localhost-only by default
ADMIN_HTTP_PORT = int(os.environ.get("PA_MUD_ADMIN_PORT", "4001"))

# Matrix chat integration — the class/chat area routes through the Matrix verse when the
# operator opts in. DEFAULT OFF; local in-room `say` still works. `admin chat on|off` toggles.
CHAT_MATRIX = os.environ.get("PA_CHAT_MATRIX", "off").lower() in ("1", "true", "on", "yes")
MATRIX_BRIDGE_URL = os.environ.get("PA_MATRIX_BRIDGE_URL", "http://matrix-bridge:8084")

# runtime handles (set in main)
SERVER = None
LOOP = None
REBOOT = False
SHUTDOWN = asyncio.Event()

# --- screen control ----------------------------------------------------------
CLEAR = "\x1b[2J\x1b[3J\x1b[H"        # clear screen + scrollback, cursor home
RESIZE = "\x1b[8;42;112t"            # ask the terminal for 42x112 (honored by some; resize freely after)

# --- ANSI 8-bit palette ------------------------------------------------------
R = "\x1b[0m"
BOLD = "\x1b[1m"
AMBER = "\x1b[38;5;214m"
GREEN = "\x1b[38;5;46m"
CYAN = "\x1b[38;5;51m"
MAG = "\x1b[38;5;201m"
GREY = "\x1b[38;5;245m"
RED = "\x1b[38;5;196m"
GOLD = "\x1b[38;5;220m"


def c(color: str, s: str) -> str:
    return f"{color}{s}{R}"


# --- ASCII title (aligned block art; no emoji INSIDE boxes = no broken pipes) -
_GLYPHS = {
    "P": ["██████", "██  ██", "██████", "██    ", "██    "],
    "O": [" ████ ", "██  ██", "██  ██", "██  ██", " ████ "],
    "K": ["██  ██", "██ ██ ", "████  ", "██ ██ ", "██  ██"],
    "E": ["██████", "██    ", "█████ ", "██    ", "██████"],
}


def big(word: str) -> list[str]:
    rows = ["", "", "", "", ""]
    for ch in word.upper():
        g = _GLYPHS.get(ch, ["      "] * 5)
        for i in range(5):
            rows[i] += g[i] + "  "
    return [r.rstrip() for r in rows]


def boxed(lines: list[str], width: int, bcol: str = MAG, tcol: str = GOLD) -> str:
    """Draw a double-line box. Every interior line is centered+padded to `width`, so the right
    border ALWAYS aligns — the fix for the old 'broken pipes'. Keep content free of emoji /
    double-width chars (they'd desync the padding)."""
    out = [c(bcol, "╔" + "═" * width + "╗")]
    for ln in lines:
        out.append(c(bcol, "║") + c(tcol, ln.center(width)) + c(bcol, "║"))
    out.append(c(bcol, "╚" + "═" * width + "╝"))
    return "\n".join(out)


def make_banner() -> str:
    lines = [""] + big("POKE") + [
        "",
        "PAC'S  ARCADE",
        "Proof of Knowledge Engine  ·  P.O.K.E.",
        "play to learn",
        "",
        "type  help  to learn the controls   ·   quit  to leave",
        "",
    ]
    width = max(len(l) for l in lines) + 8
    return "\n" + boxed(lines, width) + "\n" + c(GREY, "  Welcome, fren. 💜") + "\n"


BANNER = make_banner()

HELP = "\n".join([
    c(BOLD + AMBER, "── How to play ──"),
    c(CYAN, "  look") + c(GREY, " (l)          — look around the room"),
    c(CYAN, "  north/south/east/west") + c(GREY, "  — go through a door (also n/s/e/w, or 'go north')"),
    c(CYAN, "  talk oracle") + c(GREY, "        — speak with the Oracle (it asks; you answer)"),
    c(CYAN, "  answer <text>") + c(GREY, "      — answer the Oracle's question"),
    c(CYAN, "  ask oracle <q>") + c(GREY, "     — ask the Oracle anything (uses your local LLM if running)"),
    c(CYAN, "  pull lever") + c(GREY, "         — operate a feature in the room"),
    c(CYAN, "  link <kind> <id>") + c(GREY, "   — link your @fren / nostr / spaces identity (see 'link')"),
    c(CYAN, "  profile") + c(GREY, "            — your character, wallet, links, and runes"),
    c(CYAN, "  say <message>") + c(GREY, "      — speak aloud to other frens in the room"),
    c(CYAN, "  certs · who · inventory") + c(GREY, "  — your runes / who's online / what you carry"),
    c(GREY, "  Doors are the gaps in the frame ") + c(CYAN, "▲ ▼ ◄ ►") + c(GREY, ". The Oracle trades understanding for a rune. 🎓"),
])


# --- the world (in-memory rooms; player + feature state persists) ------------
ROOM_ART = {
    "entrance": [
        "┌──┐  ┌──┐  ┌──┐     ~ insert token ~",
        "│▓▓│  │░░│  │▓▓│",
        "└──┘  └──┘  └──┘",
    ],
    "alcove": [
        "        .-\"\"\"-.",
        "       ( o   o )     the Oracle waits, patient",
        "        '-...-'",
    ],
    "vault": [
        "    .------------.",
        "    | [#]     ()  |   a sealed chest, banded in gold",
        "    '------------'",
    ],
}

ROOMS = {
    "entrance": {
        "title": "The Arcade Entrance",
        "desc": (
            "CRT cabinets hum in the dark, their attract-mode demos throwing blue light across the "
            "carpet. A neon sign buzzes: PAC'S ARCADE — KNOWLEDGE IS THE HIGH SCORE. The air smells "
            "of solder and bubblegum. A worn token-slot glows, waiting."
        ),
        "exits": {"north": "alcove", "east": "vault"},
        "npcs": [],
    },
    "alcove": {
        "title": "The Oracle's Alcove",
        "desc": (
            "A single cabinet stands apart, its screen a calm violet. No coin slot — just a worn brass "
            "plate that reads ASK, AND DEMONSTRATE. This is where the Oracle holds court, trading "
            "questions for understanding. It never lectures. It only asks."
        ),
        "exits": {"south": "entrance"},
        "npcs": ["oracle"],
    },
    "vault": {
        "title": "The Puzzle Vault",
        "desc": (
            "Cold stone, warmer than it looks. A great iron LEVER juts from the wall beside a sealed "
            "chest banded in gold. Etched above the chest: 'What is written here, only you may keep. "
            "Lose the scroll, lose the treasure.' The lever is a logic gate — pull it and see."
        ),
        "exits": {"west": "entrance"},
        "npcs": [],
    },
}

PLAYERS: dict[asyncio.StreamWriter, "Player"] = {}
BOARD_W = 72   # inner width of the play board


class Player:
    def __init__(self, writer: asyncio.StreamWriter):
        self.writer = writer
        self.name = "a nameless fren"
        self.room = "entrance"
        self.inventory: list[str] = []
        self.certs: list[dict] = []
        self.wallet = ""
        self.nostr = None
        self.space = None
        self.fren_tag = None
        self.oracle_pending = False
        self.connected_at = time.time()   # session start (operator stats)
        self.idle_since = time.time()      # last command time (operator stats)
        self.is_admin = False              # elevated via `admin <token>`

    async def send(self, text: str) -> None:
        self.writer.write(text.encode("utf-8", "replace"))
        await self.writer.drain()

    async def stream(self, text: str, delay: float = 0.02) -> None:
        for i, word in enumerate(text.split(" ")):
            self.writer.write((("" if i == 0 else " ") + word).encode("utf-8", "replace"))
            await self.writer.drain()
            await asyncio.sleep(delay)
        self.writer.write(b"\n")
        await self.writer.drain()

    async def prompt(self) -> None:
        tag = f"@{self.fren_tag}" if self.fren_tag else self.name
        await self.send(c(AMBER, f"\n[{ROOMS[self.room]['title']}] ") + c(GREY, f"{tag} » "))


# --- the play board (double-line frame; doors are gaps in the pipes) ---------
def _wrap(text: str, width: int) -> list[str]:
    out: list[str] = []
    for para in text.split("\n"):
        out += textwrap.wrap(para, width) or [""]
    return out


def _build_body(p: Player) -> list[str]:
    room = ROOMS[p.room]
    body: list[str] = []
    art = ROOM_ART.get(p.room)
    if art:
        body += art + [""]
    body += _wrap(room["desc"], BOARD_W - 2)
    body.append("")
    if room["npcs"]:
        body.append("Here: " + ", ".join(n.title() for n in room["npcs"]) + "   (try 'talk oracle')")
    others = [pl.name for w, pl in PLAYERS.items() if pl.room == p.room and pl is not p]
    if others:
        body.append("Also here: " + ", ".join(others))
    body.append("Doors: " + ", ".join(room["exits"].keys()) + "   ·   type 'help'")
    while len(body) < 9:
        body.append("")
    return body


def render_board(p: Player) -> str:
    room = ROOMS[p.room]
    exits = room["exits"]
    W = BOARD_W
    body = _build_body(p)
    mid = len(body) // 2

    # top border: room title in a ╡ … ╞ sign, plus a ▲ gap if there's a north door
    top = list("═" * W)
    sign = f"╡ {room['title']} ╞"
    for i, ch in enumerate(sign):
        if 3 + i < W:
            top[3 + i] = ch
    if "north" in exits:
        dp = W * 3 // 4
        top[dp - 1:dp + 2] = list(" ▲ ")
    rows = [c(MAG, "╔") + c(MAG, "".join(top)) + c(MAG, "╗")]

    # body rows: side pipes, with ◄ / ► doors punched in on the middle row
    for i, line in enumerate(body):
        left = c(CYAN, "◄") if (i == mid and "west" in exits) else c(MAG, "║")
        right = c(CYAN, "►") if (i == mid and "east" in exits) else c(MAG, "║")
        rows.append(left + " " + c(GREEN, line.ljust(W - 2)) + " " + right)

    # bottom border: a ▼ gap if there's a south door
    bot = list("═" * W)
    if "south" in exits:
        dp = W // 2
        bot[dp - 1:dp + 2] = list(" ▼ ")
    rows.append(c(MAG, "╚") + c(MAG, "".join(bot)) + c(MAG, "╝"))
    return "\n".join(rows) + "\n"


# --- the Oracle --------------------------------------------------------------
SELF_CUSTODY = {"class_id": "self-custody", "rune": "PACS•SELF•CUSTODY", "title": "Bitcoin Self-Custody 101"}

ORACLE_QUESTION = (
    "Tell me, fren: with a bitcoin wallet, there is ONE secret that is yours alone — lose it and the "
    "coins are gone, share it and they're stolen. What is that secret called?"
)
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
        if await asyncio.to_thread(STORE.has_certificate, p.name, SELF_CUSTODY["class_id"]):
            await p.stream(c(MAG, "\"But you already hold this rune, fren — I don't etch a truth twice. Wear it well.\""))
        else:
            global RUNES_ETCHED
            RUNES_ETCHED += 1
            await asyncio.to_thread(STORE.record_competency, p.name, "bitcoin-self-custody", 0.9,
                                    "Understood the seed phrase is the treasure, not a resettable password.")
            await etch_class_rune(p, SELF_CUSTODY)
    else:
        await p.stream(c(MAG, "\"Close, but feel for the weight of it. It is not your address, not your PIN. "
                             "It is the one string of words that IS the money. Try again — ") + c(CYAN, "answer <text>") + c(MAG, ".\""))
        p.oracle_pending = True


async def oracle_freeform(p: Player, question: str) -> None:
    if INFERENCE_BASE_URL and GEN_MODEL:
        reply = await asyncio.get_event_loop().run_in_executor(None, _llm_reply, question)
        if reply:
            await p.stream(c(MAG, "\"" + reply.strip() + "\""))
            return
    await p.stream(c(MAG, "\"A fine question. I won't hand you the answer — that's not how the high score is earned. "
                         "Start here: what would have to be TRUE for that to make sense? Reason it aloud, and I'll "
                         "tell you when you're warm. (Run a local model and set PA_GEN_MODEL to hear me think freely.)\""))


def _llm_reply(question: str) -> str:
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


def render_cert_card(cert: dict) -> str:
    W = 52
    inner = W + 1  # account for the single space after the opening │
    title = "─ SOULBOUND CLASS RUNE "
    top = title + "─" * (inner - len(title))

    def row(s: str, col: str = GREEN) -> str:
        return c(GOLD, "   │ ") + c(col, s.ljust(W)) + c(GOLD, "│")

    return "\n".join([
        "",
        c(GOLD, "   ┌" + top + "┐"),
        row("* " + cert["rune_name"], BOLD + GOLD),
        row("Class:   " + cert["title"]),
        row("Earned:  " + str(cert["block_time"]) + f"  (block {cert['block_height']})"),
        row("Wallet:  " + cert["original_wallet"]),
        row("soulbound · non-transferable · regtest (mock demo)", GREY),
        c(GOLD, "   └" + "─" * inner + "┘"),
        c(MAG, "  A rune is etched into your wallet, fren. Block time and your wallet are"),
        c(MAG, "  written on-chain — so even if it's ever moved, everyone knows YOU earned it. 💜"),
    ])


async def etch_class_rune(p: Player, spec: dict) -> None:
    """Etch (and PERSIST) a soulbound class rune via the world store. Idempotent: earning a class
    you already hold returns the ORIGINAL record (original block time + wallet preserved).
    In dev the rune is a mock; production etches on regtest via services/bitcoin-bridge/runes.py."""
    block = 21_000 + len(p.certs)
    cert = await asyncio.to_thread(
        STORE.etch_certificate, p.name, spec["class_id"], spec["rune"], spec["title"], p.wallet, block
    )
    p.certs = await asyncio.to_thread(STORE.list_certificates, p.name)
    await asyncio.sleep(0.4)
    await p.send(render_cert_card(cert) + "\n")


# --- identity linking (@fren / nostr / spaces) -------------------------------
async def link_identity(p: Player, rest: str) -> None:
    kind, _, val = rest.partition(" ")
    kind = kind.lower().strip()
    val = val.strip()
    if not kind:
        await p.send("\n".join([
            c(BOLD + AMBER, "── Link your identity ──"),
            c(GREY, "  Tie this character to the fren you are out in the world:"),
            c(CYAN, "  link fren  <name>") + c(GREY, "     — your @fren handle (the tag we're rolling out across Pac's Arcade)"),
            c(CYAN, "  link nostr <npub1…>") + c(GREY, "  — your nostr identity"),
            c(CYAN, "  link space <@name>") + c(GREY, "   — your spaces (Bitcoin) name"),
            c(GREY, "  Current: ") + _links_summary(p),
            c(GREY, "  (Claims are stored now; ownership is verified via ") + c(CYAN, "frens.earth") + c(GREY, ".)"),
        ]) + "\n")
        return
    if kind == "nostr":
        if not val.startswith("npub1"):
            await p.send(c(RED, "  A nostr key looks like 'npub1…', fren. Try again.\n")); return
        await asyncio.to_thread(STORE.set_identity, p.name, "nostr", val); p.nostr = val
        await p.send(c(GREEN, "  Linked your nostr identity. ") + c(GREY, "(verify at frens.earth)\n"))
    elif kind in ("space", "spaces"):
        v = val if val.startswith("@") else "@" + val
        await asyncio.to_thread(STORE.set_identity, p.name, "space", v); p.space = v
        await p.send(c(GREEN, f"  Linked your space {v}. ") + c(GREY, "(verify at frens.earth)\n"))
    elif kind == "fren":
        v = val.lstrip("@")
        if not v:
            await p.send(c(RED, "  Give me a handle: ") + c(CYAN, "link fren pacman") + "\n"); return
        await asyncio.to_thread(STORE.set_identity, p.name, "fren_tag", v); p.fren_tag = v
        await p.send(c(GREEN, f"  You are now known as ") + c(BOLD + MAG, f"@{v}") + c(GREEN, " across the arcade. 💜\n"))
    else:
        await p.send(c(GREY, "  Link what? Try ") + c(CYAN, "link") + c(GREY, " for options.\n"))


def _links_summary(p: Player) -> str:
    parts = []
    parts.append(f"@{p.fren_tag}" if p.fren_tag else "no @fren")
    parts.append(f"nostr {p.nostr[:12]}…" if p.nostr else "no nostr")
    parts.append(f"space {p.space}" if p.space else "no space")
    return " · ".join(parts)


async def show_profile(p: Player) -> None:
    lines = [
        c(BOLD + AMBER, f"── {('@' + p.fren_tag) if p.fren_tag else p.name} ──"),
        c(GREY, "  Character: ") + c(GREEN, p.name),
        c(GREY, "  Wallet:    ") + c(GREEN, p.wallet or "—"),
        c(GREY, "  @fren:     ") + c(GREEN, ("@" + p.fren_tag) if p.fren_tag else c(GREY, "unlinked  (link fren <name>)")),
        c(GREY, "  nostr:     ") + c(GREEN, p.nostr or c(GREY, "unlinked  (link nostr <npub1…>)")),
        c(GREY, "  space:     ") + c(GREEN, p.space or c(GREY, "unlinked  (link space <@name>)")),
        c(GREY, "  Runes:     ") + c(GOLD, f"{len(p.certs)} soulbound class rune(s)"),
    ]
    await p.send("\n".join(lines) + "\n")


# --- command dispatch --------------------------------------------------------
DIRS = {"north", "south", "east", "west", "up", "down"}
DIR_ALIAS = {"n": "north", "s": "south", "e": "east", "w": "west", "u": "up", "d": "down"}


async def broadcast_room(room: str, text: str, exclude: "Player | None" = None) -> None:
    for w, pl in list(PLAYERS.items()):
        if pl.room == room and pl is not exclude:
            try:
                await pl.send(text)
            except Exception:
                pass


# =============================================================================
# Operator console — live stats, knowledge-swarm health, safe reboot/shutdown.
# Reachable three ways: the local terminal (stdin), in-MUD `admin <token>`, and an
# HTTP control surface (localhost, token-auth) for the web-admin techstack.
# =============================================================================

def _fmt_dur(secs: float) -> str:
    secs = int(secs)
    h, m, s = secs // 3600, (secs % 3600) // 60, secs % 60
    return (f"{h}h " if h else "") + f"{m:02d}m {s:02d}s"


# --- knowledge-swarm status (COLD, best-effort, cached — never blocks gameplay) ---
_swarm_cache = {"at": 0.0, "data": None}


def _probe_swarm() -> dict:
    """Ask the corpus/torrent service how many nodes we're synced to. Best-effort: if it's
    not running (dev), degrade gracefully. Set PA_SWARM_MOCK='{...}' to demo without it."""
    mock = os.environ.get("PA_SWARM_MOCK")
    if mock:
        try:
            d = json.loads(mock); d["online"] = True; return d
        except Exception:
            pass
    url = os.environ.get("PA_CORPUS_URL", "")
    if not url:
        return {"online": False, "reason": "corpus service not configured (set PA_CORPUS_URL)"}
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/status", timeout=1.5) as r:
            d = json.loads(r.read()); d["online"] = True; return d
    except Exception as e:
        return {"online": False, "reason": f"corpus service unreachable ({e.__class__.__name__})"}


async def get_swarm_status(force: bool = False) -> dict:
    now = time.time()
    if not force and _swarm_cache["data"] is not None and now - _swarm_cache["at"] < 15:
        return _swarm_cache["data"]
    data = await asyncio.to_thread(_probe_swarm)
    _swarm_cache.update(at=now, data=data)
    return data


def nodes_report(status: dict) -> str:
    if not status.get("online"):
        return "Knowledge swarm: OFFLINE — " + str(status.get("reason", "unknown"))
    peers = status.get("peers", status.get("nodes", 0))
    corpora = status.get("corpora", status.get("swarms", []))
    cached, total = status.get("shards_cached"), status.get("shards_total")
    lines = ["Knowledge swarm: ONLINE", f"  nodes synced : {peers}"]
    if corpora:
        lines.append(f"  corpora      : {', '.join(map(str, corpora))}")
    if cached is not None:
        lines.append(f"  shards cached: {cached}" + (f" / {total}" if total else ""))
    if status.get("manifest_verified") is not None:
        lines.append("  manifest     : " + ("verified" if status["manifest_verified"] else "UNVERIFIED"))
    return "\n".join(lines)


# --- stats (text for humans, dict for the web admin) -------------------------
def stats_json() -> dict:
    return {
        "uptime_s": int(time.time() - SERVER_START),
        "player_count": len(PLAYERS),
        "players": [{
            "name": p.name, "fren": p.fren_tag, "room": p.room,
            "uptime_s": int(time.time() - p.connected_at),
            "idle_s": int(time.time() - p.idle_since), "admin": p.is_admin,
        } for p in PLAYERS.values()],
        "runes_etched_session": RUNES_ETCHED,
        "store": {"backend": type(STORE).__name__, "location": getattr(STORE, "path", "postgres DB-2")},
        "oracle": ("local-llm:" + GEN_MODEL) if (INFERENCE_BASE_URL and GEN_MODEL) else "scripted",
        "chat_matrix": CHAT_MATRIX,
    }


def stats_report() -> str:
    lines = ["P.O.K.E. MUD — operator stats",
             f"  uptime      : {_fmt_dur(time.time() - SERVER_START)}",
             f"  players     : {len(PLAYERS)} online"]
    for p in PLAYERS.values():
        who = f"@{p.fren_tag}" if p.fren_tag else p.name
        lines.append(f"     - {who:<18} room={p.room:<9} up={_fmt_dur(time.time() - p.connected_at)} "
                     f"idle={_fmt_dur(time.time() - p.idle_since)}{'  [admin]' if p.is_admin else ''}")
    backend, where = type(STORE).__name__, getattr(STORE, "path", "postgres DB-2")
    lines += [
        f"  runes etched: {RUNES_ETCHED} this session",
        f"  world store : {backend} @ {where}",
        f"  oracle      : {('local LLM (' + GEN_MODEL + ')') if (INFERENCE_BASE_URL and GEN_MODEL) else 'scripted fallback'}",
        f"  matrix chat : {'ON' if CHAT_MATRIX else 'off (local-only)'}",
    ]
    return "\n".join(lines)


# --- operator actions (shared by all three surfaces) -------------------------
async def op_broadcast(msg: str) -> str:
    text = c(BOLD + MAG, f"\n[operator] {msg}\n")
    for w, pl in list(PLAYERS.items()):
        try:
            await pl.send(text)
        except Exception:
            pass
    return f"broadcast to {len(PLAYERS)} player(s)"


async def op_kick(name: str) -> str:
    for w, pl in list(PLAYERS.items()):
        if pl.name.lower() == name.lower() or (pl.fren_tag or "").lower() == name.lstrip("@").lower():
            try:
                await pl.send(c(RED, "\nAn operator disconnected you. Your progress is saved. 💜\n"))
                w.close()
            except Exception:
                pass
            PLAYERS.pop(w, None)
            return f"kicked {pl.name}"
    return f"no player matching '{name}'"


async def op_shutdown(reason: str = "maintenance", reboot: bool = False) -> str:
    global REBOOT
    REBOOT = reboot
    verb = "rebooting" if reboot else "shutting down"
    await op_broadcast(f"P.O.K.E. is {verb} now ({reason}). Your progress is saved — back soon, fren. 💜")
    await asyncio.sleep(0.3)
    SHUTDOWN.set()
    return verb


def set_chat_matrix(on: bool) -> str:
    global CHAT_MATRIX
    CHAT_MATRIX = on
    return f"matrix chat {'ON — say/chat now mirror to the Matrix verse' if on else 'off — local rooms only'}"


async def forward_chat_to_matrix(room: str, sender: str, body: str) -> None:
    """COLD, fire-and-forget: mirror a chat line into the Matrix class/verse room. Only when the
    operator has opted in (CHAT_MATRIX). Best-effort — never blocks or errors the gameplay path."""
    if not CHAT_MATRIX:
        return

    def _post():
        try:
            data = json.dumps({"room": room, "sender": sender, "body": body}).encode()
            req = urllib.request.Request(MATRIX_BRIDGE_URL.rstrip("/") + "/message", data=data,
                                         headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=2)
        except Exception:
            pass  # matrix-bridge offline / not opted-in networks — silently skip

    try:
        await asyncio.to_thread(_post)
    except Exception:
        pass


# --- local terminal console (operator on the box) ----------------------------
CONSOLE_HELP = (
    "P.O.K.E. operator console:\n"
    "  stats                 live players + node status\n"
    "  who                   who's online\n"
    "  nodes                 knowledge-swarm sync status\n"
    "  broadcast <message>   message every player\n"
    "  kick <name>           disconnect a player (progress is saved)\n"
    "  chat on|off           mirror chat to the Matrix verse (default off)\n"
    "  reboot                graceful restart (drains players; state persists)\n"
    "  shutdown              graceful stop\n"
    "  help"
)


async def handle_console(cmd: str) -> None:
    verb, _, rest = cmd.partition(" ")
    verb, rest = verb.lower().strip(), rest.strip()
    if not verb:
        return
    if verb in ("help", "?"):
        print(CONSOLE_HELP)
    elif verb in ("stats", "status"):
        print(stats_report())
    elif verb == "who":
        print(f"{len(PLAYERS)} online: " + ", ".join((f"@{p.fren_tag}" if p.fren_tag else p.name) for p in PLAYERS.values()))
    elif verb in ("nodes", "swarm"):
        print(nodes_report(await get_swarm_status(force=True)))
    elif verb in ("broadcast", "bcast", "say"):
        print(await op_broadcast(rest) if rest else "usage: broadcast <message>")
    elif verb == "kick":
        print(await op_kick(rest) if rest else "usage: kick <name>")
    elif verb == "chat":
        print(set_chat_matrix(rest.lower() in ("on", "1", "true", "yes")))
    elif verb == "reboot":
        print(await op_shutdown("operator reboot", reboot=True))
    elif verb == "shutdown":
        print(await op_shutdown("operator shutdown", reboot=False))
    else:
        print(f"unknown console command '{verb}' — type help")


def _start_console(loop: asyncio.AbstractEventLoop) -> None:
    """Read operator commands from the server's own stdin (if any). Degrades to a no-op when
    stdin is closed (e.g. running detached) — in-MUD `admin` and the HTTP rails still work."""
    def run() -> None:
        try:
            for line in sys.stdin:
                asyncio.run_coroutine_threadsafe(handle_console(line.strip()), loop)
        except Exception:
            pass
    threading.Thread(target=run, daemon=True).start()


async def _status_ticker(interval: int = 60) -> None:
    while not SHUTDOWN.is_set():
        try:
            await asyncio.wait_for(SHUTDOWN.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass
        if SHUTDOWN.is_set():
            break
        sw = await get_swarm_status()
        peers = sw.get("peers", sw.get("nodes", 0)) if sw.get("online") else "offline"
        print(f"[status] {len(PLAYERS)} online · swarm nodes: {peers} · uptime {_fmt_dur(time.time() - SERVER_START)}")


# --- HTTP control rails (for the web-admin techstack; localhost + token) ------
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer  # noqa: E402


class _AdminHTTP(BaseHTTPRequestHandler):
    def _authed(self) -> bool:
        tok = self.headers.get("X-POKE-Admin-Token", "")
        return bool(tok) and secrets.compare_digest(tok, ADMIN_TOKEN)

    def _reply(self, code: int, obj: dict) -> None:
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _run(self, coro, timeout: float = 4.0):
        return asyncio.run_coroutine_threadsafe(coro, LOOP).result(timeout=timeout)

    def do_GET(self) -> None:
        if not self._authed():
            return self._reply(401, {"error": "unauthorized"})
        path = self.path.split("?")[0].rstrip("/")
        if path in ("", "/stats", "/health"):
            self._reply(200, stats_json())
        elif path == "/nodes":
            self._reply(200, self._run(get_swarm_status(True)))
        else:
            self._reply(404, {"error": "not found"})

    def do_POST(self) -> None:
        if not self._authed():
            return self._reply(401, {"error": "unauthorized"})
        length = int(self.headers.get("Content-Length", 0) or 0)
        try:
            data = json.loads(self.rfile.read(length) or b"{}") if length else {}
        except Exception:
            data = {}
        path = self.path.split("?")[0].rstrip("/")
        if path == "/broadcast":
            self._reply(200, {"ok": True, "result": self._run(op_broadcast(data.get("message", "")))})
        elif path == "/kick":
            self._reply(200, {"ok": True, "result": self._run(op_kick(data.get("player", "")))})
        elif path == "/chat":
            self._reply(200, {"ok": True, "result": set_chat_matrix(bool(data.get("enabled")))})
        elif path == "/reboot":
            self._run(op_shutdown("web-admin reboot", reboot=True), timeout=2)
            self._reply(200, {"ok": True, "result": "rebooting"})
        elif path == "/shutdown":
            self._run(op_shutdown("web-admin shutdown", reboot=False), timeout=2)
            self._reply(200, {"ok": True, "result": "shutting down"})
        else:
            self._reply(404, {"error": "not found"})

    def log_message(self, *args) -> None:
        pass  # quiet; operator actions are reported via the console/stats


def _start_admin_http() -> "ThreadingHTTPServer | None":
    try:
        srv = ThreadingHTTPServer((ADMIN_HTTP_HOST, ADMIN_HTTP_PORT), _AdminHTTP)
    except OSError as e:
        print(f"! web-admin rails not started on {ADMIN_HTTP_HOST}:{ADMIN_HTTP_PORT} ({e})")
        return None
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


# --- in-MUD admin (operator elevates with the token, then drives the node) ----
async def admin_command(p: Player, rest: str) -> None:
    sub, _, arg = rest.partition(" ")
    sub, arg = sub.lower().strip(), arg.strip()
    if not p.is_admin:
        if sub and secrets.compare_digest(sub, ADMIN_TOKEN):
            p.is_admin = True
            await p.send(c(GREEN, "  Operator mode on. ")
                         + c(GREY, "admin: stats · nodes · broadcast <m> · kick <n> · chat on|off · reboot · shutdown\n"))
        else:
            await p.send(c(RED, "  Operator only. Authenticate: ") + c(CYAN, "admin <token>")
                         + c(GREY, "  (the token prints in the server console)\n"))
        return
    if sub in ("", "stats", "status"):
        await p.send(c(GREEN, stats_report()) + "\n")
    elif sub in ("nodes", "swarm"):
        await p.send(c(GREEN, nodes_report(await get_swarm_status(force=True))) + "\n")
    elif sub in ("broadcast", "bcast"):
        await p.send(c(GREY, (await op_broadcast(arg)) if arg else "usage: admin broadcast <message>") + "\n")
    elif sub == "kick":
        await p.send(c(GREY, (await op_kick(arg)) if arg else "usage: admin kick <name>") + "\n")
    elif sub == "chat":
        await p.send(c(GREY, set_chat_matrix(arg.lower() in ("on", "1", "true", "yes"))) + "\n")
    elif sub == "reboot":
        await p.send(c(RED, "Rebooting the node…\n"))
        await op_shutdown("in-MUD operator reboot", reboot=True)
    elif sub == "shutdown":
        await p.send(c(RED, "Shutting the node down…\n"))
        await op_shutdown("in-MUD operator shutdown", reboot=False)
    else:
        await p.send(c(GREY, "admin: stats | nodes | broadcast <m> | kick <n> | chat on|off | reboot | shutdown\n"))


async def dispatch(p: Player, line: str) -> bool:
    verb, _, rest = line.strip().partition(" ")
    verb = verb.lower()
    rest = rest.strip()
    p.idle_since = time.time()   # activity, for operator stats

    if verb in ("quit", "exit", "q"):
        await p.send(c(MAG, "The cabinets dim. Come back soon, fren. 💜\n"))
        return False
    if verb in ("help", "?", "commands"):
        await p.send(HELP + "\n")
    elif verb in ("look", "l"):
        await p.send(render_board(p))
    elif verb in ("go", "move", "walk"):
        await move(p, rest)
    elif verb in DIRS or verb in DIR_ALIAS:
        await move(p, DIR_ALIAS.get(verb, verb))
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
    elif verb == "link":
        await link_identity(p, rest)
    elif verb in ("profile", "whoami", "me"):
        await show_profile(p)
    elif verb == "admin":
        await admin_command(p, rest)
    elif verb == "say":
        if rest:
            who = f"@{p.fren_tag}" if p.fren_tag else p.name
            tail = c(GREY, "  (→ matrix verse)") if CHAT_MATRIX else ""
            await p.send(c(GREEN, "You say: ") + c(BOLD, rest) + tail + "\n")
            await broadcast_room(p.room, c(CYAN, f"\n{who} says: ") + c(BOLD, rest) + "\n", exclude=p)
            if CHAT_MATRIX:   # COLD, fire-and-forget — never blocks the hot path
                asyncio.create_task(forward_chat_to_matrix(p.room, who, rest))
        else:
            await p.send(c(GREY, "Say what?\n"))
    elif verb in ("certs", "runes", "certificates"):
        await show_certs(p)
    elif verb in ("inventory", "inv", "i"):
        inv = ", ".join(p.inventory) if p.inventory else "nothing but curiosity"
        await p.send(c(GREEN, "You carry: ") + inv + "\n")
    elif verb == "who":
        names = ", ".join((f"@{pl.fren_tag}" if pl.fren_tag else pl.name) for pl in PLAYERS.values())
        await p.send(c(GREEN, f"Frens in the arcade ({len(PLAYERS)}): ") + names + "\n")
    elif p.oracle_pending:
        await oracle_judge(p, line.strip())
    else:
        await p.send(c(GREEN, f"You aren't sure how to '{verb}', fren. Try ") + c(CYAN, "help") + c(GREEN, ".\n"))
    return True


async def move(p: Player, direction: str) -> None:
    direction = DIR_ALIAS.get(direction.lower(), direction.lower())
    exits = ROOMS[p.room]["exits"]
    if direction in exits:
        who = f"@{p.fren_tag}" if p.fren_tag else p.name
        await broadcast_room(p.room, c(GREY, f"\n{who} heads {direction}.\n"), exclude=p)
        p.room = exits[direction]
        await asyncio.to_thread(STORE.save_player, p.name, p.room, p.inventory)
        await broadcast_room(p.room, c(GREY, f"\n{who} arrives.\n"), exclude=p)
        await p.send(render_board(p))
    else:
        await p.send(c(GREEN, "You can't go that way, fren.\n"))


async def pull(p: Player, thing: str) -> None:
    if "lever" in thing.lower() and p.room == "vault":
        state = not await asyncio.to_thread(STORE.get_feature, "vault", "lever", False)
        await asyncio.to_thread(STORE.set_feature, "vault", "lever", state)
        if state:
            await p.send(c(GOLD, "You heave the lever. Gears grind; the gold-banded chest clicks. Inside: a SCROLL.\n"))
            await p.stream(c(GREY, "(A lever pulled here is exactly the event a lever pull in the Luanti voxel world "
                                  "would send — one world, two windows. In production this routes through state-sync.)"))
            if "the scroll (keep it secret)" not in p.inventory:
                p.inventory.append("the scroll (keep it secret)")
                await asyncio.to_thread(STORE.save_player, p.name, p.room, p.inventory)
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
        await p.send(c(GOLD, f"  * {cert['rune_name']}  ") + c(GREEN, f"— {cert['title']}  ")
                     + c(GREY, f"(earned {cert['block_time']}, block {cert['block_height']})\n"))
    await p.send(c(MAG, "  Non-transferable by design. Move one and provenance still names you as the earner. 💜\n"))


# --- connection handling -----------------------------------------------------
def clean_line(raw: bytes) -> str:
    out = bytearray()
    i = 0
    while i < len(raw):
        b = raw[i]
        if b == 0xFF:
            i += 3
            continue
        if b in (0x08, 0x7F):
            i += 1
            continue
        out.append(b)
        i += 1
    return out.decode("utf-8", "replace").strip()


async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    p = Player(writer)
    PLAYERS[writer] = p
    try:
        await p.send(RESIZE + CLEAR)          # fresh screen; ask for a comfy size (resize freely after)
        await p.send(BANNER)
        await p.send(c(AMBER, "By what name shall the arcade know you, fren? "))
        raw = await reader.readline()
        name = clean_line(raw)
        if name:
            p.name = name[:24]
        data = await asyncio.to_thread(STORE.get_or_create_player, p.name)
        p.room, p.inventory, p.wallet = data["room"], data["inventory"], data["wallet"]
        p.nostr, p.space, p.fren_tag = data["nostr"], data["space"], data["fren_tag"]
        p.certs = await asyncio.to_thread(STORE.list_certificates, p.name)
        hello = f"@{p.fren_tag}" if p.fren_tag else p.name
        if data["new"]:
            await p.send(c(MAG, f"\nWelcome, {hello}. The high score is understanding. 💜\n"))
            await p.send(c(GREY, "  New here? Type ") + c(CYAN, "help") + c(GREY, ", or ") + c(CYAN, "link fren <name>") + c(GREY, " to claim your @handle.\n"))
        else:
            note = f" You carry {len(p.certs)} class rune(s)." if p.certs else ""
            await p.send(c(MAG, f"\nWelcome back, {hello}.{note} Your progress was kept. 💜\n"))
        await broadcast_room(p.room, c(GREY, f"\n{hello} steps in from the street.\n"), exclude=p)
        await p.send(render_board(p))
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
        who = f"@{p.fren_tag}" if p.fren_tag else p.name
        await broadcast_room(p.room, c(GREY, f"\n{who} fades from the arcade.\n"))
        try:
            writer.close()
        except Exception:
            pass


async def main() -> None:
    global SERVER, LOOP
    LOOP = asyncio.get_running_loop()
    backend = type(STORE).__name__
    store_where = getattr(STORE, "path", "postgres DB-2")
    oracle = "local LLM" if (INFERENCE_BASE_URL and GEN_MODEL) else "scripted pacbot fallback"
    SERVER = await asyncio.start_server(handle_client, MUD_HOST, MUD_PORT)
    print(f"▓ Pac's Arcade · P.O.K.E. MUD on {MUD_HOST}:{MUD_PORT}  [persisted via {backend} @ {store_where}, Oracle: {oracle}] 💜")
    print(f"  Connect:  python services/mud/play.py    (or: telnet {MUD_HOST} {MUD_PORT})")

    # operator surfaces: local console (stdin), web-admin HTTP rails, periodic status line
    http_srv = _start_admin_http()
    _start_console(LOOP)
    ticker = asyncio.create_task(_status_ticker())
    tok_note = "  (auto-generated; set PA_ADMIN_TOKEN to pin it)" if ADMIN_TOKEN_GENERATED else ""
    print("  Operator console: type 'help' here.")
    print(f"    admin token : {ADMIN_TOKEN}{tok_note}   (in-MUD: 'admin {ADMIN_TOKEN}')")
    if http_srv:
        print(f"    web rails   : http://{ADMIN_HTTP_HOST}:{ADMIN_HTTP_PORT}  "
              "(GET /stats /nodes · POST /broadcast /kick /chat /reboot /shutdown · header X-POKE-Admin-Token)")
    print(f"    matrix chat : {'ON' if CHAT_MATRIX else 'off (default) — enable with  admin chat on'}")

    try:
        async with SERVER:
            await SHUTDOWN.wait()
    finally:
        ticker.cancel()
        # graceful drain — every player's room/inventory/runes already persist in the world store
        for w, pl in list(PLAYERS.items()):
            try:
                await pl.send(c(MAG, "\nThe arcade lights power down. Your progress is saved. 💜\n"))
                w.close()
            except Exception:
                pass
        try:
            STORE.close()
        except Exception:
            pass

    if REBOOT:
        print("▓ rebooting P.O.K.E. …")
        os.execv(sys.executable, [sys.executable] + sys.argv)
    else:
        print("▓ P.O.K.E. stopped. GG, fren. 💜")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n▓ MUD shutting down. GG, fren. 💜")
