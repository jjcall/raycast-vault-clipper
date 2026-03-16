# raycast-vault-clipper

A Raycast script that grabs the URL from your active browser tab, pulls the content (tweets, YouTube videos, articles), summarizes it with an LLM, and saves a Markdown note to your Obsidian vault.

Hit a hotkey, get a note. No browser extension, no manual tagging.

---

## Why this exists

The official Obsidian Web Clipper is a browser extension, which means it's blocked in a lot of corporate environments. The Raycast extensions that already exist (Obsidian Smart Capture, Obsidian Clippings) either need a Raycast Pro subscription for AI, depend on Obsidian community plugins, or don't differentiate between content types.

This script sidesteps all of that:

- It's a Raycast script, not a browser extension
- You bring your own LLM (Ollama runs locally for free)
- It writes files directly to your vault folder, no Obsidian plugins needed
- Tweets, YouTube videos, and articles are each fetched and structured differently

---

## What it does

1. Reads the active tab URL from Chrome or Safari (or falls back to your clipboard)
2. Figures out what kind of content it is and fetches accordingly
3. Sends the content to your LLM for a title, summary, key points, and tags
4. Writes a Markdown note with frontmatter, wiki links, and source URL to your vault

Works with Ollama (local, free), OpenAI, Anthropic, or any OpenAI-compatible endpoint like Groq, Together, or LM Studio.

---

## Requirements

- macOS
- [Raycast](https://raycast.com)
- Python 3.9+
- An Obsidian vault
- One of: [Ollama](https://ollama.com) (free/local), OpenAI API key, or Anthropic API key

---

## Installation

### 1. Clone the repo

```bash
git clone https://github.com/your-username/raycast-vault-clipper.git
cd raycast-vault-clipper
```

### 2. Install dependencies

```bash
pip3 install requests trafilatura
```

### 3. Configure

```bash
cp config.example.json config.json
```

Open `config.json` and fill in your vault path and preferred LLM (see [Configuration](#configuration) below).

### 4. Add to Raycast

- Open Raycast, go to `⌘,` > Extensions > Scripts
- Click `+` > Add Scripts Directory > select this repo folder
- Search "Save to Vault" in Raycast and assign a hotkey (e.g. `⌥⇧S`)

### 5. Fix the shebang (if needed)

The script uses `#!/usr/bin/env python3`. If Raycast can't find your packages, point it at your actual Python:

```bash
which python3  # find your path
```

Then update the first line of `save-to-vault.py` (e.g. `#!/opt/homebrew/bin/python3`).

---

## Configuration

All settings live in `config.json` (gitignored, your local copy only).

| Key | Default | Description |
|-----|---------|-------------|
| `vault_path` | `~/Documents/Obsidian Vault` | Path to your Obsidian vault |
| `output_folder` | `Notes/Resources` | Folder inside vault where clips go |
| `browser` | `chrome` | Where to read the active tab: `chrome` or `safari` |
| `llm.provider` | `ollama` | `ollama`, `openai`, or `anthropic` |
| `llm.model` | `llama3.2:3b` | Model name |
| `llm.base_url` | `http://localhost:11434` | API base URL (Ollama or OpenAI-compatible) |
| `llm.api_key` | `""` | API key (not needed for Ollama) |
| `capture.max_content_chars` | `3000` | Max characters sent to the LLM |
| `capture.tag_count` | `5` | Number of tags to generate |
| `capture.filename_format` | `title` | `title`, `date-title`, or `title-date` |

### LLM provider setup

**Ollama** (recommended, runs locally)

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

**OpenAI** (or any OpenAI-compatible endpoint: Groq, Together, LM Studio)

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

1. Open a page in Chrome (tweet, YouTube video, article, whatever)
2. Press your Raycast hotkey
3. Watch the toast notifications as it fetches, summarizes, and saves
4. Check your vault

If no browser is open, copy a URL to your clipboard first. The script will pick it up.

---

## Output format

Each saved note looks like this:

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

PRs welcome. The script is intentionally a single file so it's easy to read and modify.
