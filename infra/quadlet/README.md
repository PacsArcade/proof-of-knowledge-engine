# Quadlet — the PRODUCTION path for the verse 💜

These are **Podman Quadlet** systemd unit files. They let an operator run the
whole Federated Knowledge Engine as **rootless `systemd --user` services**:
auto-restart on crash, start-on-boot, journald logs, ordered dependencies — no
root, no daemon, no `docker.sock`.

Quadlet is a systemd generator shipped with Podman (v4.4+). It reads
`.container` / `.network` / `.volume` files and generates real `.service` units
at login. You never write raw `podman run` lines — you write these declarative
units, and Podman keeps them running.

> For quick local dev / a first smoke test, use `infra/compose.yaml` with
> `podman compose` instead (see `scripts/bootstrap.sh`). Quadlet is for the box
> you want to *stay up*.

---

## What's here

| Kind | Files |
|------|-------|
| Networks | `hot.network`, `warm.network`, `cold.network` (the three tiers) |
| Volumes | `pgdata-gamestate`, `pgdata-source`, `bitcoin-data`, `models`, `corpus-data`, `matrix-data` (`.volume`) |
| Containers | `postgres-gamestate`, `postgres-source`, `inference`, `orchestrator`, `guardrail`, `state-sync`, `corpus`, `matrix`, `mud`, `luanti`, `bitcoin`, `matrix-bridge`, `bitcoin-bridge` (`.container`) |

Service names, ports, tiers, and volumes match `infra/compose.yaml` exactly.
Cross-container DNS uses the **container name** (aardvark-dns), so `inference`,
`postgres-gamestate`, `state-sync`, … resolve just like the compose service
names. The `inference` unit runs the **Ollama** backend by default; swap it for
vLLM by editing `inference.container` (instructions inline in that file).

---

## Assumptions you may need to adjust

1. **Repo location.** The bind-mounted config files (Postgres init SQL, the
   Dendrite/bitcoin/Luanti configs, the pacsarcade mod) are referenced as
   `%h/pacsarcade/knowledge-engine/...` — i.e. the repo is cloned at
   `~/pacsarcade/knowledge-engine`. If yours lives elsewhere, either symlink it
   there, or `sed -i 's#%h/pacsarcade/knowledge-engine#/your/path#' *.container`.
2. **Built images.** The seven app services reference `localhost/pacsarcade/*:dev`.
   Build them first (once), from the repo root:
   ```bash
   podman compose -f infra/compose.yaml build
   ```
   If `podman images` lists them without the `localhost/` prefix, drop it from
   the `Image=` lines to match.
3. **The `.env`.** Each unit loads `EnvironmentFile=-%h/.../infra/.env`
   (the leading `-` means "ignore if absent", mirroring compose's
   `required: false`). The two Postgres units also set the image's `POSTGRES_*`
   vars explicitly — keep those in sync with `PA_DB1_*` / `PA_DB2_*` in `.env`.

---

## Install

```bash
# 1. Drop the units into the rootless Quadlet search path:
mkdir -p ~/.config/containers/systemd
cp infra/quadlet/*.network ~/.config/containers/systemd/
cp infra/quadlet/*.volume  ~/.config/containers/systemd/
cp infra/quadlet/*.container ~/.config/containers/systemd/

# 2. Regenerate the systemd units from the Quadlet files:
systemctl --user daemon-reload

# 3. Bring the stack up (dependencies pull networks/volumes in automatically).
#    Order mirrors bootstrap.sh: data -> inference -> bitcoin/matrix -> services
#    -> front-ends. Starting a leaf will drag its deps in via After=/Wants=.
systemctl --user start postgres-gamestate postgres-source
systemctl --user start inference
systemctl --user start bitcoin matrix
systemctl --user start orchestrator guardrail state-sync corpus matrix-bridge bitcoin-bridge
systemctl --user start mud luanti

# Status / logs:
systemctl --user status inference
journalctl --user -u inference -f
```

## Start on boot (and survive logout)

`systemd --user` services normally stop when you log out. **Linger** keeps them
running 24/7 and starts them at boot without an interactive session:

```bash
# Enable lingering for this user (needs to be run once; may require sudo):
loginctl enable-linger "$USER"

# Enable each container unit so it starts at boot:
systemctl --user enable postgres-gamestate postgres-source inference \
  orchestrator guardrail state-sync corpus matrix matrix-bridge \
  bitcoin bitcoin-bridge mud luanti
```

(`.network` / `.volume` units don't need `enable` — the containers that use them
pull them in on demand.)

---

## Rootless GPU via CDI (for `inference`)

Podman exposes the NVIDIA GPU through the **Container Device Interface (CDI)**,
not the Docker `--gpus` flag. Generate the CDI spec once on the host, then the
`inference.container` unit's `AddDevice=nvidia.com/gpu=all` just works:

```bash
# Rootless spec (this user only) — no daemon restart, no root:
nvidia-ctk cdi generate --output="$HOME/.config/cdi/nvidia.yaml"
# (system-wide alternative: sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml)

# Verify the device name the unit references exists:
nvidia-ctk cdi list        # expect: nvidia.com/gpu=all
```

Prereqs: NVIDIA driver + `nvidia-container-toolkit` (which ships `nvidia-ctk`).
Regenerate the spec after a driver upgrade. `scripts/node-doctor.sh` checks all
of this for you.

---

## Update / teardown

```bash
# After editing a unit file, re-copy it and reload, then restart the service:
cp infra/quadlet/inference.container ~/.config/containers/systemd/
systemctl --user daemon-reload
systemctl --user restart inference

# Stop everything:
systemctl --user stop mud luanti orchestrator guardrail state-sync corpus \
  matrix-bridge bitcoin-bridge inference bitcoin matrix \
  postgres-gamestate postgres-source
```

Money safety is unchanged from the rest of the stack: **regtest is the default**;
mainnet stays gated behind `PA_MAINNET_ACK` + a passing `security-auditor`
review. See `docs/SECURITY.md`.
