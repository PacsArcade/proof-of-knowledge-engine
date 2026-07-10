#!/usr/bin/env python3
"""Seed the merge-review findings into a POKE node's Duty Roster as real tickets,
so the frens can claim/resolve/vouch them in the SCAR admin panel.

Usage:  PA_ADMIN_URL=http://127.0.0.1:4001 PA_ADMIN_TOKEN=... python seed-review-tickets.py
Idempotent: each ticket carries a dedup_key, so re-running won't duplicate.
"""
import json, os, urllib.request, urllib.error

BASE = os.environ.get("PA_ADMIN_URL", "http://127.0.0.1:4001").rstrip("/")
TOK = os.environ.get("PA_ADMIN_TOKEN", "fleetdemo")
SEV = {"high": "high", "medium": "normal", "low": "low"}   # review sev -> roster sev

# review sev is folded into severity; kind maps straight to the ITIL roster kinds.
FINDINGS = [
    ("PRB-01", "problem", "medium", "Profile: arcade stats fetched every hit but rendered owner-only",
     "getPokeProfile() runs for every request, but PokeArcadeCard only mounts in the owner branch, so public/QR/supporter views never see it yet still pay the node round-trip. Surface it in the public view or gate the fetch to owners.",
     "Open /u/<tag> signed out: no ARCADE STATS card; a breakpoint in getPokeProfile still fires.",
     "src/app/u/[handle]/page.tsx:76-79 · components/FrenProfile.tsx:694"),
    ("INC-02", "incident", "medium", "Profile: malformed 200 from the node crashes the whole profile",
     "getPokeProfile casts JSON to PokeProfile without checking name/level/xp/runes/world/verse. A 200 missing a field throws a TypeError during card render and takes down the whole profile, contradicting the never-a-throw contract.",
     "Point POKE_NODE_URL at a stub returning only {fren, moderation}; owner profile crashes instead of dropping the card.",
     "src/lib/poke.ts:77-83 · components/PokeArcadeCard.tsx:75,105"),
    ("PRB-03", "problem", "medium", "Console: legacy section padding bleeds into the NEXT LEVEL box",
     "PR#9 removed the legacy header rule but left section{padding:5rem 0}. Every profile section neutralizes it except the WHAT-CAN-NOSTR-DO cabinet, which inherits ~80px of dead band above/below.",
     "Owner console: inspect NEXT LEVEL box, computed padding 80px 0, visible dead space inside the neon border.",
     "src/app/globals.css:220-223 · components/FrenProfile.tsx:912"),
    ("CHG-04", "change", "medium", "A11y: pulse-neon animations ignore prefers-reduced-motion",
     "The always-on pulse-neon blinkers (online dot, ANCHOR-PENDING chip, CERTS NEXT tile, Matrix key banner) keep animating under reduced-motion; the kit reduced-motion query only disables matrix-col.",
     "OS reduce-motion on, load a pending-anchor profile: chip and dot still pulse; orbee correctly does not.",
     "PokeArcadeCard.tsx:68 · FrenProfile.tsx:500,834,1093 · MatrixDoor.tsx:98"),
    ("CHG-05", "change", "low", "A11y: avatar images use empty alt, invisible to screen readers",
     "The kind-0 identity picture renders with empty alt (decorative), so a screen-reader user gets nothing identifying whose profile it is.",
     "axe/VoiceOver on a profile with a nostr picture: avatar announces nothing; expected alt like '<name> avatar'.",
     "components/FrenProfile.tsx:344-347,449-451,838-843"),
    ("PRB-06", "problem", "low", "Profile: pacBOT answer doesn't appear until reload",
     "After a successful sign-and-post the card shows ON THE RECORD but pacbotAnswers is never updated, so the note is absent until reload. pushTagName does this right with applyLocal; apply the same optimistic pattern.",
     "As owner, answer a prompt: toast shows but the answer tile doesn't render until reload.",
     "components/FrenProfile.tsx:222-224 · hooks/usePacbotAsks.ts"),
    ("PRB-07", "problem", "low", "SEO: metadata claims unclaimed/reserved tags are registered and verified",
     "generateMetadata builds title/description from the parsed tag before the getEntry/reserved checks, so an unclaimed (GAME OVER) or reserved tag still ships 'registered on the board: verified on nostr'.",
     "curl /u/some-unclaimed-tag | grep title/description: claims registration though the body is GAME OVER.",
     "src/app/u/[handle]/page.tsx:38-51"),
    ("CHG-08", "change", "low", "A11y: decorative glyphs read aloud as text",
     "Pictographic glyphs (key, cert tiles, BENCHED, TIMEOUT) are announced literally by screen readers, adding noise; adjacent text already carries the meaning, so mark them aria-hidden.",
     "VoiceOver over CERTS tiles / BENCHED chip: the leading symbol is spoken before the label.",
     "FrenProfile.tsx:808,1094 · PokeArcadeCard.tsx:122,139"),
]

def post(path, body):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode("utf-8"),
        headers={"X-POKE-Admin-Token": TOK, "Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))

print(f"seeding {len(FINDINGS)} review tickets -> {BASE}")
for code, kind, sev, title, issue, verify, files in FINDINGS:
    detail = f"{issue}\n\nRepro: {verify}\n\nFiles: {files}\n\n(merge-review: pacsarcade-org profile/console, {code})"
    st, r = post("/roster", {"kind": kind, "title": title, "severity": SEV[sev],
                             "detail": detail, "source": "merge-review",
                             "dedup_key": f"merge-review:{code}"})
    tk = (r.get("result") or {})
    print(f"  {code:<7} {kind:<9} -> {st}  {tk.get('code','')}  {title[:48]}")
print("done. open the SCAR Duty Roster / GET /roster to see them.")
