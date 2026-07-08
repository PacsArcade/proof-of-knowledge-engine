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
import unicodedata
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
# Data files live next to the service, not the caller's cwd — the server behaves the
# same whether launched from the repo root, services/mud, or a process manager.
DATA_DIR = os.environ.get("PA_MUD_DATA_DIR",
                          os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))
os.environ.setdefault("PA_GAMESTATE_SQLITE", os.path.join(DATA_DIR, "gamestate.dev.sqlite"))

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "common"))
import world_store  # noqa: E402
import webbridge     # noqa: E402  (same dir as this file — the browser WebSocket bridge)
import verses        # noqa: E402  (data-driven verse packs — rooms, NPCs, strings, gallery)

# --- the verse this node hosts (PA_VERSE selects; see services/mud/verses/) ---
VERSE = verses.load()
ROOMS = VERSE["rooms"]
NPCS = VERSE["npcs"]
GALLERY = VERSE.get("gallery", [])
VSTR = VERSE["strings"]
if not (os.environ.get("PA_SPACE") or os.environ.get("PA_NODE_NAME")):
    WORLD = VERSE["name"]
# Art showcase mode: 'media' lets capable clients (web) render real ordinal/rune
# images & video; 'ascii' forces the ASCII rendition everywhere. Console: art ascii|media
ART_MODE = os.environ.get("PA_ART_MODE", "media").strip().lower()
if ART_MODE not in ("media", "ascii"):
    ART_MODE = "media"

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
# Game chat (in-room `say` + any bridge): ON by default; operators can kill it globally,
# restrict specific @tags, and every player can mute it for themselves ('chat off').
GAME_CHAT = os.environ.get("PA_GAME_CHAT", "on").lower() not in ("0", "off", "false", "no")


# --- social connections: editable from the console, persisted across reboots ---
def _social_file() -> str:
    return os.environ.get("PA_SOCIAL_FILE", os.path.join(DATA_DIR, "social.json"))


def _load_social() -> None:
    global FRENS_URL, MATRIX_BRIDGE_URL
    try:
        with open(_social_file()) as f:
            d = json.load(f)
        FRENS_URL = d.get("frens_url", FRENS_URL)
        MATRIX_BRIDGE_URL = d.get("matrix_url", MATRIX_BRIDGE_URL)
    except Exception:
        pass


def social_set(frens_url: "str | None" = None, matrix_url: "str | None" = None) -> str:
    """Point the node at its frens.earth hub / Matrix bridge (empty string clears)."""
    global FRENS_URL, MATRIX_BRIDGE_URL
    if frens_url is not None:
        FRENS_URL = frens_url.strip()
    if matrix_url is not None:
        MATRIX_BRIDGE_URL = matrix_url.strip()
    os.makedirs(os.path.dirname(os.path.abspath(_social_file())), exist_ok=True)
    with open(_social_file(), "w") as f:
        json.dump({"frens_url": FRENS_URL, "matrix_url": MATRIX_BRIDGE_URL}, f, indent=2)
    event("admin", f"social links → frens: {FRENS_URL or 'standalone'} · matrix: {MATRIX_BRIDGE_URL or '—'}")
    return f"frens.earth: {FRENS_URL or 'standalone'} · matrix bridge: {MATRIX_BRIDGE_URL or '—'}"


_load_social()
# DEMO MODE: on by default until the courses are audited — runes etched are PRACTICE
# runes, clearly labeled, never presented as real credentials.
DEMO_MODE = os.environ.get("PA_DEMO_MODE", "on").lower() not in ("0", "off", "false", "no")

SERVER = None
LOOP = None
REBOOT = False
SHUTDOWN = asyncio.Event()

# --- screen control ----------------------------------------------------------
HOME = "\x1b[H"                       # cursor to top-left (in-place redraw)
CLEAR = "\x1b[2J\x1b[3J\x1b[H"        # full clear + scrollback, home
RESIZE = "\x1b[8;42;112t"            # ask for 42x112 (honored by some terminals; resize freely)


def _enable_vt() -> bool:
    """Enable ANSI (virtual-terminal) processing for the SERVER's own console and report
    whether stdout is an interactive TTY that can host the in-place status line."""
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    try:
        if not sys.stdout.isatty():
            return False
    except Exception:
        return False
    if sys.platform != "win32":
        return True
    try:
        import ctypes
        k = ctypes.windll.kernel32
        h = k.GetStdHandle(-11)                       # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint32()
        if not k.GetConsoleMode(h, ctypes.byref(mode)):
            return False
        return bool(k.SetConsoleMode(h, mode.value | 0x0004))   # ENABLE_VIRTUAL_TERMINAL_PROCESSING
    except Exception:
        return False


VT_TTY = _enable_vt()

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


# --- display width (emoji/wide-glyph aware, so the frame border never jogs) ----
_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_ZERO_WIDTH = {0x200D, 0xFE0E, 0xFE0F}          # ZWJ + variation selectors
# Terminal-double-wide singletons outside the emoji planes (⭐ ⚡ ❤ …).
_WIDE_ONES = {0x2B50, 0x26A1, 0x2764, 0x2B55, 0x267B}


def _ch_width(ch: str) -> int:
    o = ord(ch)
    if o in _ZERO_WIDTH or unicodedata.combining(ch):
        return 0
    if 0x1F000 <= o <= 0x1FAFF or o in _WIDE_ONES:
        return 2
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


def dwidth(s: str) -> int:
    return sum(_ch_width(ch) for ch in s)


def dw_crop(s: str, width: int) -> str:
    out, w = [], 0
    for ch in s:
        cw = _ch_width(ch)
        if w + cw > width:
            break
        out.append(ch)
        w += cw
    return "".join(out)


def dw_ljust(s: str, width: int) -> str:
    s = dw_crop(s, width)
    return s + " " * (width - dwidth(s))


def ansi_crop(s: str, width: int) -> str:
    """Crop a COLORED string to a display width — escape codes pass through free,
    and a cropped line closes its colors so nothing bleeds into the next row."""
    out, w, i = [], 0, 0
    while i < len(s):
        m = _ANSI.match(s, i)
        if m:
            out.append(m.group())
            i = m.end()
            continue
        cw = _ch_width(s[i])
        if w + cw > width - 1:                    # reserve one cell for the ellipsis
            return "".join(out) + R + c(GREY, "…")
        out.append(s[i])
        w += cw
        i += 1
    return "".join(out)


# One glyph family for movement everywhere: filled = compass, hollow = vertical.
DIR_GLYPH = {"north": "▲", "south": "▼", "east": "►", "west": "◄", "up": "△", "down": "▽"}


def exits_line(room: dict) -> str:
    return "Exits: " + " · ".join(f"{DIR_GLYPH.get(d, '·')} {d}" for d in room["exits"])


def dir_to(src: str, dst: str) -> "str | None":
    """First-step direction from src toward dst over the room graph (BFS), or None if
    unreachable / already there. Keeps every hint truthful from ANY room."""
    if src == dst:
        return None
    seen, queue = {src}, [(src, None)]
    while queue:
        room, first = queue.pop(0)
        for d, nxt in ROOMS.get(room, {}).get("exits", {}).items():
            step = first or d
            if nxt == dst:
                return step
            if nxt not in seen:
                seen.add(nxt)
                queue.append((nxt, step))
    return None


def hint_to(src: str, dst: str, label: str) -> str:
    """'the Oracle is ▲ north of here' — or 'right here' when you've arrived."""
    if src.startswith("home:"):                   # every home room opens south onto the floor
        return f"{label} is ▼ south of here, back on the floor"
    d = dir_to(src, dst)
    if d is None:
        return f"{label} is right here"
    return f"{label} is {DIR_GLYPH[d]} {d} of here"


# --- banner + attract mode (shown once before the game window) ---------------
# Block-letter logo — narrow glyphs only (█ ▀ ▄ are single-cell) so it centers cleanly.
LOGO = [
    "█▀▀▄ █▀▀█ █ ▄▀ █▀▀▀ █▀▄▀█ █  █ █▀▀▄",
    "█▄▄▀ █  █ ██   █▀▀  █ ▀ █ █  █ █  █",
    "█    █▄▄█ █ ▀▄ █▄▄▄ █   █ █▄▄█ █▄▄▀",
]

BOOT_LINES = [
    ("CRT POWER ...........", "OK"),
    ("COIN MECH ...........", "OK"),
    ("KNOWLEDGE CORE ......", "LOADED"),
    ("ORACLE LINK .........", "VIOLET"),
]

# A little Commodore-64 love: the cassette-era load ritual, played before the logo.
C64_LINES = [
    ("**** POKE BASIC V2 · 64K RAM FREE ****", 0.7),
    ("READY.", 0.6),
    ('LOAD "POKEMUD",8,1', 0.9),
    ("SEARCHING FOR POKEMUD", 1.0),
    ("LOADING", 1.2),
    ("READY.", 0.6),
    ("RUN", 0.7),
]


SUBTITLE = "Proof of Knowledge Engine - Multi User Dungeon"
_COIN_ROW = "\x00coin\x00"                       # placeholder swapped for the blinking coin


def make_banner(accent: str = BOLD + GOLD, coin: str = "", coin_col: str = "") -> str:
    """The attract banner. `accent` colors the POKEMUD logo (cycled to glimmer);
    `coin` renders centered on the INSERT COIN row inside the box."""
    verse_name = VERSE["name"].upper()
    lines = [
        "",
        verse_name,
        "presents",
        "",
        *LOGO,
        SUBTITLE,
        "",
        _COIN_ROW,
        "",
    ]
    width = max(dwidth(l) for l in lines if l != _COIN_ROW) + 8
    out = [c(MAG, "╔" + "═" * width + "╗")]
    for ln in lines:
        if ln == _COIN_ROW:
            txt, col = coin, (coin_col or BOLD + GOLD)
        elif ln in LOGO:
            txt, col = ln, accent
        elif ln == verse_name:
            txt, col = ln, BOLD + AMBER
        elif ln == SUBTITLE:
            txt, col = ln, AMBER
        else:
            txt, col = ln, GREY
        pad = width - dwidth(txt)
        out.append(c(MAG, "║") + c(col, " " * (pad // 2) + txt + " " * (pad - pad // 2)) + c(MAG, "║"))
    out.append(c(MAG, "╚" + "═" * width + "╝"))
    return "\n" + "\n".join(out) + "\n"


def banner_width() -> int:
    lines = ["", VERSE["name"].upper(), "presents", "", *LOGO, SUBTITLE, "", ""]
    return max(dwidth(l) for l in lines) + 8


BANNER = make_banner()
# Colors the title cycles through on login so PAC'S ARCADE / POKEMUD glimmers.
SHIMMER = [BOLD + GOLD, BOLD + CYAN, BOLD + MAG, BOLD + AMBER, BOLD + GREEN, BOLD + GOLD]

HELP_PAGES = 2


def help_lines(p: "Player", page: int = 1) -> list[str]:
    """Paginated help — every command column lines up at 20 chars, and the boss hint is
    computed from where the player stands, so 'down' is never a lie. `help 2` / `next`
    turn the page."""
    if page == 2:
        return [
            "  ▸ IDENTITY",
            "   link fren <name>     claim your @fren",
            "   verify <code>        confirm the pairing code",
            "   link nostr <npub1…>  bind your nostr identity",
            "   link space <@name>   bind your spaces name",
            "   backup               anchor your progress on-chain",
            "",
            "  ▸ CHAT",
            "   say <msg>            talk to the room",
            "   who                  see who's online",
            "   chat on|off          mute game chat, just for you",
            "",
            "  ▸ HOME & ART",
            "   home  (/home)        go to your own room",
            "   rename room <name>   name your room",
            "   /fren invite <name>  let a fren visit your room",
            "   /fren visit <name>   drop by a fren's room",
            "   gallery              the art on display",
            "   view <n>             stand before a piece",
            "   quit                 save + leave",
            "",
            "  ── page 2/2  ·   help 1  or  next  to loop back ──",
        ]
    boss_room = _npc_room("boss")
    boss = hint_to(p.room, boss_room, "the boss") if boss_room else "no boss in this verse (yet)"
    t_rid = _npc_room("socratic")
    tid = get_room(t_rid)["npcs"][0] if t_rid else "npc"
    return [
        "  ▸ MOVE",
        "   north south east west up down     shortcuts: n s e w u d",
        "   go <dir>  ·  look (l)             look around the room",
        "",
        "  ▸ LEARN",
        f"   talk {tid:<15} begin the trial",
        f"   ask {tid} <q>{' ' * max(1, 13 - len(tid))}ask anything",
        "   answer <text>        reply to a question",
        f"   challenge            {boss}",
        "   pull lever           use a feature in the room",
        "",
        "  ▸ YOU",
        "   stats                your level · xp · energy",
        "   profile              your identity card",
        "   certs                the runes you've earned",
        "   inventory (i)        what you carry",
        "   examine <name>       look at another fren",
        "",
        "  ── page 1/2  ·   help 2  or  next  for identity, chat & home ──",
    ]


def show_help(p: "Player", page: int = 1) -> None:
    page = 2 if page == 2 else 1
    p.help_page = page
    focus_text(p, f"How to play ({page}/{HELP_PAGES})", help_lines(p, page), GREY)


# --- the world (rooms come from the verse pack; home rooms are per-player) ----
HOME_PREFIX = "home:"


def home_id(name: str) -> str:
    return HOME_PREFIX + name


def is_home(room_id: str) -> bool:
    return room_id.startswith(HOME_PREFIX)


def home_owner(room_id: str) -> str:
    return room_id[len(HOME_PREFIX):]


def get_room(room_id: str) -> dict:
    """Resolve any room id — verse rooms from the pack, `home:<player>` built on the fly.
    Unknown ids (a stale save from another verse) land on the verse start room."""
    if is_home(room_id):
        owner = room_id[len(HOME_PREFIX):]
        custom = STORE.get_feature(room_id, "room_name", None)
        return {
            "title": custom or VERSE["home"]["default_name"].format(name=owner),
            "desc": VERSE["home"]["desc"],
            "exits": {"south": VERSE["start_room"]},
            "npcs": [], "art": [], "home_of": owner,
        }
    return ROOMS.get(room_id) or ROOMS[VERSE["start_room"]]


def _npc_room(kind: str) -> "str | None":
    """First verse room hosting an NPC of `kind` ('socratic' | 'boss') — for hints."""
    for rid, room in ROOMS.items():
        for n in room["npcs"]:
            if NPCS[n]["kind"] == kind:
                return rid
    return None


def npc_here(p: "Player", kind: "str | None" = None) -> "tuple[str, dict] | None":
    for nid in get_room(p.room)["npcs"]:
        if kind is None or NPCS[nid]["kind"] == kind:
            return nid, NPCS[nid]
    return None


def _match_npc(text: str, room_npcs: list[str]) -> "str | None":
    """Match player text ('oracle', 'the quartermaster', 'boss') to an NPC in the room."""
    text = text.strip().lower()
    if not text:
        return None
    for nid in room_npcs:
        if text == nid or text in NPCS[nid]["name"].lower():
            return nid
        if text == "boss" and NPCS[nid]["kind"] == "boss":
            return nid
    return None

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
        self.room = VERSE["start_room"]
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
        self.trial_pending = None          # socratic-NPC id awaiting an answer
        self.boss_pending = None           # boss id awaiting an answer
        self.help_page = 1                 # last help page shown ('next' turns it)
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
        self.chat_muted = False            # player's OWN choice: mute game chat ('chat off')
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
    room = get_room(p.room)
    lines: list[str] = []
    lines += _wrap(room["desc"], BOARD_W - 4)
    lines.append("")
    if room.get("home_of"):                    # a player's own room: their showcase
        lines += _home_showcase(room["home_of"], viewer=p)
    if room["npcs"]:
        first = NPCS[room["npcs"][0]]
        hint = "(type 'challenge')" if first["kind"] == "boss" else f"(try 'talk {room['npcs'][0]}')"
        lines.append("Here: " + ", ".join(NPCS[n]["name"] for n in room["npcs"]) + "   " + hint)
    others = [pl.name for w, pl in PLAYERS.items() if pl.room == p.room and pl is not p]
    if others:
        lines.append("Also here: " + ", ".join(others))
    lines.append("")
    lines.append(exits_line(room))    # same glyphs as the arrows on the frame border
    focus_text(p, room["title"], lines, GREEN, art=room.get("art"))


def _home_showcase(owner: str, viewer: "Player") -> list[str]:
    """The rune wall + gallery corner rendered inside a home room."""
    certs = (viewer.certs if viewer.name == owner
             else STORE.list_certificates(owner))
    lines = []
    if certs:
        lines.append(f"On the wall: {len(certs)} soulbound rune(s)")
        lines += [f"   * {ct['rune_name']}" for ct in certs[:4]]
        if len(certs) > 4:
            lines.append(f"   …and {len(certs) - 4} more")
    else:
        lines.append("The rune wall waits for its first etch.")
    if GALLERY:
        lines.append(f"Gallery corner: {len(GALLERY)} piece(s) on display   (try 'gallery')")
    lines.append("")
    return lines


def focus_text(p: Player, title: str, lines: list[str], color: str = GREEN,
               media: "dict | None" = None, art: "list[str] | None" = None) -> None:
    """`art` is a block that must never re-wrap: terminals center it in the frame,
    the web client renders it as its own no-wrap block (so walls survive mobile)."""
    p.focus = {"title": title, "lines": list(lines), "color": color, "media": media,
               "art": list(art) if art else []}


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


FRAME_MAX_H = 26     # a panel may grow to this many body rows before it truncates


def _frame(title: str, body: list[str], exits: dict, color: str) -> list[str]:
    W = BOARD_W
    # Wrap anything that would overflow the frame; grow the window (up to FRAME_MAX_H)
    # instead of silently cutting a panel off at BODY_H.
    rows: list[str] = []
    for line in body:
        if dwidth(line) <= W - 2:
            rows.append(line)
        else:
            rows += _wrap(line, W - 4)
    if len(rows) > FRAME_MAX_H:
        rows = rows[:FRAME_MAX_H - 1] + ["… (the rest is cut off — this panel is too tall)"]
    while len(rows) < BODY_H:
        rows.append("")
    mid = len(rows) // 2

    # top: ▲ north (centered) + a hollow '△ up' corner tag, then the title
    top = list("═" * W); tdoors = set()
    if "north" in exits:
        top[W // 2] = "▲"; tdoors.add(W // 2)
    if "up" in exits:
        tag = "△ up"
        for j, ch in enumerate(tag):
            top[W - len(tag) - 3 + j] = ch; tdoors.add(W - len(tag) - 3 + j)
    for i, ch in enumerate(f"╡ {title} ╞"):
        if 3 + i < W and (3 + i) not in tdoors:
            top[3 + i] = ch
    out = [c(MAG, "╔") + _render_border(top, tdoors) + c(MAG, "╗")]

    # sides: ◄ / ► compass doors on the middle row
    for i, line in enumerate(rows):
        left = c(CYAN, "◄") if (i == mid and "west" in exits) else c(MAG, "║")
        right = c(CYAN, "►") if (i == mid and "east" in exits) else c(MAG, "║")
        out.append(left + " " + c(color, dw_ljust(line, W - 2)) + " " + right)

    # bottom: ▼ south (centered) + a hollow '▽ down' corner tag
    bot = list("═" * W); bdoors = set()
    if "south" in exits:
        bot[W // 2] = "▼"; bdoors.add(W // 2)
    if "down" in exits:
        tag = "▽ down"
        for j, ch in enumerate(tag):
            bot[W - len(tag) - 3 + j] = ch; bdoors.add(W - len(tag) - 3 + j)
    out.append(c(MAG, "╚") + _render_border(bot, bdoors) + c(MAG, "╝"))
    return out


def render_screen(p: Player) -> str:
    room = get_room(p.room)
    f = p.focus or {"title": room["title"], "lines": [], "color": GREEN}
    who = f"@{p.fren_tag}" if p.fren_tag else p.name
    header = (c(BOLD + MAG, f"  {VERSE['name'].upper()} · P.O.K.E.")
              + c(GREY, f"      {who} · {room['title']}"))
    rank = verses.rank_for(VERSE, p.level)
    hud = ("  " + c(GOLD, f"⭐ Lv {p.level}") + (c(AMBER, f" {rank}") if rank else "")
           + c(GREY, " · ") + c(CYAN, f"✦ {p.xp} xp")
           + c(GREY, " · ") + c(GOLD, f"🎓 {len(p.certs)}") + c(GREY, " · ") + c(GREEN, f"⚡ {p.energy}"))
    art = f.get("art") or []
    body = (center_block(art) + [""] if art else []) + f["lines"]
    frame = _frame(f["title"], body, room["exits"], f.get("color", GREEN))
    log = list(p.log)[-LOG_H:]
    log = [""] * (LOG_H - len(log)) + log            # bottom-align the log
    # Crop every free-form row to the window width — a line that hard-wraps in the
    # terminal would shift the whole in-place redraw.
    parts = [ansi_crop(header, BOARD_W + 2), hud, ""] + frame + ["", c(GREY, "  ── messages ──")]
    parts += ["  " + ansi_crop(l, BOARD_W) for l in log]
    parts += ["", c(AMBER, f"  {who} ") + c(GREY, "» ")]
    out = HOME
    for ln in parts[:-1]:
        out += ln + "\x1b[K\r\n"
    out += parts[-1] + "\x1b[K\x1b[J"                # prompt; clear anything below
    return out


# --- JSON render mode (browser clients) --------------------------------------
# Telnet clients get ANSI (render_screen). Browser clients get a STRUCTURED screen model, so the
# web client can render it as real UI — glow, animation, sound — instead of interpreting ANSI.
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
    room = get_room(p.room)
    f = p.focus or {"title": room["title"], "lines": [], "color": GREEN}
    fx, p.pending_fx = p.pending_fx, []
    return {
        "t": "screen",
        "verse": VERSE["name"],
        "room": room["title"],
        "who": display_name(p),
        "hud": {"level": p.level, "xp": p.xp, "xp_into": p.xp % 100,
                "runes": len(p.certs), "energy": p.energy,
                "rank": verses.rank_for(VERSE, p.level)},
        "title": f.get("title") or room["title"],
        "color": _color_name(f.get("color", GREEN)),
        "art": [_plain(l) for l in (f.get("art") or [])],   # no-wrap block; client centers it
        "body": [_plain(l) for l in f.get("lines", [])],
        # Real ordinal/rune media for capable clients — unless the node forces ASCII.
        "media": (f.get("media") if ART_MODE == "media" else None),
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
RESERVED_NAMES = {"help", "quit", "exit", "q", "look", "l", "admin", "boss",
                  "say", "go", "north", "south", "east", "west", "up", "down", "n", "s", "e", "w",
                  "talk", "answer", "ask", "challenge", "fight", "stats", "profile", "certs", "runes",
                  "inventory", "inv", "i", "backup", "link", "verify", "who", "pull", "examine",
                  "home", "rename", "invite", "visit", "gallery", "view", "enter",
                  "chat", "fren", "next", "more", "load", "run"} | set(NPCS)


async def _prompt_again(p: "Player", text: str) -> None:
    """Re-ask for a name (structured for web, ANSI for telnet)."""
    if p.web:
        await p.send(json.dumps({"t": "prompt", "text": text}))
    else:
        await p.send(c(AMBER, "\r\n" + text + " "))


def center_block(lines: list[str]) -> list[str]:
    """Center a block of art in the frame as ONE unit — every line shifts by the same
    offset, so the piece's internal alignment survives."""
    width = max((dwidth(l) for l in lines), default=0)
    off = max(0, (BOARD_W - 2 - width) // 2)
    return [" " * off + l for l in lines]


async def animate(p: Player, frames: list[list[str]], title: str, color: str = GOLD, hold: float = 0.5) -> None:
    """Play ASCII frames inside the window — the primitive bosses & lesson effects use.
    Frames ride the art channel: centered on terminals, never re-wrapped on the web."""
    for frame in frames:
        focus_text(p, title, [], color, art=frame)
        await show(p)
        await asyncio.sleep(hold)


# --- NPC rail: verse NPCs are run by the node's local AI ----------------------
# Every NPC in a verse pack declares a persona (its system prompt), a kind
# ('socratic' teachers, 'boss' encounters), an optional scripted trial, and a
# fallback line for nodes without a local model. Free text routed to an NPC goes
# to the local LLM with the player's recent memory (DB-2) — so bots REMEMBER
# frens across visits. Dungeon encounters ride the same rail: data, not code.
def _npc_panel(npc: dict, lines: list[str]) -> list[str]:
    return ["", f"  {npc['name']} turns its attention to you.", ""] + ["  " + l for l in lines]


async def trial_open(p: Player, nid: str) -> None:
    npc = NPCS[nid]
    trial = npc.get("trial")
    if not trial:
        await converse_npc(p, nid, "hello")
        return
    p.trial_pending = nid
    body = _npc_panel(npc, _wrap('"' + trial["question"] + '"', BOARD_W - 6)
                      + ["", "(answer with:  answer <your words>)"])
    focus_text(p, npc["name"], body, MAG)


async def trial_judge(p: Player, ans: str) -> None:
    nid, p.trial_pending = p.trial_pending, None
    npc = NPCS[nid]
    trial = npc["trial"]
    low = ans.lower()
    if any(k in low for k in trial["keys"]):
        if await asyncio.to_thread(STORE.has_certificate, p.name, trial["class"]["class_id"]):
            focus_text(p, npc["name"], _npc_panel(npc, _wrap('"' + trial["already"] + '"', BOARD_W - 6)), MAG)
        else:
            global RUNES_ETCHED
            RUNES_ETCHED += 1
            await asyncio.to_thread(STORE.record_competency, p.name, trial["class"]["class_id"], 0.9,
                                    f"Passed {npc['name']}'s trial: {trial['class']['title']}.")
            push(p, c(MAG, f'{npc["name"]}: "{trial.get("pass_line", "Understanding demonstrated.")}"'))
            await etch_class_rune(p, trial["class"], xp=int(trial.get("xp", 100)))
    else:
        p.trial_pending = nid
        focus_text(p, npc["name"], _npc_panel(npc, _wrap('"' + trial["retry"] + '"', BOARD_W - 6)), MAG)


def cert_card_lines(cert: dict) -> list[str]:
    lines = [
        "",
        "  *  " + cert["rune_name"],
        "",
        "  Class:   " + cert["title"],
        "  Earned:  " + str(cert["block_time"]) + f"   (block {cert['block_height']})",
        "  Wallet:  " + cert["original_wallet"],
        "  soulbound · non-transferable · regtest (mock)",
        "",
    ]
    if DEMO_MODE:
        lines += [
            "  ⚠ DEMO rune — practice only. Courses aren't rated for real",
            "  certification yet; nothing here is a credential.",
        ]
    else:
        lines += [
            "  Etched into your wallet. Block time + wallet live on-chain — even",
            "  if it's ever moved, everyone knows YOU earned it. 💜",
        ]
    return lines


async def etch_class_rune(p: Player, spec: dict, xp: int = 100) -> None:
    block = 21_000 + len(p.certs)
    cert = await asyncio.to_thread(
        STORE.etch_certificate, p.name, spec["class_id"], spec["rune"], spec["title"], p.wallet, block
    )
    p.certs = await asyncio.to_thread(STORE.list_certificates, p.name)
    old_level = p.level
    res = await asyncio.to_thread(STORE.add_xp, p.name, xp); p.xp, p.level = res["xp"], res["level"]
    p.pending_fx.append("etch")                        # cue the web client to glow/particle the etch
    demo = " [demo]" if DEMO_MODE else ""
    event("etch", f"{display_name(p)} etched {spec['rune']}{demo} (+{xp} xp)")
    await animate(p, RUNE_ANIM, "Etching a rune...", GOLD, hold=1.3)
    focus_text(p, "Soulbound Class Rune" + (" · DEMO" if DEMO_MODE else ""), cert_card_lines(cert), GOLD)
    if p.level > old_level:
        p.pending_fx.append("levelup")
    push(p, c(GOLD, f"🎓 etched {spec['rune']}{demo}  (+{xp} xp)"))


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
    # Standalone nodes can't check a claim against frens.earth — identity links are the
    # player's OWN claim until the node syncs with the hub, and we say so honestly.
    unv = "" if frens_aware() else "  (claimed — verifies via frens.earth)"
    lines = [
        "",
        "  Character : " + p.name,
        "  Wallet    : " + (p.wallet or "—"),
        "  @fren     : " + ((("@" + p.fren_tag) + unv) if p.fren_tag else "unlinked   (link fren <name>)"),
        "  nostr     : " + ((p.nostr + unv) if p.nostr else "unlinked   (link nostr <npub1…>)"),
        "  space     : " + ((p.space + unv) if p.space else "unlinked   (link space <@name>)"),
        "  Runes     : " + f"{len(p.certs)} soulbound class rune(s)",
        "  Backup    : " + ("run  backup  to anchor on-chain"),
    ]
    if not frens_aware():
        lines.append("  This node is standalone — links confirm when it joins frens.earth.")
    focus_text(p, ("@" + p.fren_tag) if p.fren_tag else p.name, lines, AMBER)


async def show_certs(p: Player) -> None:
    if not p.certs:
        rid = _npc_room("socratic")
        where = (hint_to(p.room, rid, get_room(rid)["title"]) if rid
                 else "seek out a teacher")
        focus_text(p, "Your runes", ["", "  No class runes yet.", "",
                                      f"  {where} — runes are earned there. 🎓"], GOLD)
        return
    lines = ["", "  Your soulbound class runes:" + ("   (DEMO — practice only)" if DEMO_MODE else ""), ""]
    for cert in p.certs:
        lines.append(f"  * {cert['rune_name']}  -  {cert['title']}")
        lines.append(f"       earned {cert['block_time']} · block {cert['block_height']}")
    lines += ["", ("  ⚠ Demo runes — not real credentials until the courses are audited."
                   if DEMO_MODE else "  Non-transferable. Move one and provenance still names you.")]
    focus_text(p, "Your runes", lines, GOLD)


# =============================================================================
# Operator console — live stats, knowledge-swarm health, safe reboot/shutdown.
# Reachable three ways: local terminal (stdin), in-MUD `admin <token>`, HTTP rails.
# =============================================================================
def _fmt_dur(secs: float) -> str:
    secs = int(secs)
    h, m, s = secs // 3600, (secs % 3600) // 60, secs % 60
    return (f"{h}h " if h else "") + f"{m:02d}m {s:02d}s"


# --- console output: event feed + a single in-place status line ----------------
# On a real TTY the status line REFRESHES in place (no 1-min scroll spam); events print
# above it. Piped/service stdout falls back to change-only lines + a 5-min heartbeat.
STATUS_EVERY = max(5, int(os.environ.get("PA_STATUS_EVERY", "60")))
_EVENTS: deque = deque(maxlen=500)
_EVENT_ID = 0
_STATUS_TXT = ""
EVENT_COLORS = {"join": GREEN, "part": GREY, "etch": GOLD, "levelup": GOLD,
                "admin": CYAN, "warn": RED, "info": GREY}


def cprint(line: str = "") -> None:
    """Print a console line without clobbering the in-place status line."""
    if VT_TTY and _STATUS_TXT:
        sys.stdout.write("\r\x1b[K" + line + "\n" + _STATUS_TXT)
    else:
        sys.stdout.write(line + "\n")
    sys.stdout.flush()


def _draw_status(line: str) -> None:
    global _STATUS_TXT
    _STATUS_TXT = line
    if VT_TTY:
        sys.stdout.write("\r\x1b[K" + line)
        sys.stdout.flush()


def event(kind: str, msg: str) -> None:
    """Record an operator-visible event (ring buffer → console + GET /events)."""
    global _EVENT_ID
    _EVENT_ID += 1
    _EVENTS.append({"id": _EVENT_ID, "at": time.strftime("%H:%M:%S"), "kind": kind, "msg": msg})
    cprint("  " + c(GREY, time.strftime("%H:%M:%S")) + " "
           + c(EVENT_COLORS.get(kind, GREY), f"{kind:>7}") + c(GREY, " │ ") + msg)


def events_since(since: int) -> dict:
    return {"events": [e for e in _EVENTS if e["id"] > int(since)], "next": _EVENT_ID}


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


def art_mode_set(mode: str) -> str:
    """Console/admin toggle: 'ascii' forces ASCII art everywhere; 'media' lets web
    clients render real ordinal/rune images + video."""
    global ART_MODE
    mode = mode.strip().lower()
    if mode in ("ascii", "on"):           # 'art ascii on' and plain 'art ascii'
        ART_MODE = "ascii"
    elif mode in ("media", "off", "ascii off"):
        ART_MODE = "media"
    else:
        return f"art mode is '{ART_MODE}' — usage:  art ascii|media"
    event("admin", f"art mode → {ART_MODE}")
    return f"art mode → {ART_MODE}" + ("  (ASCII everywhere)" if ART_MODE == "ascii"
                                       else "  (web clients may render full media)")


def stats_json() -> dict:
    return {
        "uptime_s": int(time.time() - SERVER_START),
        "player_count": len(PLAYERS),
        "world": WORLD,
        "verse": VERSE["id"],
        "art_mode": ART_MODE,
        "players": [{
            "name": p.name, "fren": p.fren_tag, "world": WORLD, "room": p.room,
            "client": "web" if p.web else "terminal", "module": "FREE PLAY",
            "muted": p.muted, "watched": p.watched,
            "timeout_s": max(0, int(p.timeout_until - time.time())),
            "uptime_s": int(time.time() - p.connected_at),
            "idle_s": int(time.time() - p.idle_since), "admin": p.is_admin,
        } for p in PLAYERS.values()],
        "bans": bans_list(),
        "frens_url": FRENS_URL,
        "matrix_bridge": MATRIX_BRIDGE_URL,
        "runes_etched_session": RUNES_ETCHED,
        "store": {"backend": type(STORE).__name__, "location": getattr(STORE, "path", "postgres DB-2")},
        "oracle": ("local-llm:" + GEN_MODEL) if (INFERENCE_BASE_URL and GEN_MODEL) else "scripted",
        "chat_matrix": CHAT_MATRIX,
        "game_chat": GAME_CHAT,
        "chat_blocked": _load_chatblocks(),
        "demo_mode": DEMO_MODE,
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
    event("admin", f"broadcast: {msg[:80]}")
    return f"broadcast to {len(PLAYERS)} player(s)"


async def op_kick(name: str) -> str:
    for w, pl in list(PLAYERS.items()):
        if pl.name.lower() == name.lower() or (pl.fren_tag or "").lower() == name.lstrip("@").lower():
            # Same branded message on web and terminal (the web client shows it on its
            # end screen instead of silently auto-reconnecting).
            await send_gameover(pl, "kicked", [
                "GAME OVER",
                "An operator removed you from the floor. Your progress is saved.",
                "You can reconnect — repeat trouble means a longer bench. 💜",
            ])
            event("admin", f"kicked {pl.name}")
            return f"kicked {pl.name}"
    return f"no player matching '{name}'"


async def op_shutdown(reason: str = "maintenance", reboot: bool = False) -> str:
    global REBOOT
    REBOOT = reboot
    verb = "rebooting" if reboot else "shutting down"
    event("admin", f"{verb} ({reason})")
    await op_broadcast(f"P.O.K.E. is {verb} now ({reason}). Progress saved — back soon, fren. 💜")
    await asyncio.sleep(0.3)
    SHUTDOWN.set()
    return verb


def set_chat_matrix(on: bool) -> str:
    global CHAT_MATRIX
    CHAT_MATRIX = on
    return f"matrix chat {'ON — say now mirrors to the Matrix verse' if on else 'off — local rooms only'}"


# --- game-chat controls (global kill switch + per-@tag restriction) ------------
CHATBLOCK_FILE = os.environ.get("PA_CHATBLOCK_FILE", os.path.join(DATA_DIR, "chatblock.json"))


def _load_chatblocks() -> list[str]:
    try:
        with open(CHATBLOCK_FILE) as f:
            return [str(t).lstrip("@").lower() for t in json.load(f).get("blocked", [])]
    except Exception:
        return []


def set_game_chat(on: bool) -> str:
    global GAME_CHAT
    GAME_CHAT = bool(on)
    event("admin", f"game chat {'ON' if on else 'OFF (node-wide)'}")
    return f"game chat {'ON — frens can say to the room' if on else 'OFF — says are local-only node-wide'}"


def chat_restrict(tag: str, blocked: bool) -> str:
    tag = tag.strip().lstrip("@").lower()
    if not tag:
        return "usage: chat block|allow <@tag>"
    blocks = _load_chatblocks()
    if blocked and tag not in blocks:
        blocks.append(tag)
    if not blocked:
        blocks = [b for b in blocks if b != tag]
    os.makedirs(os.path.dirname(os.path.abspath(CHATBLOCK_FILE)), exist_ok=True)
    with open(CHATBLOCK_FILE, "w") as f:
        json.dump({"blocked": blocks}, f, indent=2)
    event("admin", f"chat {'restricted' if blocked else 'allowed'} for @{tag}")
    return f"@{tag} chat {'restricted — their says stay local' if blocked else 'allowed'}"


def chat_blocked(p: "Player") -> bool:
    blocks = _load_chatblocks()
    return p.name.lower() in blocks or (p.fren_tag or "").lower() in blocks


def chat_status() -> dict:
    return {"game_chat": GAME_CHAT, "matrix": CHAT_MATRIX, "blocked": _load_chatblocks()}


def chat_admin(rest: str) -> str:
    """One grammar for every operator surface: console, in-MUD admin, HTTP."""
    sub, _, arg = rest.partition(" ")
    sub, arg = sub.lower().strip(), arg.strip()
    if sub in ("on", "off"):
        return set_game_chat(sub == "on")
    if sub == "matrix":
        return set_chat_matrix(arg.lower() in ("on", "1", "true", "yes"))
    if sub == "block":
        return chat_restrict(arg, True)
    if sub == "allow":
        return chat_restrict(arg, False)
    if sub in ("", "status", "blocks"):
        st = chat_status()
        blocked = (", ".join("@" + b for b in st["blocked"])) if st["blocked"] else "none"
        return (f"game chat {'ON' if st['game_chat'] else 'OFF'} · matrix "
                f"{'ON' if st['matrix'] else 'off'} · restricted tags: {blocked}")
    return "usage: chat on|off · chat matrix on|off · chat block|allow <@tag> · chat status"


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
    "  stats · who · nodes · events · broadcast <m>\n"
    "  kick <n> · ban <n> [min] [reason] · unban <n> · bans · timeout via web console\n"
    "  chat on|off · chat matrix on|off · chat block|allow <@tag> · chat status\n"
    "  social frens|matrix <url> · art ascii|media · ext <name> on|off · games\n"
    "  reboot · shutdown · help"
)


async def handle_console(cmd: str) -> None:
    verb, _, rest = cmd.partition(" ")
    verb, rest = verb.lower().strip(), rest.strip()
    if not verb:
        return
    if verb in ("help", "?"):
        cprint(CONSOLE_HELP)
    elif verb in ("stats", "status"):
        cprint(stats_report())
    elif verb == "who":
        cprint(f"{len(PLAYERS)} online: " + ", ".join((f"@{p.fren_tag}" if p.fren_tag else p.name) for p in PLAYERS.values()))
    elif verb in ("nodes", "swarm"):
        cprint(nodes_report(await get_swarm_status(force=True)))
    elif verb in ("events", "log"):
        for e in list(_EVENTS)[-15:]:
            cprint(f"  {e['at']} {e['kind']:>7} │ {e['msg']}")
    elif verb in ("broadcast", "bcast", "say"):
        cprint(await op_broadcast(rest) if rest else "usage: broadcast <message>")
    elif verb == "kick":
        cprint(await op_kick(rest) if rest else "usage: kick <name>")
    elif verb == "ban":
        name, _, tail = rest.partition(" ")
        mins, _, reason = tail.partition(" ")
        cprint(await op_ban(name, int(mins) if mins.isdigit() else None,
                            (reason if mins.isdigit() else tail).strip())
               if name else "usage: ban <name> [minutes] [reason]   (no minutes = permanent)")
    elif verb == "unban":
        cprint(await op_unban(rest) if rest else "usage: unban <name>")
    elif verb == "bans":
        bl = bans_list()
        cprint("\n".join(f"  {b['name']:<18} "
                         + ("permanent" if b['left_s'] == -1 else f"{b['left_s'] // 60}m left")
                         + (f"  ({b['reason']})" if b['reason'] else "") for b in bl)
               if bl else "no active bans — good vibes on the floor")
    elif verb == "social":
        kind, _, url = rest.partition(" ")
        kind = kind.lower().strip()
        if kind in ("frens", "frens.earth"):
            cprint(social_set(frens_url=url.strip()))
        elif kind == "matrix":
            cprint(social_set(matrix_url=url.strip()))
        else:
            cprint(f"frens.earth: {FRENS_URL or 'standalone'} · matrix bridge: {MATRIX_BRIDGE_URL or '—'}\n"
                   "usage: social frens <url> · social matrix <url>   (empty url clears)")
    elif verb == "chat":
        cprint(chat_admin(rest))
    elif verb == "art":
        cprint(art_mode_set(rest))
    elif verb == "ext":
        name, _, state = rest.partition(" ")
        cprint(extensions_set(name.strip(), state.strip().lower() in ("on", "1", "true", "yes"))
               if name else "usage: ext <name> on|off   (extensions: " + ", ".join(_load_extensions()) + ")")
    elif verb == "games":
        cprint("\n".join(f"  {g['name']:<14} {g['kind']:<8} {g.get('url', '') or '—':<28} "
                         f"{'ON' if g.get('enabled') else 'off'}{'  [builtin]' if g.get('builtin') else ''}"
                         for g in _load_games()))
    elif verb == "reboot":
        cprint(await op_shutdown("operator reboot", reboot=True))
    elif verb == "shutdown":
        cprint(await op_shutdown("operator shutdown", reboot=False))
    else:
        cprint(f"unknown console command '{verb}' — type help")


def _start_console(loop: asyncio.AbstractEventLoop) -> None:
    def run() -> None:
        try:
            for line in sys.stdin:
                asyncio.run_coroutine_threadsafe(handle_console(line.strip()), loop)
        except Exception:
            pass
    threading.Thread(target=run, daemon=True).start()


async def _status_ticker(interval: "int | None" = None) -> None:
    """TTY: refresh ONE status line in place. Non-TTY: print only on change (+5-min heartbeat)."""
    interval = interval or (STATUS_EVERY if VT_TTY else min(STATUS_EVERY, 60))
    last_sig, last_print = None, 0.0
    while not SHUTDOWN.is_set():
        sw = await get_swarm_status()
        peers = sw.get("peers", sw.get("nodes", 0)) if sw.get("online") else "offline"
        up = _fmt_dur(time.time() - SERVER_START)
        if VT_TTY:
            _draw_status(c(MAG, "▓ ") + c(BOLD + GREEN, f"{len(PLAYERS)} online")
                         + c(GREY, " · swarm: ") + c(CYAN if sw.get("online") else GREY, str(peers))
                         + c(GREY, f" · up {up} · ") + c(AMBER, WORLD)
                         + c(GREY, " · type 'help' for console commands "))
        else:
            sig = (len(PLAYERS), str(peers))
            if sig != last_sig or time.time() - last_print >= 300:
                print(f"[status] {len(PLAYERS)} online · swarm nodes: {peers} · uptime {up}", flush=True)
                last_sig, last_print = sig, time.time()
        try:
            await asyncio.wait_for(SHUTDOWN.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass


# --- HTTP control rails (serves the web-admin page + JSON API) ----------------
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer  # noqa: E402

_HERE = os.path.dirname(os.path.abspath(__file__))
_ADMIN_HTML = os.path.join(_HERE, "admin.html")
_WEBCLIENT_HTML = os.path.join(_HERE, "webclient.html")


class _AdminHTTP(BaseHTTPRequestHandler):
    def _authed(self) -> bool:
        tok = self.headers.get("X-POKE-Admin-Token", "")
        return bool(tok) and secrets.compare_digest(tok, ADMIN_TOKEN)

    def _bot_blocked(self) -> bool:
        """Server-owner bots identify with X-POKE-Bot; refuse them while their extension is off."""
        bot = self.headers.get("X-POKE-Bot", "").strip()
        if bot and not extension_enabled(bot):
            self._reply(403, {"error": f"extension '{bot}' is disabled — the owner can enable it "
                                       "in the node console (Extensions) or:  ext " + bot.lower() + " on"})
            return True
        return False

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
        if path.startswith("/u/"):                     # public: a fren's profile + moderation state
            import urllib.parse                        # (the website's /u/<name> page pulls this)
            name = urllib.parse.unquote(path[3:]).strip()
            a = STORE.public_attributes(name) if name else None
            if not a:
                return self._reply(404, {"error": "no fren by that name"})
            b = ban_info(a["name"])
            return self._reply(200, {
                "name": a["name"], "fren": a["fren_tag"], "level": a["level"], "xp": a["xp"],
                "runes": a["runes"], "verse": VERSE["id"], "world": WORLD,
                "online": any(pl.name == a["name"] for pl in PLAYERS.values()),
                "demo_mode": DEMO_MODE,
                "moderation": {
                    "banned": bool(b),
                    "ban_reason": (b or {}).get("reason", ""),
                    "ban_left_s": (-1 if (b and b.get("until", -1) == -1)
                                   else (max(0, int(b["until"] - time.time())) if b else 0)),
                    "timeout_s": timeout_left(a["name"]),
                },
            })
        if not self._authed():
            return self._reply(401, {"error": "unauthorized"})
        if self._bot_blocked():
            return
        if path in ("/stats", "/health"):
            self._reply(200, stats_json())
        elif path == "/chat":
            self._reply(200, chat_status())
        elif path == "/events":
            since = 0
            if "?" in self.path:
                for kv in self.path.split("?", 1)[1].split("&"):
                    if kv.startswith("since="):
                        try:
                            since = int(kv.split("=")[1])
                        except Exception:
                            pass
            self._reply(200, events_since(since))
        elif path == "/games":
            self._reply(200, {"games": _load_games()})
        elif path == "/extensions":
            self._reply(200, {"extensions": _load_extensions()})
        elif path == "/bans":
            self._reply(200, {"bans": bans_list()})
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
        elif path == "/block":
            self._reply(200, block_height())
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
        if self._bot_blocked():
            return
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
        elif path == "/gamechat":
            self._reply(200, {"ok": True, "result": set_game_chat(bool(data.get("enabled")))})
        elif path == "/chat/restrict":
            self._reply(200, {"ok": True, "result": chat_restrict(
                str(data.get("tag", "")), bool(data.get("blocked", True)))})
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
        elif path == "/games":
            self._reply(200, {"ok": True, "result": games_add(
                str(data.get("name", "")).strip(), str(data.get("kind", "")).strip(),
                str(data.get("url", "")).strip())})
        elif path == "/games/remove":
            self._reply(200, {"ok": True, "result": games_remove(str(data.get("name", "")).strip())})
        elif path == "/games/toggle":
            self._reply(200, {"ok": True, "result": games_toggle(
                str(data.get("name", "")).strip(), bool(data.get("enabled")))})
        elif path == "/extensions":
            self._reply(200, {"ok": True, "result": extensions_set(
                str(data.get("name", "")).strip(), bool(data.get("enabled")))})
        elif path == "/art":
            self._reply(200, {"ok": True, "result": art_mode_set(str(data.get("mode", "")))})
        elif path == "/torrent":
            self._reply(200, {"ok": True, "result": torrent_control(
                str(data.get("action", "status")), data.get("corpus_id"))})
        elif path == "/mute":
            self._reply(200, {"ok": True, "result": self._run(op_mute(
                str(data.get("player", "")), bool(data.get("on", True)), str(data.get("reason", ""))))})
        elif path == "/timeout":
            self._reply(200, {"ok": True, "result": self._run(op_timeout(
                str(data.get("player", "")), int(data.get("minutes", 5) or 5), str(data.get("reason", ""))))})
        elif path == "/ban":
            mins = data.get("minutes")
            self._reply(200, {"ok": True, "result": self._run(op_ban(
                str(data.get("player", "")), int(mins) if mins else None, str(data.get("reason", ""))))})
        elif path == "/unban":
            self._reply(200, {"ok": True, "result": self._run(op_unban(str(data.get("player", ""))))})
        elif path == "/social":
            self._reply(200, {"ok": True, "result": social_set(
                data.get("frens_url") if "frens_url" in data else None,
                data.get("matrix_url") if "matrix_url" in data else None)})
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
            if "mode" in data:
                _SITELINK["mode"] = "testing" if data.get("mode") == "testing" else "synced"
                # The toggle should DO something visible: testing points the node link at
                # this local instance; synced points it back at the production site.
                if not data.get("url"):
                    _SITELINK["url"] = (f"http://{ADMIN_HTTP_HOST}:{ADMIN_HTTP_PORT}/"
                                        if _SITELINK["mode"] == "testing" else _SITELINK["prod_url"])
                event("admin", f"node link → {_SITELINK['mode']} ({_SITELINK['url']})")
            if data.get("url"):
                _SITELINK["url"] = str(data.get("url"))
                if _SITELINK["mode"] == "synced":
                    _SITELINK["prod_url"] = _SITELINK["url"]
            if data.get("site"):
                _SITELINK["site"] = str(data.get("site"))
            self._reply(200, {"ok": True, "result": _SITELINK["mode"] + " — " + _SITELINK["url"]})
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
        push(p, c(GREY, chat_admin(arg)))
    elif sub == "reboot":
        push(p, c(RED, "rebooting the node…")); await op_shutdown("in-MUD operator reboot", reboot=True)
    elif sub == "shutdown":
        push(p, c(RED, "shutting the node down…")); await op_shutdown("in-MUD operator shutdown", reboot=False)
    else:
        push(p, c(GREY, "admin: stats | nodes | broadcast <m> | kick <n> | chat on|off | reboot | shutdown"))


# =============================================================================
# Boss encounters — animated question gates, defined entirely by the verse pack.
# =============================================================================
async def boss_open(p: Player, nid: str) -> None:
    npc = NPCS[nid]
    p.boss_pending = nid
    if npc.get("anim"):
        await animate(p, npc["anim"], npc["name"], RED, hold=1.3)
    focus_text(p, npc["name"], ["", "  " + npc["name"] + " rounds on you.", ""]
               + ["  " + l for l in _wrap(npc["question"], BOARD_W - 6)]
               + ["", "  (answer with:  answer <your words>)"], RED)


async def boss_judge(p: Player, ans: str) -> None:
    nid = p.boss_pending
    npc = NPCS[nid]
    if any(k in ans.lower() for k in npc["keys"]):
        p.boss_pending = None
        # Anti-farming: reward (XP + rune + energy) is granted ONCE — the first time you learn it.
        already = await asyncio.to_thread(STORE.has_certificate, p.name, npc["class"]["class_id"])
        p.pending_fx.append("victory")                 # cue the web client's boss-defeat effect
        if npc.get("defeat_anim"):
            await animate(p, npc["defeat_anim"], npc["name"] + " - defeated", GOLD, hold=1.3)
        if already:
            focus_text(p, "Victory", ["", "  You've already mastered this truth, fren."]
                       + npc.get("already_lines", []), GOLD)
            push(p, c(GREY, "already mastered — no farming"))
            return
        old_level = p.level
        res = await asyncio.to_thread(STORE.add_xp, p.name, npc["xp"]); p.xp, p.level = res["xp"], res["level"]
        p.energy = await asyncio.to_thread(STORE.adjust_energy, p.name, int(npc.get("energy_win", 20)))
        if p.level > old_level:
            p.pending_fx.append("levelup")
        push(p, c(GOLD, f"{npc.get('victory_line', npc['name'] + ' is defeated')}  (+{npc['xp']} xp)"))
        await etch_class_rune(p, npc["class"])
    else:
        miss = int(npc.get("energy_miss", -15))
        p.energy = await asyncio.to_thread(STORE.adjust_energy, p.name, miss)
        p.boss_pending = nid
        focus_text(p, npc["name"], ["", f"  {npc['name']} laughs and holds.  ({miss} ⚡)", ""]
                   + ["  " + l for l in _wrap(npc.get("fail_hint", "Try again:  answer <text>"), BOARD_W - 6)], RED)


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
        "  Earn xp from teachers and by defeating bosses.",
        f"  {hint_to(p.room, _npc_room('boss') or VERSE['start_room'], 'The boss')}.  See a fren:  examine <name>",
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
# Home rooms & the gallery — every fren gets their own room off the floor.
# Rename it, hang your runes, invite frens over; ordinals/art join the wall as
# the media rail lands (web clients render real images; terminals get ASCII).
# =============================================================================
async def _teleport(p: Player, room_id: str, depart: str, arrive: str) -> None:
    who = display_name(p)
    await broadcast_room(p.room, c(GREY, f"{who} {depart}"), exclude=p)
    p.room = room_id
    await asyncio.to_thread(STORE.save_player, p.name, p.room, p.inventory)
    await broadcast_room(p.room, c(GREY, f"{who} {arrive}"), exclude=p)
    focus_room(p)


async def go_home(p: Player) -> None:
    if is_home(p.room) and home_owner(p.room) == p.name:
        push(p, c(GREY, "you're already home, fren"))
        return
    await _teleport(p, home_id(p.name), "heads up to their quarters.", "arrives home.")
    push(p, c(MAG, "home sweet home. 💜  (rename room <name> · invite <fren> · gallery)"))


async def rename_room(p: Player, new_name: str) -> None:
    if not new_name:
        push(p, c(GREY, "usage:  rename room <new name>")); return
    await asyncio.to_thread(STORE.set_feature, home_id(p.name), "room_name", new_name[:40])
    push(p, c(GREEN, f"✓ your room is now '{new_name[:40]}'"))
    if is_home(p.room) and home_owner(p.room) == p.name:
        focus_room(p)


async def invite_fren(p: Player, name: str) -> None:
    name = name.strip().lstrip("@")
    if not name:
        push(p, c(GREY, "usage:  invite <fren>   (they can then:  visit " + p.name + ")")); return
    invites = await asyncio.to_thread(STORE.get_feature, home_id(p.name), "invites", [])
    if name.lower() not in [i.lower() for i in invites]:
        invites.append(name)
        await asyncio.to_thread(STORE.set_feature, home_id(p.name), "invites", invites)
    push(p, c(GREEN, f"✓ {name} may now visit your room"))
    for pl in PLAYERS.values():
        if pl.name.lower() == name.lower() or (pl.fren_tag or "").lower() == name.lower():
            push(pl, c(MAG, f"{display_name(p)} invited you over — try:  visit {p.name}"))
            try:
                await show(pl)
            except Exception:
                pass


async def visit_fren(p: Player, name: str) -> None:
    name = name.strip().lstrip("@")
    if not name:
        push(p, c(GREY, "usage:  visit <fren>")); return
    owner = await asyncio.to_thread(STORE.public_attributes, name)
    if not owner:
        push(p, c(GREY, f"no fren called '{name}' is known here")); return
    owner_name = owner["name"]
    if owner_name != p.name:
        invites = await asyncio.to_thread(STORE.get_feature, home_id(owner_name), "invites", [])
        allowed = {i.lower() for i in invites}
        if p.name.lower() not in allowed and (p.fren_tag or "").lower() not in allowed:
            push(p, c(GREY, f"{owner_name}'s door is closed — ask them to  invite {p.name}")); return
    await _teleport(p, home_id(owner_name), "steps away to visit a fren.", "drops in for a visit.")


async def show_gallery(p: Player) -> None:
    if not GALLERY:
        focus_text(p, "Gallery", ["", "  No pieces on display in this verse yet.",
                                  "", "  Verse packs ship gallery art — and your ordinals dock here soon."], AMBER)
        return
    lines = ["", "  On display:"]
    for i, piece in enumerate(GALLERY, 1):
        artist = piece.get("artist", "unknown")
        media = "  [media]" if piece.get("media") else ""
        lines.append(f"   {i}. {piece['title']}   — {artist}{media}")
    lines += ["", "  view <number>  to stand before a piece."]
    focus_text(p, "Gallery", lines, AMBER)


async def view_piece(p: Player, which: str) -> None:
    try:
        piece = GALLERY[int(which.strip()) - 1]
    except (ValueError, IndexError):
        push(p, c(GREY, "view which? try  gallery  for the list")); return
    art = list(piece.get("art", ["(no ascii rendition)"]))
    art += ["", f"'{piece['title']}' — {piece.get('artist', 'unknown')}"]
    lines = []
    if piece.get("media") and ART_MODE != "media":
        lines.append("  (full media is off on this node — ascii mode)")
    focus_text(p, piece["title"], lines, AMBER, media=piece.get("media"), art=art)


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


def _llm_npc(persona: str, text: str, mem: list[dict]) -> str:
    msgs = [{"role": "system", "content": persona or
             "You are a warm NPC in Pac's Arcade — a Socratic educator. Say 'fren', never 'friend'. "
             "Reply in 1-3 sentences and end with a probing question. Never lecture."}]
    for m in mem:
        msgs.append({"role": "assistant" if m["role"] == "game" else "user", "content": m["text"]})
    msgs.append({"role": "user", "content": text})
    return _chat(msgs, 140)


async def converse_npc(p: Player, nid: str, text: str) -> None:
    """Free-form chat with a verse NPC — run by the node's local AI with the player's
    recent memory (DB-2), so bots remember frens. Scripted fallback without a model."""
    npc = NPCS[nid]
    await asyncio.to_thread(STORE.add_memory, p.name, "player", text)
    focus_text(p, npc["name"], _npc_panel(npc, [f"…{npc['name']} considers…"]), MAG)
    await show(p)
    reply = ""
    if INFERENCE_BASE_URL and GEN_MODEL:
        mem = await asyncio.to_thread(STORE.recent_memory, p.name, 6)
        reply = await asyncio.get_event_loop().run_in_executor(None, _llm_npc, npc["persona"], text, mem)
    if not reply:
        reply = npc.get("fallback") or ("I trade in questions, not chit-chat, fren — but I'm listening. "
                                        "What's on your mind?")
    await asyncio.to_thread(STORE.add_memory, p.name, "game", reply)
    focus_text(p, npc["name"], _npc_panel(npc, _wrap('"' + reply.strip() + '"', BOARD_W - 6)), MAG)


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
    if a == "move" and act.get("dir"):
        await move(p, act["dir"]); return True
    if a == "talk":
        hit = npc_here(p, "socratic") or npc_here(p, "boss")
        if hit:
            nid, npc = hit
            await (boss_open(p, nid) if npc["kind"] == "boss" else trial_open(p, nid)); return True
    if a == "look":
        focus_room(p); return True
    if a == "pull":
        await pull(p, "lever"); return True
    if a == "challenge" and npc_here(p, "boss"):
        await boss_open(p, npc_here(p, "boss")[0]); return True
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
    await asyncio.to_thread(STORE.add_memory, p.name, "player", line)
    if any(low == g or low.startswith(g + " ") for g in GREETINGS):
        hit = npc_here(p, "socratic") or npc_here(p, "boss")
        if hit:
            nid, npc = hit
            await (boss_open(p, nid) if npc["kind"] == "boss" else trial_open(p, nid)); return
        push(p, c(GREY, "you say it to the empty room; the cabinets blink back")); return
    for d in DIRS:
        if d in low.split():
            await move(p, d); return
    if low in ("where am i", "look around", "explore", "wat", "what"):
        focus_room(p); return
    teacher = npc_here(p, "socratic")
    if teacher:                                # with a teacher, free text IS a question to them
        await converse_npc(p, teacher[0], line); return
    if INFERENCE_BASE_URL and GEN_MODEL:       # elsewhere, let the model map intent (only cost when needed)
        room = get_room(p.room)
        act = await asyncio.get_event_loop().run_in_executor(
            None, _llm_intent, room["title"], list(room["exits"]), room["npcs"], line)
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


RELAYS_FILE = os.environ.get("PA_RELAYS_FILE", os.path.join(DATA_DIR, "relays.json"))


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


# --- linked games (other front-ends into this pokenode — Luanti lands here) ----
GAMES_FILE = os.environ.get("PA_GAMES_FILE", os.path.join(DATA_DIR, "games.json"))
_BUILTIN_GAMES = [{"name": "POKEMUD", "kind": "mud", "url": "/play", "status": "live",
                   "enabled": True, "builtin": True}]


def _load_games() -> list:
    try:
        with open(GAMES_FILE) as f:
            extra = json.load(f).get("games", [])
    except Exception:
        extra = []
    return list(_BUILTIN_GAMES) + [g for g in extra if not g.get("builtin")]


def _save_games(games: list) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(GAMES_FILE)), exist_ok=True)
    with open(GAMES_FILE, "w") as f:
        json.dump({"games": [g for g in games if not g.get("builtin")]}, f, indent=2)


def games_add(name: str, kind: str, url: str) -> str:
    if not name:
        return "need a game name"
    if name.upper() in {g["name"].upper() for g in _BUILTIN_GAMES}:
        return f"'{name}' is built in"
    games = [g for g in _load_games() if g.get("name") != name]
    games.append({"name": name, "kind": kind or "game", "url": url, "status": "linked",
                  "enabled": True, "added_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
    _save_games(games)
    event("admin", f"linked game '{name}' ({kind or 'game'})")
    return f"linked '{name}'"


def games_remove(name: str) -> str:
    _save_games([g for g in _load_games() if g.get("name") != name])
    return f"unlinked '{name}'"


def games_toggle(name: str, enabled: bool) -> str:
    games = _load_games()
    for g in games:
        if g.get("name") == name and not g.get("builtin"):
            g["enabled"] = bool(enabled)
    _save_games(games)
    return f"'{name}' {'enabled' if enabled else 'disabled'}"


# --- extensions (owner-toggled add-ons; the pacBOT ops bot is the first) --------
EXT_FILE = os.environ.get("PA_EXTENSIONS_FILE", os.path.join(DATA_DIR, "extensions.json"))
_EXT_DEFAULTS = {
    "pacbot": {"enabled": False,
               "desc": "pacBOT ops bot — may read stats/events and act for the owner (see docs/BOT-EXTENSION.md)"},
}


def _load_extensions() -> dict:
    ext = {k: dict(v) for k, v in _EXT_DEFAULTS.items()}
    try:
        with open(EXT_FILE) as f:
            for k, v in json.load(f).get("extensions", {}).items():
                ext.setdefault(k, {})["enabled"] = bool(v.get("enabled"))
                if v.get("desc"):
                    ext[k]["desc"] = v["desc"]
    except Exception:
        pass
    return ext


def extensions_set(name: str, enabled: bool) -> str:
    name = name.lower().strip()
    ext = _load_extensions()
    if name not in ext:
        return f"unknown extension '{name}' (have: {', '.join(ext)})"
    ext[name]["enabled"] = bool(enabled)
    os.makedirs(os.path.dirname(os.path.abspath(EXT_FILE)), exist_ok=True)
    with open(EXT_FILE, "w") as f:
        json.dump({"extensions": ext}, f, indent=2)
    event("admin", f"extension '{name}' {'ON' if enabled else 'off'}")
    return f"extension '{name}' {'ON' if enabled else 'off'}"


def extension_enabled(name: str) -> bool:
    return bool(_load_extensions().get(name.lower().strip(), {}).get("enabled"))


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


_BLOCK_CACHE = {"t": 0.0, "height": None, "source": ""}


def block_height() -> dict:
    """Best-effort current Bitcoin block height for the console — local-first.
    Point PA_BITCOIN_REST_URL at your node's REST (bitcoind -rest=1), or PA_BITCOIN_RPC_URL
    (+ PA_BITCOIN_RPC_AUTH 'user:pass'), or set PA_BLOCK_HEIGHT for a fixed display. Cached 15s."""
    now = time.time()
    if now - _BLOCK_CACHE["t"] < 15 and _BLOCK_CACHE["height"] is not None:
        return {"height": _BLOCK_CACHE["height"], "source": _BLOCK_CACHE["source"]}
    height, source = _BLOCK_CACHE["height"], _BLOCK_CACHE["source"]   # keep last-known on error
    env, rest, rpc = (os.environ.get(k, "") for k in ("PA_BLOCK_HEIGHT", "PA_BITCOIN_REST_URL", "PA_BITCOIN_RPC_URL"))
    try:
        if env.strip().isdigit():
            height, source = int(env.strip()), "env"
        elif rest:
            with urllib.request.urlopen(rest.rstrip("/") + "/rest/chaininfo.json", timeout=2) as r:
                height, source = int(json.loads(r.read())["blocks"]), "bitcoin-rest"
        elif rpc:
            body = json.dumps({"jsonrpc": "1.0", "id": "poke", "method": "getblockcount", "params": []}).encode()
            req = urllib.request.Request(rpc, data=body, headers={"Content-Type": "text/plain"})
            auth = os.environ.get("PA_BITCOIN_RPC_AUTH", "")
            if auth:
                import base64
                req.add_header("Authorization", "Basic " + base64.b64encode(auth.encode()).decode())
            with urllib.request.urlopen(req, timeout=2) as r:
                height, source = int(json.loads(r.read())["result"]), "bitcoin-rpc"
    except Exception:
        pass
    if height is not None:
        _BLOCK_CACHE.update(t=now, height=height, source=source)
    return {"height": height, "source": source}


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
    event("admin", f"{pl.name} {'muted' if on else 'unmuted'}")
    return f"{pl.name} {'muted' if on else 'unmuted'}"


async def op_timeout(name: str, minutes: int, reason: str = "") -> str:
    w, pl = _find_player(name)
    target = (pl.name if pl else name).strip()
    if not target:
        return "usage: timeout <name> [minutes]"
    until = time.time() + max(1, int(minutes)) * 60
    _persist_timeout(target, until)                   # survives a rage-quit + rejoin
    if pl:
        pl.timeout_until = until
        push(pl, c(GOLD, f"TIMEOUT — {int(minutes)}:00. Your seat and progress are safe; chat re-opens at zero.")
             + (c(GREY, f"  ({reason})") if reason else ""))
        try:
            await show(pl)
        except Exception:
            pass
    event("admin", f"{target} timed out {int(minutes)}m")
    return f"{target} timed out {int(minutes)}m"


async def op_watch(name: str, on: bool) -> str:
    w, pl = _find_player(name)
    if not pl:
        return f"no player '{name}'"
    pl.watched = bool(on)
    return f"{'watching' if on else 'unwatched'} {pl.name}"


# --- persistent moderation: bans + timeouts survive reconnects and reboots ----
MOD_FILE = os.environ.get("PA_MODERATION_FILE", os.path.join(DATA_DIR, "moderation.json"))


def _load_mod() -> dict:
    try:
        with open(MOD_FILE) as f:
            return json.load(f)
    except Exception:
        return {"bans": {}, "timeouts": {}}


def _save_mod(d: dict) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(MOD_FILE)), exist_ok=True)
    with open(MOD_FILE, "w") as f:
        json.dump(d, f, indent=2)


def ban_info(name: str) -> "dict | None":
    """Active ban for a name (case-insensitive), or None. Expired bans self-clean."""
    d = _load_mod()
    b = d.get("bans", {}).get(name.strip().lower())
    if not b:
        return None
    if b.get("until", -1) != -1 and time.time() > b["until"]:
        d["bans"].pop(name.strip().lower(), None)
        _save_mod(d)
        return None
    return b


def timeout_left(name: str) -> int:
    d = _load_mod()
    until = d.get("timeouts", {}).get(name.strip().lower(), 0)
    return max(0, int(until - time.time()))


def _persist_timeout(name: str, until: float) -> None:
    d = _load_mod()
    d.setdefault("timeouts", {})[name.strip().lower()] = until
    _save_mod(d)


def _fmt_left(until: float) -> str:
    if until == -1:
        return "this bench has no timer — talk to the operator"
    return "the floor reopens in " + _fmt_dur(max(0, until - time.time()))


def ban_lines(b: dict) -> list[str]:
    lines = ["GAME OVER — you're benched from this arcade, fren."]
    if b.get("reason"):
        lines.append(f"Reason: {b['reason']}")
    lines += [_fmt_left(b.get("until", -1)).capitalize() + ".",
              "Hydrate. Take a stroll. The high score will wait. 💜"]
    return lines


async def send_gameover(pl: "Player", kind: str, lines: list[str]) -> None:
    """Branded removal message — same words on web and terminal — then the door."""
    try:
        if pl.web:
            await pl.send(json.dumps({"t": kind, "lines": lines}))
        else:
            await pl.send(CLEAR + c(RED, "\r\n  " + "\r\n  ".join(lines) + "\r\n"))
        pl.writer.close()
    except Exception:
        pass
    PLAYERS.pop(pl.writer, None)


async def op_ban(name: str, minutes: "int | None" = None, reason: str = "") -> str:
    w, pl = _find_player(name)
    target = (pl.name if pl else name).strip()
    if not target:
        return "usage: ban <name> [minutes] [reason]"
    until = -1 if not minutes else time.time() + max(1, int(minutes)) * 60
    d = _load_mod()
    d.setdefault("bans", {})[target.lower()] = {"until": until, "reason": reason,
                                                "at": time.time(), "by": "operator"}
    _save_mod(d)
    span = "permanently" if until == -1 else f"for {int(minutes)}m"
    event("admin", f"banned {target} {span}" + (f" ({reason})" if reason else ""))
    if pl:
        await send_gameover(pl, "banned", ban_lines(d["bans"][target.lower()]))
    return f"banned {target} {span}"


async def op_unban(name: str) -> str:
    d = _load_mod()
    if d.get("bans", {}).pop(name.strip().lower(), None) is None:
        return f"no ban on '{name}'"
    _save_mod(d)
    event("admin", f"unbanned {name}")
    return f"unbanned {name} — welcome them back, fren"


def bans_list() -> list[dict]:
    d = _load_mod()
    out = []
    for n, b in d.get("bans", {}).items():
        if b.get("until", -1) != -1 and time.time() > b["until"]:
            continue
        out.append({"name": n, "until": b.get("until", -1), "reason": b.get("reason", ""),
                    "left_s": (-1 if b.get("until", -1) == -1
                               else max(0, int(b["until"] - time.time())))})
    return out


# Course modules + knowledge QA are the Architect's/Warden's — stubbed until wired (see ROADMAP).
_QA_FLAGS: list = []
_MODULES = [
    {"lvl": 1, "code": "BTC101", "name": "Bitcoin Self-Custody", "path": "BITCOIN › CUSTODY",
     "prereq": "", "rune": "PACS•ARCADE•BTC101", "access": "OPEN"},
    {"lvl": 2, "code": "CONSENSUS", "name": "Bitcoin Consensus", "path": "BITCOIN › CONSENSUS",
     "prereq": "BTC101", "rune": "PACS•ARCADE•CONSENSUS", "access": "AFTER BTC101"},
]
_SITELINK = {"mode": "testing" if LOCAL_SITE_URL else "synced",
             "url": LOCAL_SITE_URL or "https://pacsarcade.org",
             "prod_url": "https://pacsarcade.org",
             "site": os.environ.get("PA_ORG_SITE", "pacsarcade.org")}


# --- command dispatch --------------------------------------------------------
DIRS = {"north", "south", "east", "west", "up", "down"}
DIR_ALIAS = {"n": "north", "s": "south", "e": "east", "w": "west", "u": "up", "d": "down"}


async def broadcast_room(room: str, log_line: str, exclude: "Player | None" = None,
                         chat: bool = False) -> None:
    """Room-wide line. `chat=True` marks player chatter — skipped for frens who muted it."""
    for w, pl in list(PLAYERS.items()):
        if pl.room == room and pl is not exclude:
            if chat and pl.chat_muted:
                continue
            push(pl, log_line)
            try:
                await show(pl)
            except Exception:
                pass


async def dispatch(p: Player, line: str) -> bool:
    line = line.strip()
    if line.startswith("/"):                  # '/home', '/fren invite <name>' — slash style works too
        line = line[1:].strip()
    verb, _, rest = line.partition(" ")
    verb = verb.lower()
    rest = rest.strip()
    p.idle_since = time.time()

    # Operator timeout: benched except for quit/look/help.
    if p.timeout_until > time.time() and verb not in ("quit", "exit", "q", "look", "l", "help", "?"):
        push(p, c(GOLD, f"you're benched — {int(p.timeout_until - time.time())}s left. seat + progress safe."))
        return True

    # While a question is pending, most input IS the answer — so "proof of work" is judged even
    # if it starts with a command word like 'i' (inventory). A few meta verbs still work mid-question.
    if (p.boss_pending or p.trial_pending) and verb not in (
            "quit", "exit", "q", "help", "?", "look", "l", "answer", "admin"):
        if p.boss_pending:
            await boss_judge(p, line.strip())
        else:
            await trial_judge(p, line.strip())
        return True

    if verb in ("quit", "exit", "q"):
        gained = p.xp - p.session_start_xp
        new_runes = len(p.certs) - p.session_start_runes
        lines = [
            VSTR["goodnight"].format(who=display_name(p)),
            "This session: +" + str(gained) + " xp" + (f", +{new_runes} rune(s)" if new_runes > 0 else "") + ".",
            f"You're Level {p.level} · {p.xp} xp · {len(p.certs)} rune(s).",
            VSTR["come_back"],
        ]
        if p.web:
            await p.send(json.dumps({"t": "bye", "lines": lines,
                                     "summary": {"xp": p.xp, "level": p.level, "runes": len(p.certs), "gained": gained}}))
        else:
            await p.send(CLEAR + c(MAG, "\r\n  " + "\r\n  ".join(lines) + "\r\n"))
        return False
    if verb in ("help", "?", "commands"):
        page = 2 if rest.strip().startswith("2") else 1
        show_help(p, page)
        if page == 1:
            push(p, c(GREY, "type naturally, fren — 'sup', 'go down', 'who is the boss' all work"))
    elif verb in ("look", "l"):
        focus_room(p)
    elif verb in ("go", "move", "walk"):
        await move(p, rest)
    elif verb in DIRS or verb in DIR_ALIAS:
        await move(p, DIR_ALIAS.get(verb, verb))
    elif verb == "talk":
        room_npcs = get_room(p.room)["npcs"]
        target = _match_npc(rest.lower(), room_npcs) or (room_npcs[0] if room_npcs else None)
        if target:
            npc = NPCS[target]
            await (boss_open(p, target) if npc["kind"] == "boss" else trial_open(p, target))
        else:
            push(p, c(GREY, "there's no one by that name here"))
    elif verb == "answer":
        if p.boss_pending:
            await boss_judge(p, rest)
        elif p.trial_pending:
            await trial_judge(p, rest)
        else:
            push(p, c(GREY, "nothing has asked you a question yet — try  talk  or  challenge"))
    elif verb == "ask":
        tgt, _, q = rest.partition(" ")
        room_npcs = get_room(p.room)["npcs"]
        target = _match_npc(tgt.lower(), room_npcs)
        teacher = npc_here(p, "socratic")
        if target and NPCS[target]["kind"] == "socratic":
            await converse_npc(p, target, q.strip() or "teach me something")
        elif teacher:
            await converse_npc(p, teacher[0], rest.strip() or "teach me something")
        else:
            rid = _npc_room("socratic")
            push(p, c(GREY, hint_to(p.room, rid, "a teacher") if rid else "no one here teaches — explore, fren"))
    elif verb == "pull":
        await pull(p, rest)
    elif verb == "link":
        await link_identity(p, rest)
    elif verb == "verify":
        await verify_code(p, rest)
    elif verb == "backup":
        await backup_onchain(p)
    elif verb in ("challenge", "fight", "battle"):
        boss = npc_here(p, "boss")
        if boss:
            await boss_open(p, boss[0])
        else:
            rid = _npc_room("boss")
            hint = hint_to(p.room, rid, get_room(rid)["title"]) if rid else "this verse has no boss yet"
            push(p, c(GREY, "nothing to challenge here — " + hint))
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
            if not GAME_CHAT:                             # node-wide kill switch
                push(p, c(GREY, "game chat is off on this node — the operator can turn it back on"))
            elif p.chat_muted:
                push(p, c(GREY, "you have game chat muted —  chat on  to speak"))
            elif p.muted or chat_blocked(p):              # operator moderation / @tag restriction
                push(p, c(GREEN, "you say: ") + c(BOLD, rest) + c(GREY, "  (muted — local only)"))
            else:
                push(p, c(GREEN, "you say: ") + c(BOLD, rest) + (c(GREY, "  (→ matrix)") if CHAT_MATRIX else ""))
                await broadcast_room(p.room, c(CYAN, f"{who} says: ") + c(BOLD, rest), exclude=p, chat=True)
                if CHAT_MATRIX:
                    asyncio.create_task(forward_chat_to_matrix(p.room, who, rest))
        else:
            push(p, c(GREY, "say what?"))
    elif verb == "chat":
        want = rest.lower().strip()
        if want in ("off", "mute", "0"):
            p.chat_muted = True
            await asyncio.to_thread(STORE.set_feature, "pref:" + p.name, "chat_off", True)
            push(p, c(GREY, "game chat muted for you — others' says won't reach you.  chat on  to undo"))
        elif want in ("on", "unmute", "1"):
            p.chat_muted = False
            await asyncio.to_thread(STORE.set_feature, "pref:" + p.name, "chat_off", False)
            push(p, c(GREEN, "game chat ON for you — welcome back to the floor, fren"))
        else:
            push(p, c(GREY, f"your game chat is {'muted' if p.chat_muted else 'on'} —  chat on|off"))
    elif verb in ("certs", "runes", "certificates"):
        await show_certs(p)
    elif verb in ("inventory", "inv", "i"):
        focus_text(p, "Inventory", ["", "  You carry:", ""] +
                   (["   · " + it for it in p.inventory] if p.inventory else ["   nothing but curiosity"]), GREEN)
    elif verb == "who":
        push(p, c(GREEN, f"online ({len(PLAYERS)}): ") + ", ".join((f"@{pl.fren_tag}" if pl.fren_tag else pl.name) for pl in PLAYERS.values()))
    elif verb == "home":
        await go_home(p)
    elif verb == "rename" and rest.lower().startswith("room"):
        await rename_room(p, rest[4:].strip())
    elif verb == "invite":
        await invite_fren(p, rest)
    elif verb == "visit":
        await visit_fren(p, rest)
    elif verb in ("next", "more") and p.focus and str(p.focus.get("title", "")).startswith("How to play"):
        show_help(p, p.help_page % HELP_PAGES + 1)
    elif verb == "fren":
        sub, _, arg = rest.partition(" ")
        sub, arg = sub.lower().strip(), arg.strip()
        if sub == "invite":
            await invite_fren(p, arg)
        elif sub == "visit":
            await visit_fren(p, arg)
        elif sub in ("add", "link"):
            await link_identity(p, "fren " + arg)
        else:
            push(p, c(GREY, "fren what?  /fren invite <name> · /fren visit <name> · /fren add <name>"))
    elif verb == "gallery":
        await show_gallery(p)
    elif verb == "view":
        await view_piece(p, rest)
    elif p.boss_pending:
        await boss_judge(p, line.strip())
    elif p.trial_pending:
        await trial_judge(p, line.strip())
    else:
        await interpret(p, line)          # the flexible path — heuristics, NPC chat, then the LLM
    return True


async def move(p: Player, direction: str) -> None:
    direction = DIR_ALIAS.get(direction.lower(), direction.lower())
    exits = get_room(p.room)["exits"]
    if direction in exits:
        who = f"@{p.fren_tag}" if p.fren_tag else p.name
        await broadcast_room(p.room, c(GREY, f"{who} heads {direction}."), exclude=p)
        p.room = exits[direction]
        await asyncio.to_thread(STORE.save_player, p.name, p.room, p.inventory)
        await broadcast_room(p.room, c(GREY, f"{who} arrives."), exclude=p)
        focus_room(p)
    elif len(exits) == 1:
        # One door out (home rooms, dead ends): any direction takes it, with a nudge —
        # so 'd' in your quarters walks you out instead of arguing about south vs down.
        only = next(iter(exits))
        push(p, c(GREY, f"one way out — {DIR_GLYPH[only]} {only} it is, fren"))
        await move(p, only)
    else:
        push(p, c(GREY, VSTR["cant_go"] + " — exits: "
                  + ", ".join(f"{DIR_GLYPH[d]} {d}" for d in exits)))


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


async def attract_intro(p: Player, reader: asyncio.StreamReader) -> "str | None":
    """The arcade boot + attract sequence (terminal clients). Any keypress skips ahead;
    if the player typed an actual word, it's returned to feed the name prompt."""
    pre: "str | None" = None
    skipped = False

    async def pause(delay: float) -> None:
        nonlocal pre, skipped
        if skipped:
            return
        try:
            raw = await asyncio.wait_for(reader.readline(), timeout=delay)
        except asyncio.TimeoutError:
            return
        if not raw and reader.at_eof():
            skipped = True
            return
        line = clean_line(raw)
        # 'insert coin' / 'coin' / 'start' / 'load' / 'run' mean "let me in", not "call me that"
        if line and line.lower() not in ("insert coin", "coin", "start", "play", "load", "run"):
            pre = line
        skipped = True

    await p.send(CLEAR + "\r\n\r\n")
    for label, status in BOOT_LINES:                  # a tiny CRT boot check
        if skipped:
            break
        await p.send("   " + c(GREY, "▓ " + label + " ") + c(GREEN, status) + "\r\n")
        await pause(0.45)
    await pause(0.5)
    if not skipped:                                   # the C64 load ritual 💾
        await p.send("\r\n")
        for text, hold in C64_LINES:
            if skipped:
                break
            await p.send("   " + c(CYAN, text) + "\r\n")
            await pause(hold)
    await pause(0.4)
    for col in SHIMMER:                               # the logo glimmers ✨
        if skipped:
            break
        await p.send(CLEAR + make_banner(col))
        await pause(0.16)
    # INSERT COIN — the attract screen HOLDS here: the coin blinks INSIDE the box while
    # hints slide across the bottom of the window. ENTER / 'run' / 'insert coin' advances;
    # ~3 min failsafe for idle sockets.
    msgs = [
        "a study buddy for your cyberdeck",
        "type  /help  for the controls",
        "type  /quit  to leave",
        VERSE.get("tagline", ""),
        "frens welcome 💜",
    ]
    reel = "   ···   ".join(m for m in msgs if m) + "   ···   "
    reel_w = banner_width() - 2
    tick = 0
    if skipped:                                       # typed through the boot: still show the marquee screen once
        await p.send(CLEAR + make_banner(coin="▶ INSERT COIN ◀") + "  " + c(GREY, reel[:reel_w]) + "\r\n")
        return pre
    await p.send(CLEAR)
    while not skipped and tick < 720:
        blink_on = tick % 4 < 2
        coin = "▶ INSERT COIN ◀" if blink_on else "▷ INSERT COIN ◁"
        coin_col = (BOLD + GOLD) if blink_on else GREY
        off = (tick * 2) % len(reel)
        window = (reel + reel)[off:off + reel_w]
        await p.send(HOME + make_banner(coin=coin, coin_col=coin_col)
                     + "  " + c(GREY, window) + "\x1b[K")
        await pause(0.25)
        tick += 1
    await p.send("\x1b[J")
    return pre


async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, web: bool = False) -> None:
    p = Player(writer)
    p.web = web
    PLAYERS[writer] = p
    pre_name: "str | None" = None
    try:
        if web:
            # The browser renders its own (magical) login; just hand it the node info + a name prompt.
            await p.send(json.dumps({"t": "hello", "node": os.environ.get("PA_NODE_NAME", "a POKE node"),
                                     "site": LOCAL_SITE_URL,
                                     "prompt": "By what name shall the arcade know you, fren?"}))
        else:
            await p.send(RESIZE)
            pre_name = await attract_intro(p, reader)
            if reader.at_eof():
                return
            await p.send(c(AMBER, "\nBy what name shall the arcade know you, fren? "))
        # --- name entry: reject command words as names (so no one is called "help"/"quit") ---
        for _ in range(4):
            if pre_name:                              # typed during the attract sequence
                name, pre_name = pre_name, None
            else:
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

        # --- moderation gate: banned frens don't get past the door ---
        ban = await asyncio.to_thread(ban_info, p.name)
        if ban:
            event("warn", f"{p.name} tried to join while banned")
            await send_gameover(p, "banned", ban_lines(ban))
            return
        left = await asyncio.to_thread(timeout_left, p.name)
        if left > 0:                                  # a timeout follows you back in
            p.timeout_until = time.time() + left
            push(p, c(GOLD, f"still benched — {left}s left. seat + progress safe, fren."))

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
        if p.room not in ROOMS and not is_home(p.room):   # saved in another verse's room
            p.room = VERSE["start_room"]
        p.certs = await asyncio.to_thread(STORE.list_certificates, p.name)
        p.chat_muted = bool(await asyncio.to_thread(STORE.get_feature, "pref:" + p.name, "chat_off", False))
        p.session_start_xp, p.session_start_runes = p.xp, len(p.certs)
        hello = f"@{p.fren_tag}" if p.fren_tag else p.name

        p.in_game = True
        if data["new"]:
            push(p, c(MAG, VSTR["welcome"].format(who=hello)))
            if frens_aware() and not p.fren_tag:
                focus_text(p, "Welcome to the arcade", [
                    "", f"  This node is connected to frens.earth ({FRENS_URL}).", "",
                    "  Claim your handle and bind it to your @fren account:", "",
                    "     link fren <yourname>", "",
                    "  Or just explore — type  help  or  look.", "",
                ], AMBER)
            else:
                focus_room(p)
            push(p, c(GREY, "psst — you have your own room here:  home   (invite frens over)"))
        else:
            # Welcome back with a summary + a nudge toward next goals (directions computed
            # from where the player actually is, so the hints are never wrong).
            t_rid, b_rid = _npc_room("socratic"), _npc_room("boss")
            hints = []
            if t_rid:
                hints.append(hint_to(p.room, t_rid, NPCS[get_room(t_rid)["npcs"][0]]["name"]))
            if b_rid:
                hints.append(hint_to(p.room, b_rid, "the boss"))
            rank = verses.rank_for(VERSE, p.level)
            focus_text(p, f"Welcome back, {hello}", [
                "",
                f"  Level {p.level}{(' · ' + rank) if rank else ''} · {p.xp} xp · "
                f"{len(p.certs)} rune(s) · energy {p.energy}/100",
                f"  Last seen in: {get_room(p.room)['title']}",
                "",
                "  Good to see you, fren. What would you like to work on next?",
                ("  " + "; ".join(hints) + " — or just  look  around.") if hints
                else "  Just  look  around, fren.",
                "",
                "  Your own room awaits:  home   (hang your runes · invite frens)",
                "",
            ], AMBER)
            push(p, c(MAG, VSTR["welcome_back"].format(who=hello)))
        await broadcast_room(p.room, c(GREY, f"{hello} steps in from the street."), exclude=p)
        event("join", f"{hello} stepped in ({'web' if web else 'terminal'})")
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
        if p.in_game:
            event("part", f"{who} left the arcade")
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
    try:
        SERVER = await asyncio.start_server(handle_client, MUD_HOST, MUD_PORT)
        ws_server = await asyncio.start_server(_ws_client, MUD_HOST, MUD_WS_PORT)
    except OSError as e:
        print(f"! POKEMUD couldn't bind {MUD_HOST}:{MUD_PORT} — another node is already running "
              f"on this box ({e.strerror or e}).")
        print("    find it :  netstat -ano | findstr :4000      then:  taskkill /PID <pid> /F")
        print("    or run a second node on its own ports:")
        print("               PA_MUD_PORT=4100 PA_MUD_ADMIN_PORT=4101 PA_MUD_WS_PORT=4102  python services/mud/server.py")
        return
    http_srv = _start_admin_http()

    # --- the startup box: CLOSED borders, every row cropped + padded to one width ---
    BW = 78                       # outer width
    IN = BW - 4                   # inner content width

    def crow(content: str) -> str:
        cropped = ansi_crop(content, IN)
        pad = " " * max(0, IN - dwidth(_ANSI.sub("", cropped)))
        return c(MAG, "║ ") + cropped + pad + c(MAG, " ║")

    def row(label: str, value: str, vcol: str = "", note: str = "") -> str:
        return crow(c(GREY, f"{label:<13}") + (c(vcol, value) if vcol else value)
                    + (c(GREY, note) if note else ""))

    store_disp = str(store_where)
    if len(store_disp) > IN - 22:                 # long path: keep the tail that matters
        store_disp = "…" + store_disp[-(IN - 23):]
    tok_note = "  (set PA_ADMIN_TOKEN to pin)" if ADMIN_TOKEN_GENERATED else ""
    top = c(MAG, "╔" + "═" * (BW - 2) + "╗")
    bar = c(MAG, "╠" + "═" * (BW - 2) + "╣")
    bot = c(MAG, "╚" + "═" * (BW - 2) + "╝")
    lines = [
        top,
        crow(c(BOLD + GOLD, "PAC'S ARCADE · POKEMUD") + c(GREY, "  ·  Proof of Knowledge Engine  💜")),
        crow(c(GREY, "verse ") + c(BOLD + AMBER, WORLD) + c(GREY, "  ·  oracle: " + oracle)),
        bar,
        row("telnet", f"{MUD_HOST}:{MUD_PORT}", GREEN, "   (python services/mud/play.py)"),
        row("browser", f"http://{ADMIN_HTTP_HOST}:{ADMIN_HTTP_PORT}/play", GREEN,
            f"   (ws bridge :{MUD_WS_PORT})"),
        row("web console", f"http://{ADMIN_HTTP_HOST}:{ADMIN_HTTP_PORT}/" if http_srv else "not running", CYAN),
        row("admin token", ADMIN_TOKEN, BOLD + GOLD, f"   (in-MUD: 'admin {ADMIN_TOKEN}')" + tok_note),
        bar,
        row("store", f"{backend} @ {store_disp}"),
        row("frens.earth", ("connected — " + FRENS_URL) if frens_aware() else "standalone", "",
            "" if frens_aware() else "  (set PA_FRENS_URL to connect)"),
        row("game chat", "ON" if GAME_CHAT else "OFF", GREEN if GAME_CHAT else RED,
            "   (chat on|off · chat block <@tag>)"),
        row("matrix chat", "ON" if CHAT_MATRIX else "off", GREEN if CHAT_MATRIX else GREY,
            "" if CHAT_MATRIX else "  (enable:  chat matrix on)"),
        row("demo mode", "ON — practice runes only" if DEMO_MODE else "off", GOLD if DEMO_MODE else GREY,
            "  (PA_DEMO_MODE=off after audit)" if DEMO_MODE else ""),
    ]
    if LOCAL_SITE_URL:
        lines.append(row("arcade site", LOCAL_SITE_URL, CYAN))
    lines += [
        row("console", "type 'help' here for operator commands"),
        bot,
    ]
    print("\n".join(lines) if VT_TTY else "\n".join(_ANSI.sub("", ln) for ln in lines), flush=True)

    _start_console(LOOP)
    ticker = asyncio.create_task(_status_ticker())
    sampler = asyncio.create_task(_metrics_sampler())      # feeds the console's CPU/MEM/NET histograms

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
        print("\n▓ POKEMUD rebooting…")
        os.execv(sys.executable, [sys.executable] + sys.argv)
    else:
        print("\n▓ POKEMUD is going offline. GG's, fren. 💜")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n▓ POKEMUD is going offline. GG's, fren. 💜")
