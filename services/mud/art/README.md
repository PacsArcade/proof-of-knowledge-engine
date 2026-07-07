# Boss & lesson ASCII art 🎨👾

The MUD has a frame-animation primitive — `animate(p, frames, title, color, hold)` in
`services/mud/server.py` — that plays a list of ASCII frames **inside the persistent window**.
It's how bosses move and lessons come alive. The rune-etch effect (`RUNE_ANIM`) is the first
demo; drop more frame sets here and wire them to rooms/exams.

## Frame format

A "frame" is a list of plain strings (no ANSI — the window colors them). Keep frames within the
board interior (**≤ 68 cols wide, ≤ 12 rows tall**) so they fit the window. Example:

```python
CALCULUS_GOLEM = [
    ["", "     ▟█▙  ▟█▙", "    ◄ ◉  ◉ ►   the Calculus Golem stirs…", "     ▜█▛  ▜█▛", ""],
    ["", "     ▟█▙  ▟█▙", "    ◄ ◉  ◉ ►   \"Solve me, or don't pass.\"", "     ▜█▛▟██▙▜█▛", ""],
]
# then, in a room/exam handler:
await animate(p, CALCULUS_GOLEM, "The Calculus Golem", RED, hold=0.4)
```

Store bigger/animated bosses as `boss_name.json` here — a list of frames — and a small loader
can read + play them.

## Generating frames from images/video

`tplay` (https://github.com/maxcurzi/tplay) is a lovely terminal ASCII player, but it renders
only to a **live terminal** — it doesn't export frames or pipe to stdout, so it can't feed the
MUD's socket directly. Use it to *preview*. To actually **generate frames** you want a
stdout-capable converter:

- **Images → ASCII** (a single boss pose):
  - `chafa --format symbols --size 68x12 boss.png` (great quality, color or mono)
  - `jp2a --width=68 boss.png` · or `ascii-image-converter -d 68,12 boss.png`
- **Video / GIF → frames** (an animated boss): split with ffmpeg, convert each, collect:
  ```bash
  ffmpeg -i golem.gif -vf fps=6 frames/%03d.png
  for f in frames/*.png; do chafa --format symbols --size 68x12 "$f"; echo "---FRAME---"; done > golem.txt
  ```
  then load `golem.txt` (split on `---FRAME---`) into a frame list.
- **`asciify-engine`** (the repo you cloned) is a **browser/canvas** engine (image/video → ASCII
  on an HTML canvas). It's ideal for the **web** front-ends (and the web console's flair), not the
  terminal MUD — reach for `chafa`/`ffmpeg` for MUD frames.

## Design notes

- Keep frames plain (uniform color per animation via the `color` arg); the window handles the box.
- Short animations (3–6 frames, `hold` 0.3–0.6s) read best over a socket — long ones cost bandwidth.
- Bosses are lessons: pair a boss with an Oracle question or an exam gate. A "final exam" boss that
  drops a seed-loot fragment on a correct answer is the intended arc (see `docs/SECURITY.md`).
