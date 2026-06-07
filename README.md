# raycast-vault-clipper

Two Raycast scripts for sending links from your active browser tab into an
Obsidian vault.

| Command | Script | Use it for |
|---|---|---|
| Save to Vault | `save-to-vault.py` | Comprehensive saved notes with extracted content, AI summary, tags, and frontmatter |
| Read Later to Daily | `read-later.py` | One lightweight bookmark link appended to today's daily note |

Use **Save to Vault** when you want a full note you can search, process, and
revisit. Use **Read Later to Daily** when you only want to park a link for
later.

---

## Why this exists

The official Obsidian Web Clipper is a browser extension, which can be blocked
in locked-down work environments. Existing Raycast options also tend to require
Raycast Pro, Obsidian plugins, or a capture flow that does not match how you
use your vault.

This repo keeps the path simple:

- It runs from Raycast, no browser extension needed.
- It writes directly to your vault folder.
- The full clipper can use your own LLM.
- The read-later command has no LLM step. It just saves the link.

---

## What Each Script Does

### Save to Vault

`save-to-vault.py` is the full clipper.

1. Reads the active tab URL from Chrome or Safari, with clipboard fallback.
2. Detects tweets, X threads, X articles, YouTube videos, and webpages.
3. Extracts the source content. For YouTube, it tries to pull the transcript
   first and falls back to the video description.
4. Writes a stub note immediately.
5. Runs AI enrichment in the background for summary, key points, tags, and type.
6. Saves the final note to your configured output folder.

The saved note keeps the full article body under `## Article` or
`## Full Content`, and YouTube captures keep the transcript under
`## Transcript` when captions are available. The `article_max_chars` setting
only caps what gets sent to the LLM, not what gets stored in Obsidian.

### Read Later to Daily

`read-later.py` is intentionally small.

1. Reads the active tab URL and title from Chrome or Safari, with clipboard
   fallback.
2. Cleans the title. For X/Twitter links, it trims long tweet text into a short
   title instead of dumping the whole post.
3. Appends one bookmark bullet under `## Notes` in today's daily note.
4. Creates the daily note if it does not exist yet.
5. De-dupes by URL, so hitting the hotkey twice does not spam the note.

Example output:

```markdown
- [b] [Bill Guo: designing in code be like...](<https://x.com/billguo/status/123>)
```

---

## Requirements

- macOS
- [Raycast](https://raycast.com)
- Python 3.9+
- An Obsidian vault
- Chrome or Safari
- For `save-to-vault.py` only: Ollama, OpenAI, Anthropic, or another
  OpenAI-compatible endpoint

`read-later.py` uses only the Python standard library.

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

Open `config.json` and set your vault path and browser. If you plan to use the
full clipper, also set your LLM provider.

### 3. Add the scripts to Raycast

- Open Raycast settings.
- Go to **Extensions** > **Scripts**.
- Click `+` > **Add Scripts Directory**.
- Select this repo folder.
- Search for **Save to Vault** and assign a hotkey.
- Search for **Read Later to Daily** and assign a second hotkey.

That is it. No Obsidian plugin, no browser extension.

---

## Dependencies

`read-later.py` has no third-party dependencies.

`save-to-vault.py` bootstraps its own virtual environment the first time you run
it. On first run you will see:

```text
First-run setup: creating venv and installing dependencies...
(this takes 10-30 seconds, only happens once)
```

That creates `.venv/` next to the script and installs `requests`,
`trafilatura`, `markdownify`, and `youtube-transcript-api`. Every run after
that uses the local venv.

To warm it up before assigning a hotkey:

```bash
./save-to-vault.py
```

The first run may complain about no URL if you run it from the terminal. That is
fine. The venv is ready after that.

If you ever need to rebuild the venv, delete `.venv/` and run
`save-to-vault.py` again.

---

## Configuration

All settings live in `config.json`, which is gitignored.

| Key | Default | Description |
|-----|---------|-------------|
| `vault_path` | `~/Documents/Obsidian Vault` | Path to your Obsidian vault |
| `output_folder` | `Sources/clips` | Where full saved notes are written |
| `browser` | `chrome` | Browser to read from: `chrome` or `safari` |
| `llm.provider` | `ollama` | `ollama`, `openai`, or `anthropic` |
| `llm.model` | `llama3.2:3b` | Model name |
| `llm.base_url` | `http://localhost:11434` | API base URL |
| `llm.api_key` | `""` | API key, not needed for Ollama |
| `capture.max_content_chars` | `3000` | Max short-content characters sent to the LLM |
| `capture.article_max_chars` | `16000` | Max article characters sent to the LLM |
| `capture.tag_count` | `5` | Number of tags to generate |
| `capture.filename_format` | `title` | `title`, `date-title`, or `title-date` |

`read-later.py` only needs `vault_path` and `browser`.

### LLM Provider Setup

For Ollama:

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

For OpenAI or an OpenAI-compatible endpoint:

```json
"llm": {
  "provider": "openai",
  "model": "gpt-4o-mini",
  "base_url": "https://api.openai.com",
  "api_key": "sk-..."
}
```

For Anthropic:

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

### Save a Full Note

1. Open a page in Chrome or Safari.
2. Run **Save to Vault** from Raycast.
3. A stub note lands in your configured output folder.
4. The background process fills in the AI summary, key points, tags, and final
   frontmatter.

If no browser tab is available, copy a URL first. The script will use the
clipboard as a fallback.

### Save a Read-Later Link

1. Open the page, post, or tweet you want to save.
2. Run **Read Later to Daily** from Raycast.
3. The script appends one `[b]` bookmark bullet under `## Notes` in
   `Journal/Daily/YYYY-MM-DD.md`.

You can also run it from the terminal:

```bash
./read-later.py --url https://example.com/post --title "Example Post"
```

For testing without writing to the vault:

```bash
./read-later.py --url https://example.com/post --title "Example Post" --dry-run
```

---

## Maintenance Commands

### Sweep Pending Saves

If your laptop sleeps or the LLM is down, a pending sidecar may stay in
`<output_folder>/_pending/`. Retry all pending saves with:

```bash
./save-to-vault.py --sweep
```

### Fix Processed Notes Missing Summaries

If a saved note is marked processed but no matching downstream summary exists:

```bash
./save-to-vault.py --fix-orphans
```

### Debug Browser Detection

X changes its DOM often. If a tweet, thread, or X article clips in the wrong
shape, run:

```bash
./diagnose-tab.py
```

It prints the selectors and content lengths the clipper can see in the active
tab. That usually tells you whether the issue is detection, extraction, or LLM
truncation.

---

## Output Examples

### Read Later

```markdown
## Notes
- [b] [Example Post](<https://example.com/post>)
```

### Full Save

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
enriched: true
processed: false
domain: subcultures
---

# Punks vs Rude Boys Subcultures

## Summary

A concise AI summary goes here.

## Tweet

> Source content goes here.

## Notes

---

[[subcultures]]  [[music-history]]  [[fashion]]
```

---

## Contributing

PRs welcome. The scripts are intentionally small so they stay easy to inspect,
debug, and adapt to a specific vault workflow.
