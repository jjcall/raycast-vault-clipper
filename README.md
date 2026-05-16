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

### 2. Configure

```bash
cp config.example.json config.json
```

Open `config.json` and fill in your vault path and preferred LLM (see [Configuration](#configuration) below).

### 3. Add to Raycast

- Open Raycast, go to `⌘,` > Extensions > Scripts
- Click `+` > Add Scripts Directory > select this repo folder
- Search "Save to Vault" in Raycast and assign a hotkey (e.g. `⌥⇧S`)

That's it. No `pip install`, no PATH twiddling, no shebang surgery.

### How dependencies work

The script auto-bootstraps a virtual environment the first time you run it. On first run you'll see:

```
⚙️  First-run setup: creating venv and installing dependencies...
    (this takes 10-30 seconds, only happens once)
```

That creates `.venv/` next to the script with `requests`, `trafilatura`, and `markdownify` inside. Every run after that uses the venv directly, so the hotkey is instant.

Works with any Python 3.9+ on `PATH` — Apple's `/usr/bin/python3`, Homebrew (Intel or Apple Silicon), pyenv, conda, whatever. The script doesn't care which one it bootstraps from.

If you ever need to rebuild (corruption, Python upgrade, moved the repo): `rm -rf .venv` and run the script once.

#### Tip: warm the venv before assigning the hotkey

So the first Raycast invocation doesn't take 30 seconds, run it once from the terminal first:

```bash
./save-to-vault.py
```

The first run will install deps and then complain about no URL (expected). After that, the venv is ready and the Raycast hotkey is instant.

---

## Configuration

All settings live in `config.json` (gitignored, your local copy only).

| Key | Default | Description |
|-----|---------|-------------|
| `vault_path` | `~/Documents/Obsidian Vault` | Path to your Obsidian vault |
| `output_folder` | `Sources/clips` | Folder inside vault where clips go |
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
3. The stub note lands in your vault immediately. The summary, tags, and key points fill in seconds later as the LLM finishes.
4. Check your vault

If no browser is open, copy a URL to your clipboard first. The script will pick it up.

### How async enrichment works

Each capture happens in two phases so the hotkey feels instant:

1. **Sync:** the script reads your tab, fetches the content, writes a stub note (`processed: false`) plus a sidecar JSON in `Sources/clips/_pending/`, and exits.
2. **Background:** a detached Python subprocess runs the LLM, rewrites the note with summary + tags + key points (`processed: true`), and deletes the sidecar.

If your laptop sleeps mid-process or the LLM is down, the sidecar stays in `_pending/` as a flag. Re-run anytime to clean it up:

```bash
./save-to-vault.py --sweep
```

That walks `_pending/`, retries every leftover sidecar, and removes the ones it can process. You can also wire `--sweep` as a second Raycast command if you want a one-click "catch up."

---

## Output format

Each saved note looks like this:

```markdown
---
title: "Punks vs Rude Boys Subcultures"
type: clip
subtype: resource
source: https://x.com/timecaptales/status/1736190618320158819
author: "Time Capsule Tales"
tags:
  - subcultures
  - music-history
  - fashion
date: 2026-03-16
---

# Punks vs Rude Boys Subcultures

## Summary

A comparison of two iconic youth subcultures: punks, known for their anti-establishment views and DIY aesthetic, and rude boys, rooted in the Jamaican diaspora with sharp suits and ties to ska and reggae music.

## Tweet

> Punks were known for their anti-establishment views and ripped clothing, safety pins, and mohawks dyed in bright colors. Rude boys were part of a subculture that had its origins in the Jamaican diaspora with sharp suits and pork pie hats closely associated with ska and reggae...

## Notes

---

[[subcultures]]  [[music-history]]  [[fashion]]
```

---

## Contributing

PRs welcome. The script is intentionally a single file so it's easy to read and modify.
