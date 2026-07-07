# DESIGN GUIDE — the POKE operator console (and web game) 🎨

This is a design guide for theming the **POKE web surfaces** with the Pac's Arcade brand — so the
server admin console, the browser game, and pacsarcade.org feel like **one product**. This is a
product of Pac's Arcade; branding is the point.

Two self-contained pages, one design language:
- **`services/mud/admin.html`** — the operator **console** (served at `:4001/`).
- **`services/mud/webclient.html`** — the browser **game** client (served at `:4001/play`).

Both are single files with **no external assets** (offline-first — no CDN, no web fonts from the
network). So theming = editing inlined CSS. Keep it that way: inline the arcade-ui tokens.

---

## 1. The theming seam: CSS custom properties

Every color lives in a `:root { … }` block at the top of each file. **Retheme by overriding these —
you should almost never touch the markup.** Drop the **@pacsarcade/arcade-ui design tokens** in here
and both pages inherit the brand.

```css
:root{
  /* surfaces */
  --bg:#05060a;      /* page background        → arcade-ui: color.bg.base       */
  --panel:#0b0e16;   /* card / input surface   → arcade-ui: color.bg.raised     */
  --line:#1b2233;    /* borders / dividers     → arcade-ui: color.border.subtle */
  --ink:#cdd6ea;     /* body text              → arcade-ui: color.fg.default    */
  --dim:#6b7690;     /* muted text             → arcade-ui: color.fg.muted      */
  /* brand accents (the arcade palette) */
  --magenta:#ff35c8; /* primary / brand        → arcade-ui: color.brand.primary */
  --amber:#ffbe3c;   /* highlight / links      → arcade-ui: color.brand.amber   */
  --cyan:#39e6ff;    /* interactive / doors    → arcade-ui: color.brand.cyan    */
  --green:#39ff9e;   /* success / room         → arcade-ui: color.brand.green   */
  --gold:#ffd24a;    /* reward / runes         → arcade-ui: color.brand.gold    */
  --red:#ff5a5a;     /* danger / boss          → arcade-ui: color.brand.red     */
  --accent:var(--green);   /* per-view accent (set at runtime by screen color) */
}
```

**To apply the brand:** paste your arcade-ui token values into these variables in *both* files.
That's the whole theme. (If arcade-ui ships a font, self-host it as a base64 `@font-face` inline —
don't `<link>` a CDN.)

### Semantic color roles (keep these meanings stable)
| Role | Var | Where |
|------|-----|-------|
| Brand / primary action | `--magenta` | buttons, brand mark, focus ring |
| Links / highlights | `--amber` | header links, labels |
| Interactive / navigation | `--cyan` | door chips, exits, toggles |
| Success / a room | `--green` | room panels, healthy states |
| Reward / a rune | `--gold` | rune cards, level-up, etch glow |
| Danger / a boss | `--red` | boss panels, shutdown, kick |

The game panel's border/glow uses `--accent`, which the client sets **per screen** from the server's
`color` field (room=green, oracle=magenta, boss=red, reward=gold). Keep that mapping — it's how the
world signals mood.

---

## 2. Structure (what to skin, not rebuild)

### Console (`admin.html`)
- **Header**: brand mark + "Play POKEMUD" + local-arcade link + connection dot + sign-out.
- **Widget grid** (responsive cards), each a labeled panel:
  Node · Players (now with **world** + **client** columns) · Knowledge Swarm · **System** (CPU/mem
  grid) · **Knowledge Relays** · **Torrent** · Controls (broadcast/kick/chat/reboot/shutdown).
- **Token gate**: first-run screen; the token is bootstrap only — nostr sign-in is roadmapped.

### Game (`webclient.html`)
- **Login**: PAC'S ARCADE / presents / **P O K E M U D** / Proof of Knowledge Engine + name field.
  This is the **login-experience overhaul** surface — the glimmer, boot sequence, and sound live here.
- **HUD**: level, xp bar, runes, energy bar — real UI elements.
- **Panel**: the color-themed game window (title + body).
- **Door chips**: clickable exits (`▲ north … ↓ down`).
- **Effects**: `.fx-etch` (gold glow), `.fx-victory` (shake), level-up toast. Add more here — these
  are cued by the server's `fx` field.
- **End screen**: goodnight + session summary + "play again" / back-to-arcade.

Reusable classes to theme: `.panel`, `.chip`, `.bar`, `.door`, `.hud`, `#toast`, `.ghost-btn`,
`.pill`, `.meter`, `.ctl`.

---

## 3. Recommended arcade-ui mapping

- Swap the token block (§1) for arcade-ui tokens → instant brand match on both pages.
- Where arcade-ui defines components (buttons, cards, pills, meters), mirror their **class names +
  radius/spacing/shadow tokens** so a designer can lift markup between the site and these pages.
- Keep the **CRT layer** (scanlines + vignette) as an arcade signature, but drive its intensity from
  a token (`--crt:0..1`) so it can be dialed per surface.
- One brand, one product: the console, the game, and pacsarcade.org should share the palette, the
  radius, the type scale, and the magenta focus ring.

## 4. The JSON contract (so design never breaks the server)
The game client renders whatever the server's `screen_model` sends — `{t, room, who, hud, title,
color, body[], exits[], log[], fx[]}` — so **you can restyle freely without touching server code**,
as long as you keep reading those fields. New effects = new `fx` cues (ask for a server one-liner).

Bring the brand. We'll keep the contract. 💜
