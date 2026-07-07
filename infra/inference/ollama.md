# Inference backend: Ollama (Arch Linux)

The **WARM tier**, variant #1. Ollama is the node-wizard's pick for **small /
solo nodes**: one binary, automatic model management, the simplest possible
path to a local OpenAI-compatible endpoint. Everything runs on your GPU, on
your box — no API keys, nothing leaves the machine.

> The whole stack talks to inference through **one** OpenAI-compatible URL,
> `PA_INFERENCE_BASE_URL`. Swapping Ollama ⇄ vLLM is a config change, not a
> code change.

Target hardware for these notes: **RTX 4070 Ti SUPER (16 GB VRAM)**.

---

## When the wizard picks Ollama

- Solo node, one operator, a classroom, a handful of concurrent players.
- You want it to *just work* — pull a model, serve it, done.
- Low/bursty concurrency: Ollama serves requests largely one-at-a-time. That's
  fine when a few frens are learning; it is **not** built for continuous
  batching under heavy simultaneous load (that's when the wizard reaches for
  vLLM — see `vllm.md`).

---

## 1. Install

```bash
# Ollama is in the Arch 'extra' repo:
sudo pacman -S ollama

# For NVIDIA GPU acceleration you also need the CUDA runtime + driver:
sudo pacman -S nvidia cuda        # (or nvidia-dkms for custom kernels)

# Enable + start the service:
sudo systemctl enable --now ollama
```

Running under **rootless Podman** instead (matches the compose `--profile
ollama`)? The `ollama/ollama` image sees the GPU through **Podman CDI** — no
root daemon to restart, no `docker.sock`, no `--gpus` flag. Install the NVIDIA
Container Toolkit and generate the CDI spec once:

```bash
sudo pacman -S nvidia-container-toolkit
# Generate the CDI device spec (rootless → writes ~/.config/cdi/nvidia.yaml):
nvidia-ctk cdi generate --output="$HOME/.config/cdi/nvidia.yaml"
nvidia-ctk cdi list        # expect: nvidia.com/gpu=all
```

Then bring it up through compose, or run a standalone container to kick the
tyres — either way the GPU is injected by the CDI **device**:

```bash
# via compose (the whole stack, Ollama profile):
podman compose -f infra/compose.yaml --profile ollama up -d inference-ollama

# or standalone, note --device nvidia.com/gpu=all:
podman run --rm --device nvidia.com/gpu=all \
  -e OLLAMA_HOST=0.0.0.0:11434 -p 11434:11434 \
  -v models:/root/.ollama ollama/ollama:latest
```

The compose file already sets `OLLAMA_HOST=0.0.0.0:11434` and requests the GPU
via CDI, so sibling containers can reach it at `http://inference:11434`.

> Rootless GPU, one line: the card is injected by the CDI device
> `nvidia.com/gpu=all` that `nvidia-ctk cdi generate` produced — daemonless,
> rootless, no privileged container.

---

## 2. Pull a chat model that fits 16 GB (with KV-cache headroom)

A 7–8B model quantized to **Q4_K_M** weighs ~4.5–5 GB. That leaves ~10 GB of
the 16 GB for the **KV cache** (grows with context length × concurrency) plus
CUDA overhead — comfortable headroom. Do **not** run an unquantized 7B (~15 GB
of weights alone) — you'll have no room left to think.

Good defaults (pick one, set it as `PA_GEN_MODEL`):

```bash
ollama pull qwen2.5:7b-instruct-q4_K_M      # strong all-rounder
# or
ollama pull llama3.1:8b-instruct-q4_K_M
# or
ollama pull mistral:7b-instruct-q4_K_M
```

```bash
# .env
PA_GEN_MODEL=qwen2.5:7b-instruct-q4_K_M
```

Rule of thumb: **weights + KV cache must fit in 16 GB.** If you raise the
context window (`num_ctx`) or expect many concurrent Oracle turns, the KV cache
grows — keep the weights small (Q4) so the cache has room.

---

## 3. Pull the embedding model (for the pgvector guardrail)

The guardrail embeds every generated room and compares it to DB-1. Use the same
model the corpus was embedded with — **`nomic-embed-text`, 768 dims** (this is
why `documents.embedding` is `vector(768)`):

```bash
ollama pull nomic-embed-text
```

```bash
# .env
PA_EMBED_MODEL=nomic-embed-text
```

It's tiny (~275 MB) and stays resident happily alongside the chat model.

---

## 4. The OpenAI-compatible endpoint

Ollama exposes OpenAI-compatible routes under `/v1`. That's the contract the
orchestrator, guardrail, and everything else speak:

```bash
# .env
PA_INFERENCE_BACKEND=ollama
PA_INFERENCE_BASE_URL=http://inference:11434/v1
```

Endpoints you get for free:

- `POST /v1/chat/completions` — Oracle dialogue, Architect room generation
- `POST /v1/embeddings` — the guardrail's similarity vectors

Smoke test (from inside the compose network, or swap host for `localhost`):

```bash
curl http://inference:11434/v1/chat/completions -d '{
  "model": "qwen2.5:7b-instruct-q4_K_M",
  "messages": [{"role":"user","content":"Say hi, fren."}],
  "stream": true
}'
```

---

## 5. STREAMING is the whole trick ⚡

The WARM tier's promise is **first token < 300 ms**, not *whole answer* fast.
We keep the experience snappy by **streaming tokens** (`"stream": true`) and
rendering them as they arrive. The Oracle appears to *speak as it thinks*:

- The HOT loop acks the player instantly ("The Oracle considers your words…").
- Tokens then stream into the MUD/Luanti view the moment they're generated.
- Total generation time is *hidden behind the stream* — nobody stares at a
  spinner waiting for a paragraph to finish.

Always request `stream: true` for player-facing generation. Non-streamed calls
are fine only for background/batch work (e.g. the guardrail embedding, which
nobody is watching).
