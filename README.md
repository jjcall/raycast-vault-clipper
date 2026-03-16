# raycast-vault-clipper

A Raycast script that captures your active browser tab — tweet, YouTube video, or any webpage — summarizes it with AI, and saves a structured note directly to your Obsidian vault.

No browser extension. No copying URLs. No manual tagging. Just trigger a hotkey and it's in your vault.

---

## Why not the Obsidian Web Clipper or existing Raycast extensions?

The official Obsidian Web Clipper is a browser extension — which is blocked in many corporate environments. The existing Raycast extensions (Obsidian Smart Capture, Obsidian Clippings) either require a Raycast Pro subscription for AI, depend on Obsidian community plugins, or treat every URL the same way.

This tool is different:

- **No browser extension** — runs entirely as a Raycast script
- **No Raycast Pro required** — bring your own LLM
- **No Obsidian plugins required** — writes directly to your vault folder
- **Content-aware** — a tweet, YouTube video, and article are each fetched and structured differently
- **Local AI supported** — run Ollama for free, fully offline, nothing leaving your machine

---

## What it does

- **Reads your active Chrome or Safari tab** (falls back to clipboard URL)
- **Detects content type** — tweet, YouTube video, or webpage — and fetches accordingly
- **Summarizes with AI** — generates a title, summary, key points, and tags
- **Saves a structured Markdown note** to your Obsidian vault with frontmatter, wiki links, and a source link
- **Works with any LLM** — Ollama (local/free), OpenAI, Anthropic, or any OpenAI-compatible endpoint (Groq, Together, LM Studio)

---

## Requirements

- macOS
- [Raycast](https://raycast.com)
- Python 3.9+
- An Obsidian vault
- One of: [Ollama](https://ollama.com) (free/local), OpenAI API key, or Anthropic API key

---

## Installation

**1. Clone the repo**

```bash
git clone https://github.com/your-username/raycast-vault-clipper.git
cd raycast-vault-clipper
```

**2. Install dependencies**

```bash
pip3 install requests trafilatura
```

**3. Configure**

```bash
cp config.example.json config.json
```

Open `config.json` and fill in your vault path and preferred LLM (see [Configuration](#configuration) below).

**4. Add to Raycast**

- Open Raycast → `⌘,` → **Extensions** → **Scripts**
- Click `+` → **Add Scripts Directory** → select this repo folder
- Search "Save to Vault" in Raycast and assign a hotkey (e.g. `⌥⇧S`)

**5. Fix the shebang (if needed)**

The script uses `#!/usr/bin/env python3`. If Raycast can't find your packages, replace it with the explicit Python path:

```bash
which python3  # find your path
```

Then update the first line of `save-to-vault.py` to match (e.g. `#!/opt/homebrew/bin/python3`).

---

## Configuration

All settings live in `config.json` (gitignored — your local copy only).

| Key | Default | Description |
|-----|---------|-------------|
| `vault_path` | `~/Documents/Obsidian Vault` | Path to your Obsidian vault |
| `output_folder` | `Notes/Resources` | Folder inside vault where clips are saved |
| `browser` | `chrome` | Active tab source — `chrome` or `safari` |
| `llm.provider` | `ollama` | LLM provider — `ollama`, `openai`, or `anthropic` |
| `llm.model` | `llama3.2:3b` | Model name |
| `llm.base_url` | `http://localhost:11434` | API base URL (Ollama or OpenAI-compatible) |
| `llm.api_key` | `""` | API key (not needed for Ollama) |
| `capture.max_content_chars` | `3000` | Max characters sent to AI for webpage content |
| `capture.tag_count` | `5` | Number of tags to generate |
| `capture.filename_format` | `title` | Filename style — `title`, `date-title`, or `title-date` |

### LLM Provider Setup

**Ollama (free, local — recommended)**

```bash
brew install ollama
ollama pull llama3.2:3b
```

```json
"llm": {
  "provider": "ollama",
  "model": "llama3.2:3b",
  "base_url": "http://localhost:11434",
  "api_key": ""
}
```

**OpenAI (or any OpenAI-compatible endpoint — Groq, Together, LM Studio)**

```json
"llm": {
  "provider": "openai",
  "model": "gpt-4o-mini",
  "base_url": "https://api.openai.com",
  "api_key": "sk-..."
}
```

For Groq, set `base_url` to `https://api.groq.com/openai` and use a Groq model name.

**Anthropic**

```json
"llm": {
  "provider": "anthropic",
  "model": "claude-haiku-4-5-20251001",
  "base_url": "",
  "api_key": "sk-ant-..."
}
```

---

## Usage

1. Open any page in Chrome — a tweet, YouTube video, or article
2. Press your Raycast hotkey
3. Watch the progress toast: `🐦 Fetching tweet... → ⚙️ Summarizing... → ✅ Saved`
4. Note appears in your vault

**Clipboard fallback:** If no browser is open, copy any URL to your clipboard first — the script will use it automatically.

---

## Output format

Each saved note looks like:

```markdown
---
title: "Brecka Daily Supplement Stack Kids"
type: clip
subtype: resource
source: https://x.com/...
author: "Camus"
tags:
  - supplements
  - health
  - nutrition
date: 2026-03-16
---

# Brecka Daily Supplement Stack Kids

## Summary

Gary Brecka recommends a daily stack...

## Tweet

> Gary Brecka lays out his no-BS "must-have" daily stack...

## Notes

---

[[supplements]]  [[health]]  [[nutrition]]
```

---

## Contributing

PRs welcome. The script is intentionally kept as a single file to stay easy to read and modify.
