"""connectors/custom-markdown/connector.py — local .md folder → corpus records. 💜

SCAFFOLDING / STUB. Implements the connector `fetch()` interface (see connectors/README.md).

Walks a local folder of Markdown files and yields each as a record for the corpus ingest
pipeline (chunk → embed → DB-1). Perfect for feeding a meetup's own notes into The Source.

Tier: COLD. Optional / opt-in (manifest `enabled: false`). FULLY OFFLINE — only reads the local
filesystem, never the network. Background job; never on a gameplay hot path.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import AsyncIterator

_MANIFEST = json.loads((Path(__file__).parent / "manifest.json").read_text(encoding="utf-8"))
_CONFIG = _MANIFEST.get("config", {})

ROOT_DIR = os.environ.get("PA_MARKDOWN_ROOT", _CONFIG.get("root_dir", "/corpus/markdown"))
GLOB = _CONFIG.get("glob", "**/*.md")


async def fetch() -> AsyncIterator[dict]:
    """Yield {source_url, title, content} for each .md file under ROOT_DIR.

    Consumed by `ingest_records()` in services/corpus/ingest.py.
    """
    root = Path(ROOT_DIR)
    if not root.exists():
        # Nothing to ingest — degrade quietly. The operator simply hasn't populated the folder.
        # TODO: log an info-level note so the operator knows the connector found no files.
        return

    for path in sorted(root.glob(GLOB)):
        if not path.is_file():
            continue
        # TODO: read the file; derive `title` from the first `# H1` heading if present, else the
        #       filename stem; strip front-matter if any. Keep `content` as raw markdown so the
        #       embedder sees clean text.
        content = path.read_text(encoding="utf-8", errors="replace")
        title = path.stem  # TODO: prefer an in-file H1 over the filename.
        yield {
            "source_url": path.resolve().as_uri(),
            "title": title,
            "content": content,
        }
