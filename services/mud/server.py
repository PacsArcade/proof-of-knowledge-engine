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
FRENS_URL = os.environ.get("PA_FRENS_URL", "")   # empty => this node is standalone


def frens_aware() -> bool:
    """True when this node is wired to the frens.earth verse (so we walk users through linking)."""
    return bool(FRENS_URL)


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
def make_banner() -> str:
    lines = [
        "",
        "PAC'S  ARCADE   presents",
        "",
        "◆  P . O . K . E .  ◆",
        "the Proof of Knowledge Engine",
        "",
        "play to learn  ·  type  help  ·  quit  to leave",
        "",
    ]
    width = max(len(l) for l in lines) + 8
    out = [c(MAG, "╔" + "═" * width + "╗")]
    for i, ln in enumerate(lines):
        col = BOLD + GOLD if "P . O . K . E" in ln else (BOLD + AMBER if "PAC'S" in ln else GREY)
        out.append(c(MAG, "║") + c(col, ln.center(width)) + c(MAG, "║"))
    out.append(c(MAG, "╚" + "═" * width + "╝"))
    return "\n" + "\n".join(out) + "\n" + c(GREY, "  Welcome, fren. 💜") + "\n"


BANNER = make_banner()

HELP_LINES = [
    "How to play:",
    "",
    "  look (l)              look around the room",
    "  north/south/east/west go through a door  (also n/s/e/w)",
    "  talk oracle           speak with the Oracle (it asks; you answer)",
    "  answer <text>         answer the Oracle   ·   ask oracle <q>",
    "  pull lever            operate a feature in the room",
    "  link fren <name>      claim your @fren + get a code to link it",
    "  verify <code>         confirm your @fren from frens.earth",
    "  backup                anchor your progress + runes on-chain",
    "  profile · certs · inventory · who · say <msg>",
    "",
    "  Doors are the gaps in the frame:  up / down / left / right arrows.",
    "  The Oracle trades understanding for a soulbound rune.",
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
}

ROOMS = {
    "entrance": {
        "title": "The Arcade Entrance",
        "desc": ("CRT cabinets hum in the dark, throwing blue light across the carpet. A neon sign "
                 "buzzes: PAC'S ARCADE — KNOWLEDGE IS THE HIGH SCORE. A worn token-slot glows, waiting."),
        "exits": {"north": "alcove", "east": "vault"},
        "npcs": [],
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
RUNE_ANIM = [
    ["", "", "            .   *   .", "         *    ( )    *", "            '   |   '",
     "            the die is cut…", "", ""],
    ["", "", "          * .    |    . *", "        (    \\   |   /    )", "          * '  \\ | /  ' *",
     "            the rune takes form…", "", ""],
    ["", "", "              \\   |   /", "            ——   ✦   ——", "              /   |   \\",
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
        self.oracle_pending = False
        self.focus: dict | None = None     # the window's current panel {title, lines, color}
        self.log: list[str] = []           # message-log strip (transient lines)
        self.connected_at = time.time()
        self.idle_since = time.time()
        self.is_admin = False
        self.in_game = False               # False until past the name prompt

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
        lines.append("Here: " + ", ".join(n.title() for n in room["npcs"]) + "   (try 'talk oracle')")
    others = [pl.name for w, pl in PLAYERS.items() if pl.room == p.room and pl is not p]
    if others:
        lines.append("Also here: " + ", ".join(others))
    p.focus = {"title": room["title"], "lines": lines, "color": GREEN}


def focus_text(p: Player, title: str, lines: list[str], color: str = GREEN) -> None:
    p.focus = {"title": title, "lines": list(lines), "color": color}


def push(p: Player, line: str) -> None:
    p.log.append(line)
    p.log = p.log[-LOG_H:]


def _frame(title: str, body: list[str], exits: dict, color: str) -> list[str]:
    W = BOARD_W
    rows = list(body)[:BODY_H]
    while len(rows) < BODY_H:
        rows.append("")
    mid = BODY_H // 2
    top = list("═" * W)
    sign = f"╡ {title} ╞"
    for i, ch in enumerate(sign):
        if 3 + i < W:
            top[3 + i] = ch
    if "north" in exits:
        dp = W * 3 // 4
        top[dp - 1:dp + 2] = list(" ▲ ")
    out = [c(MAG, "╔") + c(MAG, "".join(top)) + c(MAG, "╗")]
    for i, line in enumerate(rows):
        left = c(CYAN, "◄") if (i == mid and "west" in exits) else c(MAG, "║")
        right = c(CYAN, "►") if (i == mid and "east" in exits) else c(MAG, "║")
        out.append(left + " " + c(color, line[:W - 2].ljust(W - 2)) + " " + right)
    bot = list("═" * W)
    if "south" in exits:
        dp = W // 2
        bot[dp - 1:dp + 2] = list(" ▼ ")
    out.append(c(MAG, "╚") + c(MAG, "".join(bot)) + c(MAG, "╝"))
    return out


def render_screen(p: Player) -> str:
    room = ROOMS[p.room]
    f = p.focus or {"title": room["title"], "lines": [], "color": GREEN}
    who = f"@{p.fren_tag}" if p.fren_tag else p.name
    header = c(BOLD + MAG, "  PAC'S ARCADE · P.O.K.E.") + c(GREY, f"      {who} · {room['title']}")
    frame = _frame(f["title"], f["lines"], room["exits"], f.get("color", GREEN))
    log = list(p.log)[-LOG_H:]
    log = [""] * (LOG_H - len(log)) + log            # bottom-align the log
    parts = [header, ""] + frame + ["", c(GREY, "  ── messages ──")]
    parts += ["  " + l for l in log]
    parts += ["", c(AMBER, f"  {who} ") + c(GREY, "» ")]
    out = HOME
    for ln in parts[:-1]:
        out += ln + "\x1b[K\r\n"
    out += parts[-1] + "\x1b[K\x1b[J"                # prompt; clear anything below
    return out


async def show(p: Player) -> None:
    if p.in_game:
        await p.send(render_screen(p))


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
        "  🎓  " + cert["rune_name"],
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
    await animate(p, RUNE_ANIM, "Etching a rune…", GOLD, hold=0.6)
    focus_text(p, "Soulbound Class Rune", cert_card_lines(cert), GOLD)
    push(p, c(GOLD, f"🎓 etched {spec['rune']}"))


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
    payload = json.dumps({"fren": p.fren_tag, "wallet": p.wallet, "nostr": p.nostr, "space": p.space,
                          "runes": [x["rune_name"] for x in p.certs]}, sort_keys=True)
    digest = hashlib.sha256(payload.encode()).hexdigest()
    txid = "bcrt1q" + digest[:16]
    focus_text(p, "On-chain backup", [
        "",
        "  Your progress is committed to the chain (regtest · mock):",
        "",
        f"    attestation : {digest[:40]}…",
        f"    txid        : {txid}",
        f"    covers      : @{p.fren_tag or '—'} · {len(p.certs)} rune(s) · wallet {p.wallet[:14]}…",
        "",
        "  In production this writes an OP_RETURN via bitcoin-bridge, so your",
        "  runes + identity survive a lost device. Recover with your @fren. 💜",
    ], GOLD)
    push(p, c(GOLD, f"⛓ backup anchored: {txid}"))


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
        lines.append(f"  🎓 {cert['rune_name']}  — {cert['title']}")
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

_ADMIN_HTML = os.path.join(os.path.dirname(os.path.abspath(__file__)), "admin.html")


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

    def _serve_page(self) -> None:
        try:
            with open(_ADMIN_HTML, "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except FileNotFoundError:
            self._reply(404, {"error": "admin.html not found"})

    def _run(self, coro, timeout: float = 4.0):
        return asyncio.run_coroutine_threadsafe(coro, LOOP).result(timeout=timeout)

    def do_GET(self) -> None:
        path = self.path.split("?")[0].rstrip("/")
        if path in ("", "/admin", "/index.html"):      # the dashboard page loads without a token
            return self._serve_page()
        if not self._authed():
            return self._reply(401, {"error": "unauthorized"})
        if path in ("/stats", "/health"):
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

    if verb in ("quit", "exit", "q"):
        await p.send(CLEAR + c(MAG, "The cabinets dim. Come back soon, fren. 💜\r\n"))
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
        else:
            push(p, c(GREY, "there's no one by that name here"))
    elif verb == "answer":
        if p.oracle_pending:
            await oracle_judge(p, rest)
        else:
            push(p, c(GREY, "the Oracle hasn't asked anything yet — try  talk oracle"))
    elif verb == "ask":
        tgt, _, q = rest.partition(" ")
        if tgt.lower() == "oracle" and "oracle" in ROOMS[p.room]["npcs"]:
            await oracle_freeform(p, q.strip() or "teach me something about bitcoin")
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
    elif verb in ("profile", "whoami", "me"):
        await show_profile(p)
    elif verb == "admin":
        await admin_command(p, rest)
    elif verb == "say":
        if rest:
            who = f"@{p.fren_tag}" if p.fren_tag else p.name
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
    elif p.oracle_pending:
        await oracle_judge(p, line.strip())
    else:
        push(p, c(GREY, f"you aren't sure how to '{verb}', fren — try  help"))
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


async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    p = Player(writer)
    PLAYERS[writer] = p
    try:
        await p.send(RESIZE + CLEAR + BANNER)
        await p.send(c(AMBER, "\nBy what name shall the arcade know you, fren? "))
        raw = await reader.readline()
        name = clean_line(raw)
        if name:
            p.name = name[:24]
        data = await asyncio.to_thread(STORE.get_or_create_player, p.name)
        p.room, p.inventory, p.wallet = data["room"], data["inventory"], data["wallet"]
        p.nostr, p.space, p.fren_tag = data["nostr"], data["space"], data["fren_tag"]
        p.certs = await asyncio.to_thread(STORE.list_certificates, p.name)
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
            note = f" You carry {len(p.certs)} rune(s)." if p.certs else ""
            push(p, c(MAG, f"Welcome back, {hello}.{note} Your progress was kept. 💜"))
            focus_room(p)
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


async def main() -> None:
    global SERVER, LOOP
    LOOP = asyncio.get_running_loop()
    backend = type(STORE).__name__
    store_where = getattr(STORE, "path", "postgres DB-2")
    oracle = "local LLM" if (INFERENCE_BASE_URL and GEN_MODEL) else "scripted pacbot fallback"
    SERVER = await asyncio.start_server(handle_client, MUD_HOST, MUD_PORT)
    print(f"▓ Pac's Arcade · P.O.K.E. MUD on {MUD_HOST}:{MUD_PORT}  [persisted via {backend} @ {store_where}, Oracle: {oracle}] 💜")
    print(f"  Connect:  python services/mud/play.py    (or: telnet {MUD_HOST} {MUD_PORT})")
    http_srv = _start_admin_http()
    _start_console(LOOP)
    ticker = asyncio.create_task(_status_ticker())
    tok_note = "  (auto-generated; set PA_ADMIN_TOKEN to pin it)" if ADMIN_TOKEN_GENERATED else ""
    print("  Operator console: type 'help' here.")
    print(f"    admin token : {ADMIN_TOKEN}{tok_note}   (in-MUD: 'admin {ADMIN_TOKEN}')")
    if http_srv:
        print(f"    web console : http://{ADMIN_HTTP_HOST}:{ADMIN_HTTP_PORT}/   "
              "(open in a browser, paste the admin token)")
    print(f"    frens.earth : {'connected — ' + FRENS_URL if frens_aware() else 'standalone (set PA_FRENS_URL to connect)'}")
    print(f"    matrix chat : {'ON' if CHAT_MATRIX else 'off (default) — enable with  admin chat on'}")

    try:
        async with SERVER:
            await SHUTDOWN.wait()
    finally:
        ticker.cancel()
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
        print("▓ rebooting P.O.K.E. …")
        os.execv(sys.executable, [sys.executable] + sys.argv)
    else:
        print("▓ P.O.K.E. stopped. GG, fren. 💜")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n▓ MUD shutting down. GG, fren. 💜")
