#!/usr/bin/env bash
# node-doctor.sh — hardware & environment probe for the Pac's Arcade node-wizard.
# Emits a single JSON object on stdout describing this box so the wizard can
# recommend an inference backend, a model, a corpus scale, and flag problems early.
# Read-only. Makes no changes. Safe to run any time.
#
# Runtime target: rootless, daemonless Podman (no docker, no docker.sock).
#
# Usage:  ./scripts/node-doctor.sh            # pretty (jq if present)
#         ./scripts/node-doctor.sh --raw      # raw JSON
set -euo pipefail

have() { command -v "$1" >/dev/null 2>&1; }
num()  { [[ -n "${1:-}" && "$1" =~ ^[0-9]+$ ]] && echo "$1" || echo 0; }

# --- OS / distro -------------------------------------------------------------
DISTRO="unknown"; KERNEL="$(uname -r 2>/dev/null || echo unknown)"
[[ -r /etc/os-release ]] && DISTRO="$(. /etc/os-release; echo "${PRETTY_NAME:-$NAME}")"

# --- CPU / RAM ---------------------------------------------------------------
CPU_MODEL="$(have lscpu && lscpu | sed -n 's/^Model name:[[:space:]]*//p' | head -1 || echo unknown)"
CPU_CORES="$(num "$(nproc 2>/dev/null || echo 0)")"
RAM_GB=0
if [[ -r /proc/meminfo ]]; then
  RAM_KB="$(sed -n 's/^MemTotal:[[:space:]]*\([0-9]*\).*/\1/p' /proc/meminfo)"
  RAM_GB=$(( $(num "$RAM_KB") / 1024 / 1024 ))
fi

# --- GPU / VRAM (NVIDIA focus; RTX 4070 Ti SUPER = 16 GB target) --------------
GPU_MODEL="none"; VRAM_MB=0; NVIDIA_DRIVER="absent"
if have nvidia-smi; then
  NVIDIA_DRIVER="$(nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -1 || echo present)"
  GPU_MODEL="$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1 || echo 'NVIDIA GPU')"
  VRAM_MB="$(num "$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | head -1)")"
fi
VRAM_GB=$(( VRAM_MB / 1024 ))

# --- Disk (free GB on the repo's filesystem) ---------------------------------
DISK_FREE_GB="$(num "$(df -BG --output=avail . 2>/dev/null | tail -1 | tr -dc '0-9')")"

# --- Virtualization / containers (rootless Podman) ---------------------------
VIRT="$(have systemd-detect-virt && systemd-detect-virt 2>/dev/null || echo unknown)"
WHO="$(id -un 2>/dev/null || echo "${USER:-unknown}")"

# Podman + a compose front-end (`podman compose` OR the standalone podman-compose).
HAS_PODMAN=false; have podman && HAS_PODMAN=true
HAS_PODMAN_COMPOSE=false
if have podman && podman compose version >/dev/null 2>&1; then
  HAS_PODMAN_COMPOSE=true
elif have podman-compose; then
  HAS_PODMAN_COMPOSE=true
fi

# Rootless readiness: this user needs a subuid + subgid range for user namespaces.
SUBUID_OK=false; SUBGID_OK=false
[[ -r /etc/subuid ]] && grep -q "^${WHO}:" /etc/subuid 2>/dev/null && SUBUID_OK=true
[[ -r /etc/subgid ]] && grep -q "^${WHO}:" /etc/subgid 2>/dev/null && SUBGID_OK=true
ROOTLESS_READY=false
[[ "$SUBUID_OK" == true && "$SUBGID_OK" == true ]] && ROOTLESS_READY=true

# Linger lets `systemd --user` (Quadlet) services start at boot without a login.
LINGER=false
have loginctl && loginctl show-user "$WHO" 2>/dev/null | grep -q '^Linger=yes' && LINGER=true

# NVIDIA CDI for Podman: the toolkit ships `nvidia-ctk`, and a generated CDI spec
# must live in /etc/cdi (system) or ~/.config/cdi (rootless) for `AddDevice=`/
# `--device nvidia.com/gpu=all` to resolve.
HAS_NVIDIA_CTK=false; have nvidia-ctk && HAS_NVIDIA_CTK=true
HAS_NVIDIA_CDI=false
for d in /etc/cdi "$HOME/.config/cdi"; do
  if [[ -d "$d" ]] && ls "$d"/*.yaml "$d"/*.yml "$d"/*.json >/dev/null 2>&1; then
    HAS_NVIDIA_CDI=true
  fi
done

# --- Recommendations ---------------------------------------------------------
# Inference backend: vLLM shines with concurrency IF there's enough VRAM; else Ollama.
REC_BACKEND="ollama"
[[ "$VRAM_GB" -ge 12 ]] && REC_BACKEND="vllm-capable"   # wizard confirms w/ concurrency answer
REC_GEN_MODEL="qwen2.5:7b-instruct-q4_K_M"              # sane 16GB default; wizard may override
[[ "$VRAM_GB" -ge 24 ]] && REC_GEN_MODEL="a 13-14B quantized model"
[[ "$VRAM_GB" -eq 0 ]]  && { REC_BACKEND="cpu-only"; REC_GEN_MODEL="a small CPU model (slow)"; }

# Corpus: Simple English needs ~a few GB; full enwiki wants lots of disk + weeks of embed.
REC_CORPUS="simple-wikipedia"
[[ "$DISK_FREE_GB" -ge 250 && "$VRAM_GB" -ge 16 ]] && REC_CORPUS="simple-wikipedia (en-wikipedia feasible)"

WARNINGS="[]"
warns=()
[[ "$VRAM_GB" -eq 0 ]]        && warns+=("No NVIDIA GPU detected — generation will be slow (CPU).")
[[ "$NVIDIA_DRIVER" == absent && "$GPU_MODEL" != none ]] && warns+=("GPU present but no driver — install NVIDIA drivers.")
[[ "$DISK_FREE_GB" -lt 60 ]]  && warns+=("Low disk (<60GB free) — the corpus + models need room.")
[[ "$RAM_GB" -lt 16 ]]        && warns+=("Low RAM (<16GB) — Postgres + inference will be tight.")
[[ "$HAS_PODMAN" == false ]]  && warns+=("Podman not installed — the wizard will help you add it (rootless, no daemon).")
[[ "$HAS_PODMAN" == true && "$HAS_PODMAN_COMPOSE" == false ]] && warns+=("No compose front-end — install 'podman compose' (podman-docker/podman-compose) or 'podman-compose'.")
[[ "$ROOTLESS_READY" == false ]] && warns+=("Rootless not ready — no subuid/subgid range for '$WHO' in /etc/subuid & /etc/subgid. Add one, e.g.: sudo usermod --add-subuids 100000-165535 --add-subgids 100000-165535 $WHO && podman system migrate.")
[[ "$LINGER" == false ]]      && warns+=("Linger disabled — 'systemctl --user' services won't start at boot. Run 'loginctl enable-linger $WHO' (needed for the Quadlet production path).")
[[ "$HAS_NVIDIA_CTK" == false && "$GPU_MODEL" != none ]] && warns+=("nvidia-container-toolkit missing — provides 'nvidia-ctk' to generate the Podman CDI spec.")
[[ "$HAS_NVIDIA_CDI" == false && "$GPU_MODEL" != none ]] && warns+=("No CDI spec in /etc/cdi or ~/.config/cdi — generate it: nvidia-ctk cdi generate --output=\$HOME/.config/cdi/nvidia.yaml")
if [[ ${#warns[@]} -gt 0 ]]; then
  WARNINGS="[$(printf '"%s",' "${warns[@]}" | sed 's/,$//')]"
fi

# --- Emit JSON ---------------------------------------------------------------
JSON=$(cat <<EOF
{
  "os": {"distro": "$DISTRO", "kernel": "$KERNEL", "virt": "$VIRT"},
  "cpu": {"model": "$CPU_MODEL", "cores": $CPU_CORES},
  "ram_gb": $RAM_GB,
  "gpu": {"model": "$GPU_MODEL", "vram_gb": $VRAM_GB, "nvidia_driver": "$NVIDIA_DRIVER"},
  "disk_free_gb": $DISK_FREE_GB,
  "tooling": {"podman": $HAS_PODMAN, "podman_compose": $HAS_PODMAN_COMPOSE, "nvidia_cdi": $HAS_NVIDIA_CDI, "rootless_ready": $ROOTLESS_READY},
  "recommendations": {
    "inference_backend": "$REC_BACKEND",
    "gen_model": "$REC_GEN_MODEL",
    "embed_model": "nomic-embed-text",
    "corpus": "$REC_CORPUS"
  },
  "warnings": $WARNINGS
}
EOF
)

if [[ "${1:-}" != "--raw" ]] && have jq; then echo "$JSON" | jq .; else echo "$JSON"; fi
