#!/usr/bin/env python3

# Required parameters:
# @raycast.schemaVersion 1
# @raycast.title Save to Vault
# @raycast.mode compact
# @raycast.packageName Obsidian

# Optional parameters:
# @raycast.icon 🗂️
# @raycast.description Active browser tab → AI summary + tags → Obsidian vault

import subprocess
import sys
import json
import re
from datetime import datetime
from pathlib import Path
from html import unescape

# ── Dependencies ──────────────────────────────────────────────────────────────

try:
    import requests
except ImportError:
    print("❌ Missing dependency: pip3 install requests")
    sys.exit(1)

try:
    import trafilatura
except ImportError:
    print("❌ Missing dependency: pip3 install trafilatura")
    sys.exit(1)

# ── Config ────────────────────────────────────────────────────────────────────

def load_config():
    config_path = Path(__file__).parent / "config.json"
    example_path = Path(__file__).parent / "config.example.json"

    path = config_path if config_path.exists() else example_path
    if not path.exists():
        print("❌ No config.json found. Copy config.example.json → config.json and fill in your settings.")
        sys.exit(1)

    with open(path) as f:
        config = json.load(f)

    # Expand ~ in vault path
    config["vault_path"] = str(Path(config["vault_path"]).expanduser())
    return config

# ── URL source ────────────────────────────────────────────────────────────────

BROWSER_SCRIPTS = {
    "chrome": 'tell application "Google Chrome" to get URL of active tab of front window',
    "safari": 'tell application "Safari" to get URL of current tab of front window',
}

def get_url(browser):
    script = BROWSER_SCRIPTS.get(browser)
    if script:
        result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
        if result.returncode == 0:
            url = result.stdout.strip()
            if url.startswith("http"):
                return url

    # Fall back to clipboard
    clip = subprocess.run(["pbpaste"], capture_output=True, text=True).stdout.strip()
    if clip.startswith("http"):
        return clip

    return None

# ── URL detection ─────────────────────────────────────────────────────────────

def detect_type(url):
    if re.search(r"(twitter\.com|x\.com)/\w+/status/\d+", url):
        return "tweet"
    if re.search(r"(youtube\.com/watch|youtu\.be/)", url):
        return "youtube"
    return "webpage"

# ── Fetchers ──────────────────────────────────────────────────────────────────

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}

def fetch_tweet(url):
    normalized = re.sub(r"https://x\.com/", "https://twitter.com/", url)
    resp = requests.get(
        "https://publish.twitter.com/oembed",
        params={"url": normalized, "omit_script": "true"},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()

    html = data.get("html", "")
    p = re.search(r"<p[^>]*>(.*?)</p>", html, re.DOTALL)
    text = ""
    if p:
        raw = p.group(1)
        raw = re.sub(r"<br\s*/?>", "\n", raw)
        raw = re.sub(r'<a[^>]*href="([^"]*)"[^>]*>([^<]*)</a>', r"\2", raw)
        raw = re.sub(r"<[^>]+>", "", raw)
        text = unescape(raw).strip()

    author = data.get("author_name", "")
    handle = data.get("author_url", "").rstrip("/").split("/")[-1]
    return {"author": author, "handle": handle, "content": text}


def fetch_youtube(url):
    oembed = requests.get(
        "https://www.youtube.com/oembed",
        params={"url": url, "format": "json"},
        timeout=10,
    ).json()

    title = oembed.get("title", "")
    author = oembed.get("author_name", "")

    page = requests.get(url, headers=HEADERS, timeout=10)
    desc = ""
    m = re.search(r'<meta name="description" content="([^"]*)"', page.text)
    if m:
        desc = unescape(m.group(1))

    return {"title": title, "author": author, "content": desc}


def fetch_from_browser(browser):
    """Extract rendered page content directly from the browser tab via JS execution.
    Bypasses bot protection since the browser has already loaded the page."""
    js = """(function() {
        var title = document.title;
        var text = document.body.innerText;
        var metas = document.querySelectorAll('meta[name="author"], meta[property="author"]');
        var author = metas.length ? metas[0].getAttribute('content') : '';
        return JSON.stringify({title: title, text: text, author: author});
    })()"""

    scripts = {
        "chrome": f'tell application "Google Chrome" to execute javascript "{js}" in active tab of front window',
        "safari": f'tell application "Safari" to do javascript "{js}" in current tab of front window',
    }
    script = scripts.get(browser)
    if not script:
        return None

    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if result.returncode != 0:
        return None

    try:
        data = json.loads(result.stdout.strip())
        return data
    except Exception:
        return None


def extract_html_meta(html):
    """Extract title, author, and description from raw HTML."""
    title = ""
    author = ""
    description = ""

    m = re.search(r"<title[^>]*>([^<]+)</title>", html, re.I)
    if m:
        title = unescape(m.group(1).strip())
        title = re.split(r"\s*[|\-—]\s*", title)[0].strip()

    m = re.search(r'"author"[^}]*?"name"\s*:\s*"([^"]+)"', html)
    if m:
        author = m.group(1)

    for pattern in [
        r'<meta\s+name="description"\s+content="([^"]*)"',
        r'<meta\s+property="og:description"\s+content="([^"]*)"',
    ]:
        m = re.search(pattern, html, re.I)
        if m:
            description = unescape(m.group(1))
            break

    return title, author, description


def strip_html_to_text(html):
    """Strip scripts, styles, and tags from HTML to get raw visible text."""
    text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def fetch_webpage(url, max_chars, browser=None):
    # Try direct browser extraction first (bypasses bot protection)
    if browser:
        browser_data = fetch_from_browser(browser)
        if browser_data and len(browser_data.get("text", "")) > 50:
            title = browser_data.get("title", "")
            title = re.split(r"\s*[|\-—]\s*", title)[0].strip()
            return {
                "title": title,
                "author": browser_data.get("author", ""),
                "content": browser_data["text"][:max_chars],
            }

    # Fall back to trafilatura (for clipboard URLs without browser context)
    downloaded = trafilatura.fetch_url(url)
    text = trafilatura.extract(
        downloaded,
        include_comments=False,
        include_tables=False,
        no_fallback=False,
    ) or ""

    title = ""
    author = ""
    if downloaded:
        title, author, description = extract_html_meta(downloaded)

        # If trafilatura extracted nothing, try stripping HTML tags directly
        if not text:
            text = strip_html_to_text(downloaded)

        # Last resort: use meta description if we still have nothing
        if not text and description:
            text = description

    return {"title": title, "author": author, "content": text[:max_chars]}

# ── AI ────────────────────────────────────────────────────────────────────────

def build_prompt(content_type, data, tag_count):
    tag_instruction = f"array of {tag_count} broad topic tags — use reusable domain words that will appear across many notes (e.g. 'adhd', 'anxiety', 'design', 'productivity', 'ai'). Include specific tool or product names when they are central to the content (e.g. 'claude', 'figma', 'obsidian', 'raycast'). NOT descriptive phrases (NOT 'adhd-struggle', 'anxiety-provoking'). Single words preferred; hyphenate only if the concept genuinely needs two words (e.g. 'user-interface', 'mental-health')"

    if content_type == "tweet":
        return f"""Tweet by @{data['handle']} ({data['author']}):

{data['content']}

Return JSON with:
- "title": 3-6 word specific title capturing the topic
- "summary": 1-2 sentences capturing the key insight
- "tags": {tag_instruction}
- "type": one of: insight, resource, opinion, announcement, question"""

    elif content_type == "youtube":
        return f"""YouTube video: "{data['title']}" by {data['author']}

Description: {data['content']}

Return JSON with:
- "summary": 2-3 sentences on what the video covers and why it matters
- "points": array of 3-4 key takeaways
- "tags": {tag_instruction}
- "type": always "resource" """

    else:
        return f"""Article: "{data.get('title', '')}"
Author: {data.get('author', 'unknown')}

{data['content']}

Return JSON with:
- "summary": 2-3 sentences on what this covers and why it matters
- "points": array of 3-5 key takeaways
- "tags": {tag_instruction}
- "type": one of: article, resource, opinion, tutorial, reference"""


def call_ollama(prompt, model, base_url):
    resp = requests.post(
        f"{base_url}/api/chat",
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "format": "json",
            "stream": False,
        },
        timeout=60,
    )
    resp.raise_for_status()
    return json.loads(resp.json()["message"]["content"])


def call_openai(prompt, model, base_url, api_key):
    resp = requests.post(
        f"{base_url}/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
        },
        timeout=60,
    )
    resp.raise_for_status()
    return json.loads(resp.json()["choices"][0]["message"]["content"])


def call_anthropic(prompt, model, api_key):
    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        json={
            "model": model,
            "max_tokens": 512,
            "messages": [{"role": "user", "content": prompt + "\n\nReturn only valid JSON."}],
        },
        timeout=60,
    )
    resp.raise_for_status()
    return json.loads(resp.json()["content"][0]["text"])


def ai_process(content_type, data, config):
    llm = config["llm"]
    tag_count = config["capture"]["tag_count"]
    prompt = build_prompt(content_type, data, tag_count)
    provider = llm["provider"]

    if provider == "ollama":
        return call_ollama(prompt, llm["model"], llm["base_url"])
    elif provider == "openai":
        return call_openai(prompt, llm["model"], llm["base_url"], llm["api_key"])
    elif provider == "anthropic":
        return call_anthropic(prompt, llm["model"], llm["api_key"])
    else:
        print(f"❌ Unknown provider '{provider}'. Use: ollama, openai, anthropic")
        sys.exit(1)

# ── Note builder ──────────────────────────────────────────────────────────────

def build_note(url, content_type, data, ai):
    date = datetime.now().strftime("%Y-%m-%d")
    # Tweets get an AI-generated title; webpages and YouTube use the source title directly
    if content_type == "tweet":
        title = ai.get("title", "Untitled")
    else:
        title = data.get("title") or ai.get("title", "Untitled")
    summary = ai.get("summary", "")
    tags = [re.sub(r"\s+", "-", t.lower().strip()) for t in ai.get("tags", [])]
    points = ai.get("points", [])
    clip_type = ai.get("type", content_type)

    tags_yaml = "\n".join(f"  - {t}" for t in tags)
    tags_links = "  ".join(f"[[{t}]]" for t in tags)
    points_md = "\n".join(f"- {p}" for p in points) if points else ""

    if content_type == "tweet":
        handle = data.get("handle", "")
        author = data.get("author", "")
        body = f"""## Tweet

> {data['content']}
>
> — [{author}](https://x.com/{handle}) (@{handle})"""

    elif content_type == "youtube":
        author = data.get("author", "")
        body = f"## Video\n\n[{data.get('title', title)}]({url}) — {author}"
        if points_md:
            body += f"\n\n## Key Points\n\n{points_md}"

    else:
        author = data.get("author", "")
        body = f"## Source\n\n[{data.get('title', title)}]({url}){f' — {author}' if author else ''}"
        if points_md:
            body += f"\n\n## Key Points\n\n{points_md}"

    return title, f"""---
title: "{title}"
type: clip
subtype: {clip_type}
source: {url}
author: "{data.get('author', '')}"
tags:
{tags_yaml}
date: {date}
---

# {title}

## Summary

{summary}

{body}

## Notes

---

{tags_links}
"""

# ── Save ──────────────────────────────────────────────────────────────────────

def make_filename(title, date, fmt):
    safe = re.sub(r'[\\/*?:"<>|]', "", title).strip()
    slug = re.sub(r"\s+", "-", safe.lower())
    if fmt == "date-title":
        return f"{date}-{slug}.md"
    elif fmt == "title-date":
        return f"{safe} {date}.md"
    else:  # default: title only
        return f"{safe}.md"


def save(title, note, config):
    output = Path(config["vault_path"]) / config["output_folder"]
    output.mkdir(parents=True, exist_ok=True)

    date = datetime.now().strftime("%Y-%m-%d")
    fmt = config["capture"]["filename_format"]
    filename = make_filename(title, date, fmt)
    path = output / filename

    # Avoid collisions
    if path.exists():
        ts = datetime.now().strftime("%H%M%S")
        filename = make_filename(f"{title} {ts}", date, fmt)
        path = output / filename

    path.write_text(note, encoding="utf-8")
    return filename

# ── Main ──────────────────────────────────────────────────────────────────────

ICONS = {"tweet": "🐦", "youtube": "▶️", "webpage": "🌐"}

def fetch_for_url(url, config, from_browser=False):
    content_type = detect_type(url)
    if content_type == "tweet":
        data = fetch_tweet(url)
    elif content_type == "youtube":
        data = fetch_youtube(url)
    else:
        browser = config["browser"] if from_browser else None
        data = fetch_webpage(url, config["capture"]["max_content_chars"], browser)
    return content_type, data


def main():
    config = load_config()

    print("Reading browser tab...")
    browser_url = get_url(config["browser"])
    clip_url = subprocess.run(["pbpaste"], capture_output=True, text=True).stdout.strip()
    clip_url = clip_url if clip_url.startswith("http") else None

    if not browser_url and not clip_url:
        print("❌ No URL found. Open a browser tab or copy a URL to clipboard.")
        sys.exit(1)

    # Try browser URL first, fall back to clipboard if extraction fails
    url = browser_url or clip_url
    content_type = detect_type(url)
    print(f"{ICONS[content_type]} Fetching {content_type}...")

    try:
        content_type, data = fetch_for_url(url, config, from_browser=bool(browser_url))
    except Exception as e:
        data = {}

    # If browser tab yielded no content, silently retry with clipboard URL
    if not data.get("content") and content_type != "youtube":
        if clip_url and clip_url != browser_url:
            print(f"↩️ Retrying with clipboard URL...")
            url = clip_url
            content_type = detect_type(url)
            print(f"{ICONS[content_type]} Fetching {content_type}...")
            try:
                content_type, data = fetch_for_url(url, config, from_browser=False)
            except Exception as e:
                print(f"❌ Fetch failed: {e}")
                sys.exit(1)

    if not data.get("content") and content_type != "youtube":
        print("❌ Couldn't extract content. Page may require login.")
        sys.exit(1)

    print("⚙️ Summarizing...")

    try:
        ai = ai_process(content_type, data, config)
    except Exception as e:
        print(f"❌ AI failed: {e}")
        sys.exit(1)

    title, note = build_note(url, content_type, data, ai)
    filename = save(title, note, config)
    print(f"✅ Saved → {filename}")


if __name__ == "__main__":
    main()
