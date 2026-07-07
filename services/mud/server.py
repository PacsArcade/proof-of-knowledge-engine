"""mud/server.py — Pac's Arcade · Proof of Knowledge Engine (P.O.K.E.) — the MUD. 💜

A PERSISTENT-WINDOW text client. The game lives in one fixed frame that REDRAWS in place: the
room, the Oracle's dialogue, your rune card, your profile — they update inside the window instead
of scrolling away. A message log under the window carries transient lines (says, arrivals,
operator notices). Special effects (boss animations) redraw the window frame-by-frame.

  ── DEV MODE (runnable today, zero deps) ─────────────────────────────────────────────────────
      python services/mud/server.py            # serves on 127.0.0.1:4000  (+ admin rails on 4001)
      python services/mud/play.py              # a tiny client (or telnet / a MUD client)

  World state persists (services/common/world_store.py). Oracle uses your local LLM if
  PA_INFERENCE_BASE_URL + PA_GEN_MODEL are set, else a scripted pacbot fallback.

Production: reads/writes go through state-sync; boss art is generated offline (asciify / chafa /
ffmpeg → frames dropped in services/mud/art/) since tplay renders only to a live terminal.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import secrets
from collections import deque
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
FRENS_URL = os.environ.get("PA_FRENS_URL", "")   # empty => this node is standalone
MUD_WS_PORT = int(os.environ.get("PA_MUD_WS_PORT", "4002"))   # browser WebSocket bridge (play in a browser)
LOCAL_SITE_URL = os.environ.get("PA_LOCAL_SITE_URL", "")      # the physically-local pacsarcade-area website
# The world/verse this node hosts — shown in the operator console. Ties to the server's space once
# the owner links it (PA_SPACE), else the node name, else the default POKEMUD world.
WORLD = os.environ.get("PA_SPACE") or os.environ.get("PA_NODE_NAME") or "POKEMUD"


def frens_aware() -> bool:
    """True when this node is wired to the frens.earth verse (so we walk users through linking)."""
    return bool(FRENS_URL)


# --- persistence (shared with state-sync) ------------------------------------
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "common"))
import world_store  # noqa: E402
import webbridge     # noqa: E402  (same dir as this file — the browser WebSocket bridge)

try:
    STORE = world_store.open_store()
except Exception as e:
    print(f"! persistence backend failed ({e}); falling back to the SQLite dev store")
    os.environ["PA_GAMESTATE_BACKEND"] = "sqlite"
    STORE = world_store.open_store()

# --- operator console / admin state ------------------------------------------
SERVER_START = time.time()
ADMIN_TOKEN = os.environ.get("PA_ADMIN_TOKEN") or secrets.token_hex(4)
ADMIN_TOKEN_GENERATED = "PA_ADMIN_TOKEN" not in os.environ
RUNES_ETCHED = 0
ADMIN_HTTP_HOST = os.environ.get("PA_MUD_ADMIN_HOST", "127.0.0.1")
ADMIN_HTTP_PORT = int(os.environ.get("PA_MUD_ADMIN_PORT", "4001"))
CHAT_MATRIX = os.environ.get("PA_CHAT_MATRIX", "off").lower() in ("1", "true", "on", "yes")
MATRIX_BRIDGE_URL = os.environ.get("PA_MATRIX_BRIDGE_URL", "http://matrix-bridge:8084")

SERVER = None
LOOP = None
REBOOT = False
SHUTDOWN = asyncio.Event()

# --- screen control ----------------------------------------------------------
HOME = "\x1b[H"                       # cursor to top-left (in-place redraw)
CLEAR = "\x1b[2J\x1b[3J\x1b[H"        # full clear + scrollback, home
RESIZE = "\x1b[8;42;112t"            # ask for 42x112 (honored by some terminals; resize freely)

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


# --- banner (simple + aligned; shown once before the game window) ------------
def make_banner(accent: str = BOLD + GOLD) -> str:
    """The login banner. `accent` colors the POKEMUD title — cycled to make it glimmer."""
    lines = [
        "",
        "PAC'S  ARCADE",
        "presents",
        "",
        "P  O  K  E  M  U  D",
        "the Proof of Knowledge Engine",
        "",
        "type  help  for the controls   ·   type  quit  to leave",
        "",
    ]
    width = max(len(l) for l in lines) + 8
    out = [c(MAG, "╔" + "═" * width + "╗")]
    for ln in lines:
        if "P  O  K  E" in ln:
            col = accent
        elif "PAC'S" in ln:
            col = BOLD + AMBER
        elif "Proof of Knowledge" in ln:
            col = AMBER
        else:
            col = GREY
        out.append(c(MAG, "║") + c(col, ln.center(width)) + c(MAG, "║"))
    out.append(c(MAG, "╚" + "═" * width + "╝"))
    return "\n" + "\n".join(out) + "\n" + c(GREY, "  a study buddy for your cyberdeck  ·  welcome, fren. 💜") + "\n"


BANNER = make_banner()
# Colors the title cycles through on login so PAC'S ARCADE / POKEMUD glimmers.
SHIMMER = [BOLD + GOLD, BOLD + CYAN, BOLD + MAG, BOLD + AMBER, BOLD + GREEN, BOLD + GOLD]

HELP_LINES = [
    "How to play:",
    "",
    "  look (l)              look around the room",
    "  north/south/east/west go through a door  (also n/s/e/w)",
    "  talk oracle           speak with the Oracle (it asks; you answer)",
    "  answer <text>         answer the Oracle or a boss  ·  ask oracle <q>",
    "  challenge             face the boss (the dungeon is  down  from entrance)",
    "  pull lever            operate a feature in the room",
    "  stats                 your attributes  ·  examine <name>  see a fren",
    "  link fren <name>      claim your @fren + get a code to link it",
    "  verify <code> · backup  confirm your @fren · anchor progress on-chain",
    "  profile · certs · inventory · who · say <msg>",
    "",
    "  You don't have to be exact — just type naturally. 'sup' to the Oracle,",
    "  'go down', 'who's the boss' all work. The game figures it out.",
]


# --- the world ---------------------------------------------------------------
ROOM_ART = {
    "entrance": [
        "  ┌──┐  ┌──┐  ┌──┐     ~ insert token ~",
        "  │▓▓│  │░░│  │▓▓│",
        "  └──┘  └──┘  └──┘",
    ],
    "alcove": [
        "         .-\"\"\"-.",
        "        ( o   o )     the Oracle waits, patient",
        "         '-...-'",
    ],
    "vault": [
        "     .------------.",
        "     | [#]     ()  |   a sealed chest, banded in gold",
        "     '------------'",
    ],
    "dungeon": [
        "        .-~~~-.",
        "      /  x   x  \\    something flickers between two places",
        "      \\   \\_/   /    — here, and not-here",
        "        '-...-'",
    ],
}

ROOMS = {
    "entrance": {
        "title": "The Arcade Entrance",
        "desc": ("CRT cabinets hum in the dark, throwing blue light across the carpet. A neon sign "
                 "buzzes: PAC'S ARCADE — KNOWLEDGE IS THE HIGH SCORE. A worn token-slot glows, waiting. "
                 "A stairwell descends into a cold blue glow."),
        "exits": {"north": "alcove", "east": "vault", "down": "dungeon"},
        "npcs": [],
    },
    "dungeon": {
        "title": "The Proof Dungeon",
        "desc": ("Down here the hum turns to a drone. Something vast and half-real coils in the dark, "
                 "flickering between two places at once. It has been trying to spend the same coin "
                 "twice since before you were born. Type  challenge  to face it."),
        "exits": {"up": "entrance"},
        "npcs": ["wraith"],
    },
    "alcove": {
        "title": "The Oracle's Alcove",
        "desc": ("A single cabinet stands apart, its screen a calm violet. A brass plate reads ASK, "
                 "AND DEMONSTRATE. This is where the Oracle holds court, trading questions for "
                 "understanding. It never lectures. It only asks."),
        "exits": {"south": "entrance"},
        "npcs": ["oracle"],
    },
    "vault": {
        "title": "The Puzzle Vault",
        "desc": ("Cold stone, warmer than it looks. A great iron LEVER juts from the wall beside a "
                 "sealed chest banded in gold. Etched above it: 'What is written here, only you may "
                 "keep. Lose the scroll, lose the treasure.' The lever is a logic gate — pull it."),
        "exits": {"west": "entrance"},
        "npcs": [],
    },
}

PLAYERS: dict[asyncio.StreamWriter, "Player"] = {}
BOARD_W = 72     # inner width of the play window
BODY_H = 12      # fixed number of body rows (keeps the window from jumping)
LOG_H = 6        # message-log rows under the window


# --- rune-etch animation (a boss/effect plays as frames INSIDE the window) ----
# Frames use ASCII-only art (no double-width glyphs) so the window border never breaks.
RUNE_ANIM = [
    ["", "", "            .   *   .", "         *    ( )    *", "            '   |   '",
     "            the die is cut...", "", ""],
    ["", "", "          * .    |    . *", "        (    \\   |   /    )", "          * '  \\ | /  ' *",
     "            the rune takes form...", "", ""],
    ["", "", "           \\    |    /", "         ---   (*)   ---", "           /    |    \\",
     "            binding to the chain...", "", ""],
    ["", "", "              \\  |  /", "            ==  RUNE  ==", "              /  |  \\",
     "            SEALED on-chain.", "", ""],
]


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
        self.frens_code = None             # pending @fren pairing code
        self.xp = 0
        self.level = 1
        self.energy = 100
        self.oracle_pending = False
        self.boss_pending = None           # boss id awaiting an answer
        self.focus: dict | None = None     # the window's current panel {title, lines, color}
        self.log: list[str] = []           # message-log strip (transient lines)
        self.connected_at = time.time()
        self.idle_since = time.time()
        self.is_admin = False
        self.in_game = False               # False until past the name prompt
        self.web = False                   # True for browser clients (WebSocket + JSON render mode)
        self.pending_fx: list[str] = []    # one-shot effect cues for the web client (etch/victory/levelup)
        self.session_start_xp = 0          # snapshots for the "goodnight" session summary
        self.session_start_runes = 0
        self.muted = False                 # operator moderation
        self.timeout_until = 0.0
        self.watched = False

    async def send(self, text: str) -> None:
        self.writer.write(text.encode("utf-8", "replace"))
        await self.writer.drain()


# --- window rendering (the persistent frame) ---------------------------------
def _wrap(text: str, width: int) -> list[str]:
    out: list[str] = []
    for para in text.split("\n"):
        out += textwrap.wrap(para, width) or [""]
    return out


def focus_room(p: Player) -> None:
    room = ROOMS[p.room]
    lines: list[str] = []
    art = ROOM_ART.get(p.room)
    if art:
        lines += art + [""]
    lines += _wrap(room["desc"], BOARD_W - 4)
    lines.append("")
    if room["npcs"]:
        hint = "(type 'challenge')" if "wraith" in room["npcs"] else "(try 'talk oracle')"
        lines.append("Here: " + ", ".join(n.title() for n in room["npcs"]) + "   " + hint)
    others = [pl.name for w, pl in PLAYERS.items() if pl.room == p.room and pl is not p]
    if others:
        lines.append("Also here: " + ", ".join(others))
    lines.append("")
    lines.append("Exits: " + ", ".join(room["exits"].keys()))    # also shown as arrows on the frame
    p.focus = {"title": room["title"], "lines": lines, "color": GREEN}


def focus_text(p: Player, title: str, lines: list[str], color: str = GREEN) -> None:
    p.focus = {"title": title, "lines": list(lines), "color": color}


def push(p: Player, line: str) -> None:
    p.log.append(line)
    p.log = p.log[-LOG_H:]


def _render_border(chars: list[str], doors: set) -> str:
    """Join a border char list, coloring door positions CYAN (like the ◄ ► side doors) and the
    rest magenta — so every exit is the same cyan-arrow style."""
    out, i, n = "", 0, len(chars)
    while i < n:
        run = i in doors
        j = i
        while j < n and (j in doors) == run:
            j += 1
        seg = "".join(chars[i:j])
        out += c(CYAN, seg) if run else c(MAG, seg)
        i = j
    return out


def _frame(title: str, body: list[str], exits: dict, color: str) -> list[str]:
    W = BOARD_W
    rows = list(body)[:BODY_H]
    while len(rows) < BODY_H:
        rows.append("")
    mid = BODY_H // 2

    # top: cyan ▲ (north, centered) + a cyan ▲up corner (up), then the title
    top = list("═" * W); tdoors = set()
    if "north" in exits:
        top[W // 2] = "▲"; tdoors.add(W // 2)
    if "up" in exits:
        for j, ch in enumerate("▲up"):
            top[W - 7 + j] = ch; tdoors.add(W - 7 + j)
    for i, ch in enumerate(f"╡ {title} ╞"):
        if 3 + i < W and (3 + i) not in tdoors:
            top[3 + i] = ch
    out = [c(MAG, "╔") + _render_border(top, tdoors) + c(MAG, "╗")]

    # sides: cyan ◄ / ► doors on the middle row
    for i, line in enumerate(rows):
        left = c(CYAN, "◄") if (i == mid and "west" in exits) else c(MAG, "║")
        right = c(CYAN, "►") if (i == mid and "east" in exits) else c(MAG, "║")
        out.append(left + " " + c(color, line[:W - 2].ljust(W - 2)) + " " + right)

    # bottom: cyan ▼ (south, centered) + a cyan ▼dn corner (down)
    bot = list("═" * W); bdoors = set()
    if "south" in exits:
        bot[W // 2] = "▼"; bdoors.add(W // 2)
    if "down" in exits:
        for j, ch in enumerate("▼dn"):
            bot[W - 7 + j] = ch; bdoors.add(W - 7 + j)
    out.append(c(MAG, "╚") + _render_border(bot, bdoors) + c(MAG, "╝"))
    return out


def render_screen(p: Player) -> str:
    room = ROOMS[p.room]
    f = p.focus or {"title": room["title"], "lines": [], "color": GREEN}
    who = f"@{p.fren_tag}" if p.fren_tag else p.name
    header = c(BOLD + MAG, "  PAC'S ARCADE · P.O.K.E.") + c(GREY, f"      {who} · {room['title']}")
    hud = ("  " + c(GOLD, f"⭐ Lv {p.level}") + c(GREY, " · ") + c(CYAN, f"✦ {p.xp} xp")
           + c(GREY, " · ") + c(GOLD, f"🎓 {len(p.certs)}") + c(GREY, " · ") + c(GREEN, f"⚡ {p.energy}"))
    frame = _frame(f["title"], f["lines"], room["exits"], f.get("color", GREEN))
    log = list(p.log)[-LOG_H:]
    log = [""] * (LOG_H - len(log)) + log            # bottom-align the log
    parts = [header, hud, ""] + frame + ["", c(GREY, "  ── messages ──")]
    parts += ["  " + l for l in log]
    parts += ["", c(AMBER, f"  {who} ") + c(GREY, "» ")]
    out = HOME
    for ln in parts[:-1]:
        out += ln + "\x1b[K\r\n"
    out += parts[-1] + "\x1b[K\x1b[J"                # prompt; clear anything below
    return out


# --- JSON render mode (browser clients) --------------------------------------
# Telnet clients get ANSI (render_screen). Browser clients get a STRUCTURED screen model, so the
# web client can render it as real UI — glow, animation, sound — instead of interpreting ANSI.
_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_COLOR_NAME = {GREEN: "green", AMBER: "amber", CYAN: "cyan", MAG: "magenta",
               GREY: "grey", RED: "red", GOLD: "gold"}


def _plain(s: str) -> str:
    return _ANSI.sub("", s)


def _color_name(ansi: str) -> str:
    return _COLOR_NAME.get(ansi, "green")


def display_name(p: "Player") -> str:
    return f"@{p.fren_tag}" if p.fren_tag else p.name


def screen_model(p: "Player") -> dict:
    """The structured screen the browser renders. Everything is plain text + hints — no ANSI."""
    room = ROOMS[p.room]
    f = p.focus or {"title": room["title"], "lines": [], "color": GREEN}
    fx, p.pending_fx = p.pending_fx, []
    return {
        "t": "screen",
        "room": room["title"],
        "who": display_name(p),
        "hud": {"level": p.level, "xp": p.xp, "xp_into": p.xp % 100,
                "runes": len(p.certs), "energy": p.energy},
        "title": f.get("title") or room["title"],
        "color": _color_name(f.get("color", GREEN)),
        "body": [_plain(l) for l in f.get("lines", [])],
        "exits": list(room["exits"].keys()),
        "log": [_plain(l) for l in list(p.log)[-LOG_H:]],
        "fx": fx,
    }


async def show(p: Player) -> None:
    if not p.in_game:
        return
    if p.web:
        await p.send(json.dumps(screen_model(p)))
    else:
        await p.send(render_screen(p))


# Command words a player may NOT use as a name (so nobody is called "help" or "quit").
RESERVED_NAMES = {"help", "quit", "exit", "q", "look", "l", "admin", "oracle", "wraith", "boss",
                  "say", "go", "north", "south", "east", "west", "up", "down", "n", "s", "e", "w",
                  "talk", "answer", "ask", "challenge", "fight", "stats", "profile", "certs", "runes",
                  "inventory", "inv", "i", "backup", "link", "verify", "who", "pull", "examine"}


async def _prompt_again(p: "Player", text: str) -> None:
    """Re-ask for a name (structured for web, ANSI for telnet)."""
    if p.web:
        await p.send(json.dumps({"t": "prompt", "text": text}))
    else:
        await p.send(c(AMBER, "\r\n" + text + " "))


async def animate(p: Player, frames: list[list[str]], title: str, color: str = GOLD, hold: float = 0.5) -> None:
    """Play ASCII frames inside the window — the primitive bosses & lesson effects use."""
    for frame in frames:
        focus_text(p, title, frame, color)
        await show(p)
        await asyncio.sleep(hold)


# --- the Oracle --------------------------------------------------------------
SELF_CUSTODY = {"class_id": "self-custody", "rune": "PACS•SELF•CUSTODY", "title": "Bitcoin Self-Custody 101"}
ORACLE_QUESTION = ("With a bitcoin wallet there is ONE secret that is yours alone — lose it and the "
                   "coins are gone, share it and they're stolen. What is that secret called?")
ORACLE_KEYS = ("seed", "recovery phrase", "recovery-phrase", "private key", "privatekey", "mnemonic", "seed phrase")


def _oracle_panel(lines: list[str]) -> list[str]:
    return ["", "  The Oracle's screen warms from violet to gold.", ""] + ["  " + l for l in lines]


async def oracle_open(p: Player) -> None:
    p.oracle_pending = True
    body = _oracle_panel(_wrap('"' + ORACLE_QUESTION + '"', BOARD_W - 6) + ["", "(answer with:  answer <your words>)"])
    focus_text(p, "The Oracle", body, MAG)


async def oracle_judge(p: Player, ans: str) -> None:
    p.oracle_pending = False
    low = ans.lower()
    if any(k in low for k in ORACLE_KEYS):
        if await asyncio.to_thread(STORE.has_certificate, p.name, SELF_CUSTODY["class_id"]):
            focus_text(p, "The Oracle", _oracle_panel(_wrap(
                '"Yes — the seed phrase. But you already hold this rune, fren; I don\'t etch a truth twice. '
                'Wear it well."', BOARD_W - 6)), MAG)
        else:
            global RUNES_ETCHED
            RUNES_ETCHED += 1
            await asyncio.to_thread(STORE.record_competency, p.name, "bitcoin-self-custody", 0.9,
                                    "Understood the seed phrase is the treasure, not a resettable password.")
            push(p, c(MAG, 'The Oracle: "You understood the stakes, not a definition."'))
            await etch_class_rune(p, SELF_CUSTODY)
    else:
        p.oracle_pending = True
        focus_text(p, "The Oracle", _oracle_panel(_wrap(
            '"Close — but feel the weight of it. Not your address, not your PIN. The one string of words '
            'that IS the money. Try again:  answer <text>"', BOARD_W - 6)), MAG)


async def oracle_freeform(p: Player, question: str) -> None:
    focus_text(p, "The Oracle", _oracle_panel(["…the Oracle considers…"]), MAG)
    await show(p)
    reply = ""
    if INFERENCE_BASE_URL and GEN_MODEL:
        reply = await asyncio.get_event_loop().run_in_executor(None, _llm_reply, question)
    if not reply:
        reply = ("A fine question. I won't hand you the answer — that's not how the high score is earned. "
                 "What would have to be TRUE for that to make sense? Reason it aloud. "
                 "(Set PA_GEN_MODEL with a local model to hear me think freely.)")
    focus_text(p, "The Oracle", _oracle_panel(_wrap('"' + reply.strip() + '"', BOARD_W - 6)), MAG)


def _llm_reply(question: str) -> str:
    try:
        body = json.dumps({
            "model": GEN_MODEL,
            "messages": [
                {"role": "system", "content": "You are the Oracle at Pac's Arcade — a Socratic bitcoin/nostr "
                 "educator. Say 'fren', never 'friend'. Be brief (2-3 sentences), ask a probing question."},
                {"role": "user", "content": question},
            ],
            "max_tokens": 160, "temperature": 0.7,
        }).encode()
        req = urllib.request.Request(INFERENCE_BASE_URL.rstrip("/") + "/chat/completions",
                                     data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=8) as r:
            return json.loads(r.read())["choices"][0]["message"]["content"]
    except Exception:
        return ""


def cert_card_lines(cert: dict) -> list[str]:
    return [
        "",
        "  *  " + cert["rune_name"],
        "",
        "  Class:   " + cert["title"],
        "  Earned:  " + str(cert["block_time"]) + f"   (block {cert['block_height']})",
        "  Wallet:  " + cert["original_wallet"],
        "  soulbound · non-transferable · regtest (mock)",
        "",
        "  Etched into your wallet. Block time + wallet live on-chain — even",
        "  if it's ever moved, everyone knows YOU earned it. 💜",
    ]


async def etch_class_rune(p: Player, spec: dict) -> None:
    block = 21_000 + len(p.certs)
    cert = await asyncio.to_thread(
        STORE.etch_certificate, p.name, spec["class_id"], spec["rune"], spec["title"], p.wallet, block
    )
    p.certs = await asyncio.to_thread(STORE.list_certificates, p.name)
    old_level = p.level
    res = await asyncio.to_thread(STORE.add_xp, p.name, 100); p.xp, p.level = res["xp"], res["level"]
    p.pending_fx.append("etch")                        # cue the web client to glow/particle the etch
    await animate(p, RUNE_ANIM, "Etching a rune...", GOLD, hold=1.3)
    focus_text(p, "Soulbound Class Rune", cert_card_lines(cert), GOLD)
    if p.level > old_level:
        p.pending_fx.append("levelup")
    push(p, c(GOLD, f"🎓 etched {spec['rune']}  (+100 xp)"))


# --- identity: @fren / nostr / spaces, pairing code, on-chain backup ---------
async def link_identity(p: Player, rest: str) -> None:
    kind, _, val = rest.partition(" ")
    kind, val = kind.lower().strip(), val.strip()
    if not kind:
        focus_text(p, "Link your identity", [
            "",
            "  Tie this character to the fren you are out in the world:",
            "",
            "   link fren  <name>     your @fren handle (get a code to bind it)",
            "   link nostr <npub1…>   your nostr identity",
            "   link space <@name>    your spaces (Bitcoin) name",
            "",
            "  Current:  " + _links_summary(p),
            "  " + (f"This node is on frens.earth ({FRENS_URL})." if frens_aware()
                    else "This node is standalone — links are local until it joins frens.earth."),
        ], AMBER)
        return
    if kind == "nostr":
        if not val.startswith("npub1"):
            push(p, c(RED, "a nostr key looks like 'npub1…', fren")); return
        await asyncio.to_thread(STORE.set_identity, p.name, "nostr", val); p.nostr = val
        push(p, c(GREEN, "✓ nostr linked ") + c(GREY, "(verify at frens.earth)"))
    elif kind in ("space", "spaces"):
        v = val if val.startswith("@") else "@" + val
        await asyncio.to_thread(STORE.set_identity, p.name, "space", v); p.space = v
        push(p, c(GREEN, f"✓ space {v} linked ") + c(GREY, "(verify at frens.earth)"))
    elif kind == "fren":
        v = val.lstrip("@")
        if not v:
            push(p, c(RED, "give me a handle:  link fren pacman")); return
        await asyncio.to_thread(STORE.set_identity, p.name, "fren_tag", v); p.fren_tag = v
        p.frens_code = secrets.token_hex(3).upper()
        bind = ([f"   enter this code at  {FRENS_URL}  :   {p.frens_code}",
                 "   …or paste a code from frens.earth here:   verify <code>"]
                if frens_aware() else
                ["   your node is standalone — the claim is local for now;",
                 "   it confirms automatically once this node joins frens.earth."])
        focus_text(p, "Link your @fren", [
            "", f"  You are now  @{v}  across the arcade. 💜", "",
            "  To PROVE this handle is really yours:", "",
        ] + bind + ["", f"  pairing code:  {p.frens_code or '—'}", ""], MAG)
    else:
        push(p, c(GREY, "link what? try:  link"))


def _links_summary(p: Player) -> str:
    return " · ".join([
        f"@{p.fren_tag}" if p.fren_tag else "no @fren",
        f"nostr {p.nostr[:12]}…" if p.nostr else "no nostr",
        f"space {p.space}" if p.space else "no space",
    ])


async def verify_code(p: Player, code: str) -> None:
    code = code.strip().upper()
    if not code:
        push(p, c(GREY, "usage:  verify <code>")); return
    # Mock: in production this POSTs the code to FRENS_URL to confirm the @fren <-> character binding.
    push(p, c(GREEN, f"✓ verification recorded ({code}) ")
         + c(GREY, "— confirms when this node syncs with frens.earth"))


async def backup_onchain(p: Player) -> None:
    # No per-player Bitcoin clutter: the backup is a signed NOSTR event. Your runes are ALREADY
    # on-chain (etched); this just ties them + your identity to your @fren so a lost device
    # doesn't lose your record. Bitcoin is only touched by an OPTIONAL batched Merkle anchor
    # (one tx for many players), timed to the space inscription cadence — never one tx each.
    payload = json.dumps({"fren": p.fren_tag, "wallet": p.wallet, "nostr": p.nostr, "space": p.space,
                          "runes": [x["rune_name"] for x in p.certs]}, sort_keys=True)
    digest = hashlib.sha256(payload.encode()).hexdigest()
    ev_id = "nevent1" + digest[:24]
    focus_text(p, "Backup your progress", [
        "",
        "  Signed and published as a NOSTR event — no clutter on Bitcoin. (mock)",
        "",
        f"    attestation : {digest[:40]}...",
        f"    nostr event : {ev_id}",
        f"    covers      : @{p.fren_tag or '-'} · {len(p.certs)} rune(s) · wallet {p.wallet[:14]}...",
        "",
        "  Your runes already live on-chain (they're etched). This backup ties",
        "  them to your @fren so a lost device never loses your record.",
        "  Optional: your hash joins a BATCHED Merkle anchor (one tx for many,",
        "  timed with the space inscription cadence) — never one tx per player.",
    ], GOLD)
    push(p, c(GOLD, f"backup published to nostr: {ev_id}"))


async def show_profile(p: Player) -> None:
    focus_text(p, ("@" + p.fren_tag) if p.fren_tag else p.name, [
        "",
        "  Character : " + p.name,
        "  Wallet    : " + (p.wallet or "—"),
        "  @fren     : " + (("@" + p.fren_tag) if p.fren_tag else "unlinked   (link fren <name>)"),
        "  nostr     : " + (p.nostr or "unlinked   (link nostr <npub1…>)"),
        "  space     : " + (p.space or "unlinked   (link space <@name>)"),
        "  Runes     : " + f"{len(p.certs)} soulbound class rune(s)",
        "  Backup    : " + ("run  backup  to anchor on-chain"),
    ], AMBER)


async def show_certs(p: Player) -> None:
    if not p.certs:
        focus_text(p, "Your runes", ["", "  No class runes yet.", "",
                                      "  The Oracle's Alcove (north) is where they're earned. 🎓"], GOLD)
        return
    lines = ["", "  Your soulbound class runes:", ""]
    for cert in p.certs:
        lines.append(f"  * {cert['rune_name']}  -  {cert['title']}")
        lines.append(f"       earned {cert['block_time']} · block {cert['block_height']}")
    lines += ["", "  Non-transferable. Move one and provenance still names you."]
    focus_text(p, "Your runes", lines, GOLD)


# =============================================================================
# Operator console — live stats, knowledge-swarm health, safe reboot/shutdown.
# Reachable three ways: local terminal (stdin), in-MUD `admin <token>`, HTTP rails.
# =============================================================================
def _fmt_dur(secs: float) -> str:
    secs = int(secs)
    h, m, s = secs // 3600, (secs % 3600) // 60, secs % 60
    return (f"{h}h " if h else "") + f"{m:02d}m {s:02d}s"


_swarm_cache = {"at": 0.0, "data": None}


def _probe_swarm() -> dict:
    mock = os.environ.get("PA_SWARM_MOCK")
    if mock:
        try:
            d = json.loads(mock); d["online"] = True; return d
        except Exception:
            if mock.lower() in ("1", "true", "on", "yes"):
                return {"online": True, "peers": 4, "corpora": ["common-knowledge"],
                        "shards_cached": 812, "shards_total": 1024, "manifest_verified": True}
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


def stats_json() -> dict:
    return {
        "uptime_s": int(time.time() - SERVER_START),
        "player_count": len(PLAYERS),
        "world": WORLD,
        "players": [{
            "name": p.name, "fren": p.fren_tag, "world": WORLD, "room": p.room,
            "client": "web" if p.web else "terminal", "module": "FREE PLAY",
            "muted": p.muted, "watched": p.watched,
            "timeout_s": max(0, int(p.timeout_until - time.time())),
            "uptime_s": int(time.time() - p.connected_at),
            "idle_s": int(time.time() - p.idle_since), "admin": p.is_admin,
        } for p in PLAYERS.values()],
        "runes_etched_session": RUNES_ETCHED,
        "store": {"backend": type(STORE).__name__, "location": getattr(STORE, "path", "postgres DB-2")},
        "oracle": ("local-llm:" + GEN_MODEL) if (INFERENCE_BASE_URL and GEN_MODEL) else "scripted",
        "chat_matrix": CHAT_MATRIX,
        "qa": {"flagged": sum(1 for f in _QA_FLAGS if f["status"] == "FLAGGED"),
               "in_review": sum(1 for f in _QA_FLAGS if f["status"] == "IN REVIEW"),
               "corrected": sum(1 for f in _QA_FLAGS if f["status"] == "CORRECTED"),
               "latest": (_QA_FLAGS[-1]["topic"] if _QA_FLAGS else "")},
    }


def stats_report() -> str:
    lines = ["P.O.K.E. MUD — operator stats",
             f"  world       : {WORLD}",
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


async def op_broadcast(msg: str) -> str:
    for w, pl in list(PLAYERS.items()):
        push(pl, c(BOLD + MAG, f"[operator] {msg}"))
        try:
            await show(pl)
        except Exception:
            pass
    return f"broadcast to {len(PLAYERS)} player(s)"


async def op_kick(name: str) -> str:
    for w, pl in list(PLAYERS.items()):
        if pl.name.lower() == name.lower() or (pl.fren_tag or "").lower() == name.lstrip("@").lower():
            try:
                await pl.send(c(RED, "\r\nAn operator disconnected you. Your progress is saved. 💜\r\n"))
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
    await op_broadcast(f"P.O.K.E. is {verb} now ({reason}). Progress saved — back soon, fren. 💜")
    await asyncio.sleep(0.3)
    SHUTDOWN.set()
    return verb


def set_chat_matrix(on: bool) -> str:
    global CHAT_MATRIX
    CHAT_MATRIX = on
    return f"matrix chat {'ON — say now mirrors to the Matrix verse' if on else 'off — local rooms only'}"


async def forward_chat_to_matrix(room: str, sender: str, body: str) -> None:
    if not CHAT_MATRIX:
        return

    def _post():
        try:
            data = json.dumps({"room": room, "sender": sender, "body": body}).encode()
            req = urllib.request.Request(MATRIX_BRIDGE_URL.rstrip("/") + "/message", data=data,
                                         headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=2)
        except Exception:
            pass

    try:
        await asyncio.to_thread(_post)
    except Exception:
        pass


CONSOLE_HELP = (
    "P.O.K.E. operator console:\n"
    "  stats · who · nodes · broadcast <m> · kick <n> · chat on|off · reboot · shutdown · help"
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


# --- HTTP control rails (serves the web-admin page + JSON API) ----------------
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer  # noqa: E402

_HERE = os.path.dirname(os.path.abspath(__file__))
_ADMIN_HTML = os.path.join(_HERE, "admin.html")
_WEBCLIENT_HTML = os.path.join(_HERE, "webclient.html")


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

    def _serve_html(self, path_on_disk: str) -> None:
        try:
            with open(path_on_disk, "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except FileNotFoundError:
            self._reply(404, {"error": os.path.basename(path_on_disk) + " not found"})

    def _run(self, coro, timeout: float = 4.0):
        return asyncio.run_coroutine_threadsafe(coro, LOOP).result(timeout=timeout)

    def do_GET(self) -> None:
        path = self.path.split("?")[0].rstrip("/")
        if path in ("", "/admin", "/index.html"):      # the operator dashboard (loads without a token)
            return self._serve_html(_ADMIN_HTML)
        if path in ("/play", "/mud", "/game"):         # the browser game client (public; you log in by name)
            return self._serve_html(_WEBCLIENT_HTML)
        if path == "/config":                          # public: how the browser client reaches the game
            return self._reply(200, {"ws_port": MUD_WS_PORT, "local_site": LOCAL_SITE_URL,
                                     "node": os.environ.get("PA_NODE_NAME", "a POKE node")})
        if not self._authed():
            return self._reply(401, {"error": "unauthorized"})
        if path in ("/stats", "/health"):
            self._reply(200, stats_json())
        elif path == "/nodes":
            self._reply(200, self._run(get_swarm_status(True)))
        elif path == "/system":
            self._reply(200, system_metrics())
        elif path == "/relays":
            rl = _load_relays()
            self._reply(200, {"relays": rl, "count": len(rl)})
        elif path == "/torrent":
            self._reply(200, torrent_status())
        elif path == "/system/history":
            win = 60
            if "?" in self.path:
                for kv in self.path.split("?", 1)[1].split("&"):
                    if kv.startswith("window="):
                        try:
                            win = int(kv.split("=")[1])
                        except Exception:
                            pass
            self._reply(200, system_history(win))
        elif path == "/modules":
            self._reply(200, {"modules": _MODULES})
        elif path == "/sitelink":
            self._reply(200, _SITELINK)
        elif path.startswith("/players/") and path.endswith("/history"):
            _, pl = _find_player(path[len("/players/"):-len("/history")])
            self._reply(200, {"history": [_ANSI.sub("", x) for x in (pl.log if pl else [])]})
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
        elif path == "/relays":
            self._reply(200, {"ok": True, "result": relays_add(
                str(data.get("name", "")).strip(), str(data.get("ref", "")).strip(),
                data.get("kind", "verse"), data.get("pubkey"))})
        elif path == "/relays/remove":
            self._reply(200, {"ok": True, "result": relays_remove(str(data.get("name", "")).strip())})
        elif path == "/relays/toggle":
            self._reply(200, {"ok": True, "result": relays_toggle(
                str(data.get("name", "")).strip(), bool(data.get("enabled")))})
        elif path == "/torrent":
            self._reply(200, {"ok": True, "result": torrent_control(
                str(data.get("action", "status")), data.get("corpus_id"))})
        elif path == "/mute":
            self._reply(200, {"ok": True, "result": self._run(op_mute(
                str(data.get("player", "")), bool(data.get("on", True)), str(data.get("reason", ""))))})
        elif path == "/timeout":
            self._reply(200, {"ok": True, "result": self._run(op_timeout(
                str(data.get("player", "")), int(data.get("minutes", 5) or 5), str(data.get("reason", ""))))})
        elif path == "/watch":
            self._reply(200, {"ok": True, "result": self._run(op_watch(
                str(data.get("player", "")), bool(data.get("on", True))))})
        elif path == "/knowledge/flag":
            _QA_FLAGS.append({"topic": data.get("topic", ""), "quote": data.get("quote", ""),
                              "by": data.get("by", ""), "status": "FLAGGED"})
            self._reply(200, {"ok": True, "result": "flagged"})
        elif path == "/modules":
            self._reply(200, {"ok": True, "result": "module save is stubbed — the Architect wires this next"})
        elif path == "/sitelink":
            _SITELINK["mode"] = "testing" if data.get("mode") == "testing" else "synced"
            if data.get("url"):
                _SITELINK["url"] = str(data.get("url"))
            self._reply(200, {"ok": True, "result": _SITELINK["mode"]})
        else:
            self._reply(404, {"error": "not found"})

    def log_message(self, *args) -> None:
        pass


def _start_admin_http() -> "ThreadingHTTPServer | None":
    try:
        srv = ThreadingHTTPServer((ADMIN_HTTP_HOST, ADMIN_HTTP_PORT), _AdminHTTP)
    except OSError as e:
        print(f"! web-admin rails not started on {ADMIN_HTTP_HOST}:{ADMIN_HTTP_PORT} ({e})")
        return None
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


async def admin_command(p: Player, rest: str) -> None:
    sub, _, arg = rest.partition(" ")
    sub, arg = sub.lower().strip(), arg.strip()
    if not p.is_admin:
        if sub and secrets.compare_digest(sub, ADMIN_TOKEN):
            p.is_admin = True
            push(p, c(GREEN, "operator mode ON ") + c(GREY, "— admin: stats·nodes·broadcast·kick·chat·reboot·shutdown"))
        else:
            push(p, c(RED, "operator only — authenticate:  admin <token>  ") + c(GREY, "(token prints in the server console)"))
        return
    if sub in ("", "stats", "status"):
        focus_text(p, "Operator · stats", ["  " + l for l in stats_report().split("\n")], CYAN)
    elif sub in ("nodes", "swarm"):
        focus_text(p, "Operator · knowledge swarm",
                   ["  " + l for l in nodes_report(await get_swarm_status(force=True)).split("\n")], CYAN)
    elif sub in ("broadcast", "bcast"):
        push(p, c(GREY, (await op_broadcast(arg)) if arg else "usage: admin broadcast <message>"))
    elif sub == "kick":
        push(p, c(GREY, (await op_kick(arg)) if arg else "usage: admin kick <name>"))
    elif sub == "chat":
        push(p, c(GREY, set_chat_matrix(arg.lower() in ("on", "1", "true", "yes"))))
    elif sub == "reboot":
        push(p, c(RED, "rebooting the node…")); await op_shutdown("in-MUD operator reboot", reboot=True)
    elif sub == "shutdown":
        push(p, c(RED, "shutting the node down…")); await op_shutdown("in-MUD operator shutdown", reboot=False)
    else:
        push(p, c(GREY, "admin: stats | nodes | broadcast <m> | kick <n> | chat on|off | reboot | shutdown"))


# =============================================================================
# The boss — an animated encounter with a question gate and a reward.
# =============================================================================
WRAITH = {
    "id": "wraith",
    "name": "The Double-Spend Wraith",
    "class": {"class_id": "consensus", "rune": "PACS•CONSENSUS", "title": "Bitcoin Consensus 101"},
    "question": ("\"I am one coin, spent twice. I split the ledger and feast on the confusion. Name the "
                 "mechanism that forces the whole network to agree on ONE history — and I unravel.\""),
    "keys": ("proof of work", "proof-of-work", "pow", "mining", "miners", "longest chain",
             "heaviest chain", "most work", "confirmation", "consensus", "nakamoto", "hash"),
    "xp": 150,
}
# The Wraith flickers position/face across frames so it visibly MOVES during the encounter.
WRAITH_ANIM = [
    ["", "  it is in two places at once...", "", "        .-~~~-.", "      (  x   x  )", "       \\   ^   /", "        '-...-'", ""],
    ["", "  ...here, and not-here...", "", "    .-~~~-.", "  (  X   X  )", "   \\   >   /", "    '-...-'", ""],
    ["", "  \"which history is TRUE?\"", "", "         .-~~~-.", "       (  @   @  )", "        \\   O   /", "         '-...-'", ""],
]
WRAITH_DEFEAT = [
    ["", "  the forks collapse toward one...", "", "        .-~~~-.", "      (  x   x  )", "       \\   _   /", "        '-...-'", ""],
    ["", "  ...one chain...", "", "         .-~-.", "       (  -   -  )", "        \\  _  /", "         '-.-'", ""],
    ["", "  the Wraith unravels.", "", "           \\  |  /", "         ==  ONE  ==", "           /  |  \\", "", ""],
]


async def boss_open(p: Player) -> None:
    p.boss_pending = WRAITH["id"]
    await animate(p, WRAITH_ANIM, WRAITH["name"], RED, hold=1.3)
    focus_text(p, WRAITH["name"], ["", "  " + WRAITH["name"] + " rounds on you.", ""]
               + ["  " + l for l in _wrap(WRAITH["question"], BOARD_W - 6)]
               + ["", "  (answer with:  answer <your words>)"], RED)


async def boss_judge(p: Player, ans: str) -> None:
    if any(k in ans.lower() for k in WRAITH["keys"]):
        p.boss_pending = None
        # Anti-farming: reward (XP + rune + energy) is granted ONCE — the first time you learn it.
        already = await asyncio.to_thread(STORE.has_certificate, p.name, WRAITH["class"]["class_id"])
        p.pending_fx.append("victory")                 # cue the web client's boss-defeat effect
        await animate(p, WRAITH_DEFEAT, WRAITH["name"] + " - defeated", GOLD, hold=1.3)
        if already:
            focus_text(p, "Victory", ["", "  The Wraith yields — but you've already mastered this truth.", "",
                                      "  No XP for a lesson you already own, fren. Come back when there's a",
                                      "  NEW boss with something new to teach. (Harder rematch questions and",
                                      "  boss riddles are on the way — see docs/ROADMAP.md.)"], GOLD)
            push(p, c(GREY, "already mastered — no farming"))
            return
        old_level = p.level
        res = await asyncio.to_thread(STORE.add_xp, p.name, WRAITH["xp"]); p.xp, p.level = res["xp"], res["level"]
        p.energy = await asyncio.to_thread(STORE.adjust_energy, p.name, 20)
        if p.level > old_level:
            p.pending_fx.append("levelup")
        push(p, c(GOLD, f"the Wraith unravels  (+{WRAITH['xp']} xp)"))
        await etch_class_rune(p, WRAITH["class"])
    else:
        p.energy = await asyncio.to_thread(STORE.adjust_energy, p.name, -15)
        p.boss_pending = WRAITH["id"]
        focus_text(p, WRAITH["name"], ["", "  The Wraith laughs and splits again.  (-15 ⚡)", "",
                                       "  Think: what does a miner burn to extend the chain, making a",
                                       "  rewrite absurdly expensive?   answer <text>"], RED)


# =============================================================================
# Attributes & examine — a player's stats, and viewing another fren's.
# =============================================================================
async def show_attributes(p: Player) -> None:
    into = p.xp % 100
    bar = "█" * (into // 10) + "░" * (10 - into // 10)
    focus_text(p, "Your attributes", [
        "",
        f"  Level     : {p.level}",
        f"  Knowledge : {p.xp} xp    [{bar}]   {100 - into} to level {p.level + 1}",
        f"  Runes     : {len(p.certs)} soulbound",
        f"  Energy    : {p.energy}/100",
        f"  @fren     : {('@' + p.fren_tag) if p.fren_tag else 'unlinked  (link fren <name>)'}",
        "",
        "  Earn xp from the Oracle and by defeating bosses.",
        "  The dungeon is  down  from the entrance.  See a fren:  examine <name>",
    ], CYAN)


async def examine(p: Player, name: str) -> None:
    name = name.strip()
    if not name:
        push(p, c(GREY, "examine whom?  examine <name>")); return
    a = await asyncio.to_thread(STORE.public_attributes, name)
    if not a:
        push(p, c(GREY, f"no fren called '{name}' is known here")); return
    who = ("@" + a["fren_tag"]) if a["fren_tag"] else a["name"]
    online = any(pl.name == a["name"] for pl in PLAYERS.values())
    focus_text(p, who, [
        "",
        f"  {who}   {'· here now' if online else '· not currently online'}",
        f"  Level     : {a['level']}",
        f"  Knowledge : {a['xp']} xp",
        f"  Runes     : {a['runes']} soulbound",
        f"  Energy    : {a['energy']}/100",
        f"  Last seen : {a['room']}",
    ], AMBER)


# =============================================================================
# Flexible input — a fast path (no LLM, zero lag) + an LLM/heuristic fuzzy path.
# The local model only runs on free text; exact commands never touch it. All the
# player's turns are stored in DB-2 so the world remembers them cheaply.
# =============================================================================
GREETINGS = {"sup", "hi", "hey", "hello", "yo", "greetings", "howdy", "hiya", "wassup",
             "whatsup", "what's up", "whats up", "ahoy", "oi"}


def _chat(messages: list[dict], max_tokens: int) -> str:
    try:
        body = json.dumps({"model": GEN_MODEL, "messages": messages,
                           "max_tokens": max_tokens, "temperature": 0.7}).encode()
        req = urllib.request.Request(INFERENCE_BASE_URL.rstrip("/") + "/chat/completions",
                                     data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=8) as r:
            return json.loads(r.read())["choices"][0]["message"]["content"]
    except Exception:
        return ""


def _llm_oracle(text: str, mem: list[dict]) -> str:
    msgs = [{"role": "system", "content":
             "You are the Oracle at Pac's Arcade — a Socratic bitcoin/nostr educator in a MUD. Say 'fren', "
             "never 'friend'. Reply in 1-3 warm sentences and end with a probing question. Never lecture."}]
    for m in mem:
        msgs.append({"role": "assistant" if m["role"] == "game" else "user", "content": m["text"]})
    msgs.append({"role": "user", "content": text})
    return _chat(msgs, 140)


async def converse_oracle(p: Player, text: str) -> None:
    """Free-form chat with the Oracle. Tiny context (recent memory only), stored in DB-2."""
    await asyncio.to_thread(STORE.add_memory, p.name, "player", text)
    focus_text(p, "The Oracle", _oracle_panel(["…the Oracle considers…"]), MAG)
    await show(p)
    reply = ""
    if INFERENCE_BASE_URL and GEN_MODEL:
        mem = await asyncio.to_thread(STORE.recent_memory, p.name, 6)
        reply = await asyncio.get_event_loop().run_in_executor(None, _llm_oracle, text, mem)
    if not reply:
        reply = ("I trade in questions, not chit-chat, fren — but I'm listening. Ask me something real about "
                 "bitcoin or nostr, or say 'talk oracle' to begin the trial. What's on your mind?")
    await asyncio.to_thread(STORE.add_memory, p.name, "game", reply)
    focus_text(p, "The Oracle", _oracle_panel(_wrap('"' + reply.strip() + '"', BOARD_W - 6)), MAG)


def _llm_intent(room_title: str, exits: list, npcs: list, line: str) -> dict | None:
    sysmsg = ("Translate the player's text into ONE game action in a MUD. Reply ONLY compact JSON, no prose. "
              "Options: {\"action\":\"move\",\"dir\":\"north|south|east|west|up|down\"} | {\"action\":\"talk\"} | "
              "{\"action\":\"look\"} | {\"action\":\"pull\"} | {\"action\":\"challenge\"} | {\"action\":\"backup\"} | "
              "{\"action\":\"profile\"} | {\"action\":\"certs\"} | {\"action\":\"none\",\"reply\":\"<short in-character line>\"}. "
              f"Room: {room_title}. Exits: {exits}. NPCs here: {npcs}.")
    out = _chat([{"role": "system", "content": sysmsg}, {"role": "user", "content": line}], 60)
    try:
        return json.loads(out[out.find("{"):out.rfind("}") + 1])
    except Exception:
        return None


async def apply_intent(p: Player, act: dict) -> bool:
    a = (act.get("action") or "").lower()
    npcs = ROOMS[p.room]["npcs"]
    if a == "move" and act.get("dir"):
        await move(p, act["dir"]); return True
    if a == "talk":
        if "oracle" in npcs:
            await oracle_open(p); return True
        if "wraith" in npcs:
            await boss_open(p); return True
    if a == "look":
        focus_room(p); return True
    if a == "pull":
        await pull(p, "lever"); return True
    if a == "challenge" and "wraith" in npcs:
        await boss_open(p); return True
    if a == "backup":
        await backup_onchain(p); return True
    if a == "profile":
        await show_profile(p); return True
    if a == "certs":
        await show_certs(p); return True
    if a == "none" and act.get("reply"):
        push(p, c(MAG, str(act["reply"])[:200])); return True
    return False


async def interpret(p: Player, line: str) -> None:
    """The fuzzy path: only reached when no exact command matched. Heuristics first (instant),
    NPC conversation second, the local LLM last — so lag only ever happens on true free text."""
    low = line.lower().strip()
    npcs = ROOMS[p.room]["npcs"]
    await asyncio.to_thread(STORE.add_memory, p.name, "player", line)
    if any(low == g or low.startswith(g + " ") for g in GREETINGS):
        if "oracle" in npcs:
            await oracle_open(p); return
        if "wraith" in npcs:
            await boss_open(p); return
        push(p, c(GREY, "you say it to the empty room; the cabinets blink back")); return
    for d in DIRS:
        if d in low.split():
            await move(p, d); return
    if low in ("where am i", "look around", "explore", "wat", "what"):
        focus_room(p); return
    if "oracle" in npcs:                       # in the Alcove, free text IS a question to the Oracle
        await converse_oracle(p, line); return
    if INFERENCE_BASE_URL and GEN_MODEL:       # elsewhere, let the model map intent (only cost when needed)
        room = ROOMS[p.room]
        act = await asyncio.get_event_loop().run_in_executor(
            None, _llm_intent, room["title"], list(room["exits"]), npcs, line)
        if act and await apply_intent(p, act):
            return
    push(p, c(GREY, f"hmm — not sure what '{line}' does here. Try  help, or talk to someone."))


# --- system / relays / torrent metrics for the web console rails -------------
def _linux_metrics() -> dict:
    with open("/proc/meminfo") as f:
        mi = {ln.split(":")[0]: int(ln.split()[1]) for ln in f}
    total_kb = mi.get("MemTotal", 0)
    avail_kb = mi.get("MemAvailable", mi.get("MemFree", 0))
    total_mb, used_mb = total_kb // 1024, (total_kb - avail_kb) // 1024

    def snap():
        agg, cores = None, []
        with open("/proc/stat") as f:
            for ln in f:
                if not ln.startswith("cpu"):
                    break
                parts = ln.split(); vals = list(map(int, parts[1:]))
                idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
                pair = (idle, sum(vals))
                if parts[0] == "cpu":
                    agg = pair
                else:
                    cores.append(pair)
        return agg, cores

    a1, c1 = snap(); time.sleep(0.1); a2, c2 = snap()

    def pct(x, y):
        di, dt = y[0] - x[0], y[1] - x[1]
        return round((1 - di / dt) * 100, 1) if dt > 0 else 0.0

    per = [pct(c1[i], c2[i]) for i in range(min(len(c1), len(c2)))]
    return {"available": True, "cpu_percent": pct(a1, a2), "cores": len(per) or (os.cpu_count() or 1),
            "per_core": per, "mem_used_mb": used_mb, "mem_total_mb": total_mb,
            "mem_percent": round(used_mb / total_mb * 100, 1) if total_mb else 0.0,
            "uptime_s": int(time.time() - SERVER_START)}


def _win_metrics() -> dict:
    import ctypes
    from ctypes import wintypes
    k = ctypes.windll.kernel32

    class MEMSTAT(ctypes.Structure):
        _fields_ = [("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
    ms = MEMSTAT(); ms.dwLength = ctypes.sizeof(MEMSTAT); k.GlobalMemoryStatusEx(ctypes.byref(ms))
    total_mb = ms.ullTotalPhys // (1024 * 1024)
    used_mb = (ms.ullTotalPhys - ms.ullAvailPhys) // (1024 * 1024)

    def times():
        idle, kern, usr = wintypes.FILETIME(), wintypes.FILETIME(), wintypes.FILETIME()
        k.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kern), ctypes.byref(usr))
        q = lambda ft: (ft.dwHighDateTime << 32) | ft.dwLowDateTime
        return q(idle), q(kern) + q(usr)

    i1, t1 = times(); time.sleep(0.1); i2, t2 = times()
    dt, di = t2 - t1, i2 - i1
    cpu = round((1 - di / dt) * 100, 1) if dt > 0 else 0.0
    return {"available": True, "cpu_percent": cpu, "cores": os.cpu_count() or 1, "per_core": [],
            "mem_used_mb": used_mb, "mem_total_mb": total_mb, "mem_percent": ms.dwMemoryLoad,
            "uptime_s": int(time.time() - SERVER_START)}


def system_metrics() -> dict:
    try:
        import psutil
        vm = psutil.virtual_memory()
        per = psutil.cpu_percent(percpu=True)
        return {"available": True, "cpu_percent": round(sum(per) / len(per), 1) if per else 0.0,
                "cores": psutil.cpu_count() or len(per), "per_core": [round(x, 1) for x in per],
                "mem_used_mb": (vm.total - vm.available) // (1024 * 1024),
                "mem_total_mb": vm.total // (1024 * 1024), "mem_percent": vm.percent,
                "uptime_s": int(time.time() - SERVER_START)}
    except Exception:
        pass
    try:
        if sys.platform.startswith("linux"):
            return _linux_metrics()
        if sys.platform == "win32":
            return _win_metrics()
    except Exception as e:
        return {"available": False, "reason": f"metrics error ({e.__class__.__name__})"}
    return {"available": False, "reason": "no metrics backend (pip install psutil)"}


RELAYS_FILE = os.environ.get("PA_RELAYS_FILE", os.path.join("data", "relays.json"))


def _load_relays() -> list:
    try:
        with open(RELAYS_FILE) as f:
            return json.load(f).get("relays", [])
    except Exception:
        return []


def _save_relays(relays: list) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(RELAYS_FILE)), exist_ok=True)
    with open(RELAYS_FILE, "w") as f:
        json.dump({"relays": relays}, f, indent=2)


def relays_add(name: str, ref: str, kind: str = "verse", pubkey=None) -> str:
    if not name or not ref:
        return "need a name and a ref (magnet/infohash/npub)"
    relays = [r for r in _load_relays() if r.get("name") != name]
    relays.append({"name": name, "ref": ref, "pubkey": pubkey, "kind": kind, "enabled": True,
                   "added_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
    _save_relays(relays)
    return f"subscribed to verse '{name}'"


def relays_remove(name: str) -> str:
    _save_relays([r for r in _load_relays() if r.get("name") != name])
    return f"unsubscribed from '{name}'"


def relays_toggle(name: str, enabled: bool) -> str:
    relays = _load_relays()
    for r in relays:
        if r.get("name") == name:
            r["enabled"] = bool(enabled)
    _save_relays(relays)
    return f"'{name}' {'enabled' if enabled else 'disabled'}"


def torrent_status() -> dict:
    url = os.environ.get("PA_CORPUS_URL", "")
    if url:
        try:
            with urllib.request.urlopen(url.rstrip("/") + "/torrent/status", timeout=1.5) as r:
                return json.loads(r.read())
        except Exception:
            pass
    if os.environ.get("PA_SWARM_MOCK"):
        return {"global": {"up_kbps": 42.0, "down_kbps": 128.0, "port": 6881, "dht": True, "num_swarms": 2},
                "swarms": [
                    {"corpus_id": "pacs-common", "peers": 6, "seeds": 3, "progress": 0.82,
                     "cached": 840, "total": 1024, "verified": True, "paused": False},
                    {"corpus_id": "nostr-longform", "peers": 2, "seeds": 1, "progress": 0.31,
                     "cached": 120, "total": 384, "verified": True, "paused": False}]}
    enabled = [r for r in _load_relays() if r.get("enabled")]
    return {"global": {"up_kbps": 0.0, "down_kbps": 0.0, "port": int(os.environ.get("PA_TORRENT_PORT", "6881")),
                       "dht": True, "num_swarms": len(enabled)}, "swarms": []}


def torrent_control(action: str, corpus_id=None) -> str:
    url = os.environ.get("PA_CORPUS_URL", "")
    if url:
        try:
            data = json.dumps({"action": action, "corpus_id": corpus_id}).encode()
            req = urllib.request.Request(url.rstrip("/") + "/torrent/control", data=data,
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=2) as r:
                return str(json.loads(r.read()).get("result", action))
        except Exception:
            pass
    return f"{action} {corpus_id or 'all'} (queued; corpus service offline in dev)"


# --- console: telemetry history + moderation + course/QA stubs ---------------
_MHIST = {"cpu": deque(maxlen=90), "mem": deque(maxlen=90), "net": deque(maxlen=90)}
_net_prev = {"t": 0.0, "total": 0}


def _net_total_bytes():
    try:
        import psutil
        io = psutil.net_io_counters()
        return io.bytes_sent + io.bytes_recv
    except Exception:
        pass
    if sys.platform.startswith("linux"):
        try:
            tot = 0
            with open("/proc/net/dev") as f:
                for ln in f:
                    if ":" in ln:
                        pr = ln.split(":")[1].split()
                        tot += int(pr[0]) + int(pr[8])
            return tot
        except Exception:
            pass
    return None


def _net_kbps() -> float:
    tot = _net_total_bytes()
    if tot is None:
        return 0.0
    now = time.time()
    prev_t, prev = _net_prev["t"], _net_prev["total"]
    _net_prev.update(t=now, total=tot)
    if not prev_t:
        return 0.0
    return round(max(0.0, (tot - prev) / 1024 / max(0.001, now - prev_t)), 1)


async def _metrics_sampler() -> None:
    """Sample cpu/mem/net once a second into a ring for the console's micro-histograms."""
    while not SHUTDOWN.is_set():
        try:
            m = await asyncio.to_thread(system_metrics)
            ok = m.get("available")
            _MHIST["cpu"].append(m.get("cpu_percent", 0.0) if ok else 0.0)
            _MHIST["mem"].append(m.get("mem_percent", 0.0) if ok else 0.0)
            _MHIST["net"].append(await asyncio.to_thread(_net_kbps))
        except Exception:
            pass
        try:
            await asyncio.wait_for(SHUTDOWN.wait(), timeout=1.0)
        except asyncio.TimeoutError:
            pass


def system_history(window: int = 60) -> dict:
    n = max(1, min(90, window))
    return {k: [round(x, 1) for x in list(v)[-n:]] for k, v in _MHIST.items()}


def _find_player(name: str):
    key = name.lstrip("@").lower()
    for w, pl in list(PLAYERS.items()):
        if pl.name.lower() == key or (pl.fren_tag or "").lower() == key:
            return w, pl
    return None, None


async def op_mute(name: str, on: bool, reason: str = "") -> str:
    w, pl = _find_player(name)
    if not pl:
        return f"no player '{name}'"
    pl.muted = bool(on)
    if on:
        push(pl, c(CYAN, "MUTED — your says stay local until an operator unmutes you. The Oracle still answers.")
             + (c(GREY, f"  ({reason})") if reason else ""))
    else:
        push(pl, c(GREEN, "unmuted — say away, fren"))
    try:
        await show(pl)
    except Exception:
        pass
    return f"{pl.name} {'muted' if on else 'unmuted'}"


async def op_timeout(name: str, minutes: int, reason: str = "") -> str:
    w, pl = _find_player(name)
    if not pl:
        return f"no player '{name}'"
    pl.timeout_until = time.time() + max(1, int(minutes)) * 60
    push(pl, c(GOLD, f"TIMEOUT — {int(minutes)}:00. Your seat and progress are safe; chat re-opens at zero.")
         + (c(GREY, f"  ({reason})") if reason else ""))
    try:
        await show(pl)
    except Exception:
        pass
    return f"{pl.name} timed out {int(minutes)}m"


async def op_watch(name: str, on: bool) -> str:
    w, pl = _find_player(name)
    if not pl:
        return f"no player '{name}'"
    pl.watched = bool(on)
    return f"{'watching' if on else 'unwatched'} {pl.name}"


# Course modules + knowledge QA are the Architect's/Warden's — stubbed until wired (see ROADMAP).
_QA_FLAGS: list = []
_MODULES = [
    {"lvl": 1, "code": "BTC101", "name": "Bitcoin Self-Custody", "path": "BITCOIN › CUSTODY",
     "prereq": "", "rune": "PACS•ARCADE•BTC101", "access": "OPEN"},
    {"lvl": 2, "code": "CONSENSUS", "name": "Bitcoin Consensus", "path": "BITCOIN › CONSENSUS",
     "prereq": "BTC101", "rune": "PACS•ARCADE•CONSENSUS", "access": "AFTER BTC101"},
]
_SITELINK = {"mode": "testing" if LOCAL_SITE_URL else "synced",
             "url": LOCAL_SITE_URL or "https://pacsarcade.org"}


# --- command dispatch --------------------------------------------------------
DIRS = {"north", "south", "east", "west", "up", "down"}
DIR_ALIAS = {"n": "north", "s": "south", "e": "east", "w": "west", "u": "up", "d": "down"}


async def broadcast_room(room: str, log_line: str, exclude: "Player | None" = None) -> None:
    for w, pl in list(PLAYERS.items()):
        if pl.room == room and pl is not exclude:
            push(pl, log_line)
            try:
                await show(pl)
            except Exception:
                pass


async def dispatch(p: Player, line: str) -> bool:
    verb, _, rest = line.strip().partition(" ")
    verb = verb.lower()
    rest = rest.strip()
    p.idle_since = time.time()

    # Operator timeout: benched except for quit/look/help.
    if p.timeout_until > time.time() and verb not in ("quit", "exit", "q", "look", "l", "help", "?"):
        push(p, c(GOLD, f"you're benched — {int(p.timeout_until - time.time())}s left. seat + progress safe."))
        return True

    # While a question is pending, most input IS the answer — so "proof of work" is judged even
    # if it starts with a command word like 'i' (inventory). A few meta verbs still work mid-question.
    if (p.boss_pending or p.oracle_pending) and verb not in (
            "quit", "exit", "q", "help", "?", "look", "l", "answer", "admin"):
        if p.boss_pending:
            await boss_judge(p, line.strip())
        else:
            await oracle_judge(p, line.strip())
        return True

    if verb in ("quit", "exit", "q"):
        gained = p.xp - p.session_start_xp
        new_runes = len(p.certs) - p.session_start_runes
        lines = [
            f"Goodnight, {display_name(p)}.",
            "This session: +" + str(gained) + " xp" + (f", +{new_runes} rune(s)" if new_runes > 0 else "") + ".",
            f"You're Level {p.level} · {p.xp} xp · {len(p.certs)} rune(s).",
            "Come back and we'll pick up right where you left off. 💜",
        ]
        if p.web:
            await p.send(json.dumps({"t": "bye", "lines": lines,
                                     "summary": {"xp": p.xp, "level": p.level, "runes": len(p.certs), "gained": gained}}))
        else:
            await p.send(CLEAR + c(MAG, "\r\n  " + "\r\n  ".join(lines) + "\r\n"))
        return False
    if verb in ("help", "?", "commands"):
        focus_text(p, "How to play", HELP_LINES, GREY)
    elif verb in ("look", "l"):
        focus_room(p)
    elif verb in ("go", "move", "walk"):
        await move(p, rest)
    elif verb in DIRS or verb in DIR_ALIAS:
        await move(p, DIR_ALIAS.get(verb, verb))
    elif verb == "talk":
        target = rest.lower() or (ROOMS[p.room]["npcs"][0] if ROOMS[p.room]["npcs"] else "")
        if target == "oracle" and "oracle" in ROOMS[p.room]["npcs"]:
            await oracle_open(p)
        elif target in ("wraith", "boss") and "wraith" in ROOMS[p.room]["npcs"]:
            await boss_open(p)
        else:
            push(p, c(GREY, "there's no one by that name here"))
    elif verb == "answer":
        if p.boss_pending:
            await boss_judge(p, rest)
        elif p.oracle_pending:
            await oracle_judge(p, rest)
        else:
            push(p, c(GREY, "nothing has asked you a question yet — try  talk oracle  or  challenge"))
    elif verb == "ask":
        tgt, _, q = rest.partition(" ")
        if tgt.lower() == "oracle" and "oracle" in ROOMS[p.room]["npcs"]:
            await converse_oracle(p, q.strip() or "teach me something about bitcoin")
        elif "oracle" not in ROOMS[p.room]["npcs"]:
            push(p, c(GREY, "the Oracle is in its Alcove (north from the entrance)"))
        else:
            push(p, c(GREY, "ask whom? try:  ask oracle <your question>"))
    elif verb == "pull":
        await pull(p, rest)
    elif verb == "link":
        await link_identity(p, rest)
    elif verb == "verify":
        await verify_code(p, rest)
    elif verb == "backup":
        await backup_onchain(p)
    elif verb in ("challenge", "fight", "battle"):
        if "wraith" in ROOMS[p.room]["npcs"]:
            await boss_open(p)
        else:
            push(p, c(GREY, "nothing to challenge here — the dungeon is  down  from the entrance"))
    elif verb in ("stats", "attributes", "attr", "level"):
        await show_attributes(p)
    elif verb in ("examine", "inspect", "x"):
        await examine(p, rest)
    elif verb in ("profile", "whoami", "me"):
        await show_profile(p)
    elif verb == "admin":
        await admin_command(p, rest)
    elif verb == "say":
        if rest:
            who = f"@{p.fren_tag}" if p.fren_tag else p.name
            if p.muted:                                   # muted: your says stay local
                push(p, c(GREEN, "you say: ") + c(BOLD, rest) + c(GREY, "  (muted — local only)"))
            else:
                push(p, c(GREEN, "you say: ") + c(BOLD, rest) + (c(GREY, "  (→ matrix)") if CHAT_MATRIX else ""))
                await broadcast_room(p.room, c(CYAN, f"{who} says: ") + c(BOLD, rest), exclude=p)
                if CHAT_MATRIX:
                    asyncio.create_task(forward_chat_to_matrix(p.room, who, rest))
        else:
            push(p, c(GREY, "say what?"))
    elif verb in ("certs", "runes", "certificates"):
        await show_certs(p)
    elif verb in ("inventory", "inv", "i"):
        focus_text(p, "Inventory", ["", "  You carry:", ""] +
                   (["   · " + it for it in p.inventory] if p.inventory else ["   nothing but curiosity"]), GREEN)
    elif verb == "who":
        push(p, c(GREEN, f"online ({len(PLAYERS)}): ") + ", ".join((f"@{pl.fren_tag}" if pl.fren_tag else pl.name) for pl in PLAYERS.values()))
    elif p.boss_pending:
        await boss_judge(p, line.strip())
    elif p.oracle_pending:
        await oracle_judge(p, line.strip())
    else:
        await interpret(p, line)          # the flexible path — heuristics, NPC chat, then the LLM
    return True


async def move(p: Player, direction: str) -> None:
    direction = DIR_ALIAS.get(direction.lower(), direction.lower())
    exits = ROOMS[p.room]["exits"]
    if direction in exits:
        who = f"@{p.fren_tag}" if p.fren_tag else p.name
        await broadcast_room(p.room, c(GREY, f"{who} heads {direction}."), exclude=p)
        p.room = exits[direction]
        await asyncio.to_thread(STORE.save_player, p.name, p.room, p.inventory)
        await broadcast_room(p.room, c(GREY, f"{who} arrives."), exclude=p)
        focus_room(p)
    else:
        push(p, c(GREY, "you can't go that way, fren"))


async def pull(p: Player, thing: str) -> None:
    if "lever" in thing.lower() and p.room == "vault":
        state = not await asyncio.to_thread(STORE.get_feature, "vault", "lever", False)
        await asyncio.to_thread(STORE.set_feature, "vault", "lever", state)
        if state:
            push(p, c(GOLD, "you heave the lever — the chest clicks open. Inside: a SCROLL."))
            if "the scroll (keep it secret)" not in p.inventory:
                p.inventory.append("the scroll (keep it secret)")
                await asyncio.to_thread(STORE.save_player, p.name, p.room, p.inventory)
        else:
            push(p, c(GREY, "you return the lever; the chest re-seals with a sigh"))
        focus_room(p)
    else:
        push(p, c(GREY, "there's nothing like that to pull here"))


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


async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, web: bool = False) -> None:
    p = Player(writer)
    p.web = web
    PLAYERS[writer] = p
    try:
        if web:
            # The browser renders its own (magical) login; just hand it the node info + a name prompt.
            await p.send(json.dumps({"t": "hello", "node": os.environ.get("PA_NODE_NAME", "a POKE node"),
                                     "site": LOCAL_SITE_URL,
                                     "prompt": "By what name shall the arcade know you, fren?"}))
        else:
            await p.send(RESIZE)
            for col in SHIMMER:                       # the banner glimmers on login ✨
                await p.send(CLEAR + make_banner(col))
                await asyncio.sleep(0.16)
            await p.send(c(AMBER, "\nBy what name shall the arcade know you, fren? "))
        # --- name entry: reject command words as names (so no one is called "help"/"quit") ---
        for _ in range(4):
            raw = await reader.readline()
            if not raw and reader.at_eof():
                return
            name = clean_line(raw)
            if not name:
                await _prompt_again(p, "a name, fren?")
                continue
            if name.lower() in RESERVED_NAMES:
                await _prompt_again(p, f"'{name}' is a command, not a name — pick another, fren.")
                continue
            p.name = name[:24]
            break
        else:
            p.name = "a wandering fren"

        # --- one live session per player: take over any existing one (fixes multi-device divergence) ---
        for w2, other in list(PLAYERS.items()):
            if other is not p and other.name == p.name:
                try:
                    if other.web:
                        await other.send(json.dumps({"t": "signout", "text": "You signed in on another device."}))
                    else:
                        await other.send(c(RED, "\r\n-- you signed in on another device; this session is closed --\r\n"))
                    w2.close()
                except Exception:
                    pass
                PLAYERS.pop(w2, None)

        data = await asyncio.to_thread(STORE.get_or_create_player, p.name)
        p.room, p.inventory, p.wallet = data["room"], data["inventory"], data["wallet"]
        p.nostr, p.space, p.fren_tag = data["nostr"], data["space"], data["fren_tag"]
        p.xp, p.level, p.energy = data["xp"], data["level"], data["energy"]
        p.certs = await asyncio.to_thread(STORE.list_certificates, p.name)
        p.session_start_xp, p.session_start_runes = p.xp, len(p.certs)
        hello = f"@{p.fren_tag}" if p.fren_tag else p.name

        p.in_game = True
        if data["new"]:
            push(p, c(MAG, f"Welcome, {hello}. The high score is understanding. 💜"))
            if frens_aware() and not p.fren_tag:
                focus_text(p, "Welcome to the arcade", [
                    "", f"  This node is connected to frens.earth ({FRENS_URL}).", "",
                    "  Claim your handle and bind it to your @fren account:", "",
                    "     link fren <yourname>", "",
                    "  Or just explore — type  help  or  look.", "",
                ], AMBER)
            else:
                focus_room(p)
        else:
            # Welcome back with a summary + a nudge toward next goals.
            focus_text(p, f"Welcome back, {hello}", [
                "",
                f"  Level {p.level} · {p.xp} xp · {len(p.certs)} rune(s) · energy {p.energy}/100",
                f"  Last seen in: {ROOMS[p.room]['title']}",
                "",
                "  Good to see you, fren. What would you like to work on next?",
                "  Ask the Oracle (north), face a boss (down), or just  look  around.",
                "",
            ], AMBER)
            push(p, c(MAG, f"Welcome back, {hello}. Your progress was kept."))
        await broadcast_room(p.room, c(GREY, f"{hello} steps in from the street."), exclude=p)
        await show(p)

        while not reader.at_eof():
            raw = await reader.readline()
            if not raw:
                break
            line = clean_line(raw)
            if not line:
                await show(p)
                continue
            keep = await dispatch(p, line)
            if not keep:
                break
            await show(p)
    except (ConnectionResetError, asyncio.IncompleteReadError):
        pass
    finally:
        PLAYERS.pop(writer, None)
        who = f"@{p.fren_tag}" if p.fren_tag else p.name
        await broadcast_room(p.room, c(GREY, f"{who} fades from the arcade."))
        try:
            writer.close()
        except Exception:
            pass


async def _ws_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    """Bridge a browser WebSocket to the SAME game loop the telnet server uses (one engine, two
    transports). See services/mud/webbridge.py and services/mud/webclient.html."""
    if not await webbridge.handshake(reader, writer):
        try:
            writer.close()
        except Exception:
            pass
        return
    await handle_client(webbridge.WSReader(reader, writer), webbridge.WSWriter(writer), web=True)


async def main() -> None:
    global SERVER, LOOP
    LOOP = asyncio.get_running_loop()
    backend = type(STORE).__name__
    store_where = getattr(STORE, "path", "postgres DB-2")
    oracle = "local LLM" if (INFERENCE_BASE_URL and GEN_MODEL) else "scripted pacbot fallback"
    SERVER = await asyncio.start_server(handle_client, MUD_HOST, MUD_PORT)
    ws_server = await asyncio.start_server(_ws_client, MUD_HOST, MUD_WS_PORT)
    print(f"▓ Pac's Arcade · POKEMUD on {MUD_HOST}:{MUD_PORT}  [persisted via {backend} @ {store_where}, Oracle: {oracle}] 💜")
    print(f"  Connect:  python services/mud/play.py    (or: telnet {MUD_HOST} {MUD_PORT})")
    print(f"  In a browser:  http://{ADMIN_HTTP_HOST}:{ADMIN_HTTP_PORT}/play   (WebSocket bridge on {MUD_HOST}:{MUD_WS_PORT})")
    if LOCAL_SITE_URL:
        print(f"  Local arcade site: {LOCAL_SITE_URL}")
    http_srv = _start_admin_http()
    _start_console(LOOP)
    ticker = asyncio.create_task(_status_ticker())
    sampler = asyncio.create_task(_metrics_sampler())      # feeds the console's CPU/MEM/NET histograms
    tok_note = "  (auto-generated; set PA_ADMIN_TOKEN to pin it)" if ADMIN_TOKEN_GENERATED else ""
    print("  Operator console: type 'help' here.")
    print(f"    admin token : {ADMIN_TOKEN}{tok_note}   (in-MUD: 'admin {ADMIN_TOKEN}')")
    if http_srv:
        print(f"    web console : http://{ADMIN_HTTP_HOST}:{ADMIN_HTTP_PORT}/   "
              "(open in a browser, paste the admin token)")
    print(f"    frens.earth : {'connected — ' + FRENS_URL if frens_aware() else 'standalone (set PA_FRENS_URL to connect)'}")
    print(f"    matrix chat : {'ON' if CHAT_MATRIX else 'off (default) — enable with  admin chat on'}")

    try:
        async with SERVER, ws_server:
            await SHUTDOWN.wait()
    finally:
        ticker.cancel()
        sampler.cancel()
        for w, pl in list(PLAYERS.items()):
            try:
                await pl.send(c(MAG, "\r\nThe arcade lights power down. Your progress is saved. 💜\r\n"))
                w.close()
            except Exception:
                pass
        try:
            STORE.close()
        except Exception:
            pass

    if REBOOT:
        print("▓ POKEMUD rebooting…")
        os.execv(sys.executable, [sys.executable] + sys.argv)
    else:
        print("▓ POKEMUD is going offline. GG's, fren. 💜")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n▓ POKEMUD is going offline. GG's, fren. 💜")
