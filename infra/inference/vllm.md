# Inference backend: vLLM (Arch Linux)

The **WARM tier**, variant #2. vLLM is the node-wizard's pick when a node has to
serve **many concurrent players**. Its superpower is **continuous batching**:
it fuses many in-flight requests into one GPU pass, so throughput scales and —
crucially — **first-token latency stays low under load** instead of collapsing
into a queue. More setup and more VRAM discipline than Ollama, but it holds up
when a whole classroom is talking to the Oracle at once.

> Same contract as always: one OpenAI-compatible URL, `PA_INFERENCE_BASE_URL`.
> The rest of the stack cannot tell which backend is behind it.

Target hardware for these notes: **RTX 4070 Ti SUPER (16 GB VRAM)**.

---

## When the wizard picks vLLM

- Many simultaneous learners; the Oracle/Architect are generating constantly.
- You care about **tail latency under concurrency** — vLLM's batching keeps the
  10th concurrent request's first token nearly as fast as the 1st.
- You have the VRAM budget and are willing to manage quantization + context
  length deliberately (see below).
- If none of that is true, use **Ollama** (`ollama.md`) — simpler is better.

---

## 1. Install

Two paths. The compose `--profile vllm` uses the container under **rootless
Podman**, which is the least fiddly on Arch:

```bash
# Container (matches compose.yaml `inference-vllm`) — needs the toolkit + a CDI spec:
sudo pacman -S nvidia-container-toolkit
nvidia-ctk cdi generate --output="$HOME/.config/cdi/nvidia.yaml"   # rootless CDI spec
nvidia-ctk cdi list        # expect: nvidia.com/gpu=all
# image: vllm/vllm-openai:latest  (already wired in the compose file)

# Bring it up (vLLM profile):
podman compose -f infra/compose.yaml --profile vllm up -d inference-vllm

# or standalone, note --device nvidia.com/gpu=all (rootless GPU via CDI):
podman run --rm --device nvidia.com/gpu=all -p 8000:8000 \
  -v models:/root/.cache/huggingface vllm/vllm-openai:latest \
  --model "$PA_GEN_MODEL" --quantization awq --max-model-len 8192 \
  --gpu-memory-utilization 0.90 --port 8000
```

> Rootless GPU, one line: the card is injected by the CDI device
> `nvidia.com/gpu=all` from `nvidia-ctk cdi generate` — no root daemon, no
> `docker.sock`, no `--gpus`.

Native venv (if you'd rather not use a container):

```bash
sudo pacman -S python cuda nvidia
python -m venv ~/.venvs/vllm
source ~/.venvs/vllm/bin/activate
pip install vllm            # pulls a CUDA build of torch + vLLM
```

---

## 2. Serve a quantized 7–8B that fits 16 GB (leave KV-cache headroom)

On 16 GB you **must** quantize — full-precision 7B weights alone won't leave
room for the KV cache that continuous batching depends on. Use a **4-bit AWQ**
(or GPTQ) checkpoint (~4–5 GB weights), cap the context, and cap GPU memory so
vLLM pre-reserves a sane KV pool:

```bash
vllm serve Qwen/Qwen2.5-7B-Instruct-AWQ \
  --quantization awq \
  --max-model-len 8192 \          # cap context so the KV cache fits beside weights
  --gpu-memory-utilization 0.90 \ # leave ~10% for CUDA / display
  --port 8000
```

The compose file passes exactly these flags via `PA_GEN_MODEL` (default
`Qwen/Qwen2.5-7B-Instruct-AWQ`). Set yours:

```bash
# .env
PA_GEN_MODEL=Qwen/Qwen2.5-7B-Instruct-AWQ
```

Tuning notes:
- Lower `--max-model-len` → bigger KV pool → **more concurrent players**. It's
  a direct trade: context length vs. how many frens you can batch.
- If you OOM at boot, drop `--gpu-memory-utilization` or the model length first.

---

## 3. Embeddings (nomic-embed-text, 768 dims)

The guardrail needs embeddings from the **same** model the corpus used —
`nomic-embed-text`, 768 dims (why `documents.embedding` is `vector(768)`).

VRAM reality on 16 GB: your AWQ chat model + its KV pool will use most of the
card, so running a **second** full vLLM instance for embeddings is usually a
tight squeeze. Two good options:

1. **Serve embeddings from a tiny sidecar Ollama** (`ollama pull
   nomic-embed-text`) — a few hundred MB, and point the embed calls there. Best
   of both: vLLM for chat throughput, Ollama for cheap embeddings.
2. **A second vLLM in embedding mode**, only if you have the headroom:
   ```bash
   vllm serve nomic-ai/nomic-embed-text-v1.5 --task embed --port 8001
   ```

Either way:

```bash
# .env
PA_EMBED_MODEL=nomic-embed-text
```

Keep the embedding model **resident** — the guardrail calls it on every
generated room, and cold-loading it would add latency to the review loop.

---

## 4. The OpenAI-compatible endpoint

vLLM's server IS an OpenAI-compatible API, on **port 8000** (not 11434!). So the
base URL differs from Ollama — set it accordingly:

```bash
# .env
PA_INFERENCE_BACKEND=vllm
PA_INFERENCE_BASE_URL=http://inference:8000/v1
```

(`inference` is a network alias in the compose file, so this name resolves to
whichever backend profile is running.)

Endpoints:
- `POST /v1/chat/completions` — Oracle / Architect generation
- `POST /v1/embeddings` — if you serve embeddings from vLLM (option 2 above)

Smoke test:

```bash
curl http://inference:8000/v1/chat/completions -d '{
  "model": "Qwen/Qwen2.5-7B-Instruct-AWQ",
  "messages": [{"role":"user","content":"Say hi, fren."}],
  "stream": true
}'
```

---

## 5. STREAMING is still the whole trick ⚡

Continuous batching lowers first-token latency; **streaming** is what turns that
into a good experience. Always send `"stream": true` for player-facing turns:

- The HOT loop acks instantly ("The Oracle considers your words…").
- Tokens stream into the MUD/Luanti view as they're produced.
- Under load, vLLM's batching means each player's stream *starts* fast even when
  many are generating — the win Ollama can't match at scale.

Reserve non-streamed calls for background work (batch embeddings) that no player
is watching.
