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

try:
    from markdownify import markdownify as md_convert
except ImportError:
    print("❌ Missing dependency: pip3 install markdownify")
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

def detect_domain(tags):
    """Use the first tag as domain. Tags are already ranked by relevance."""
    return tags[0] if tags else "general"


def html_to_markdown(html):
    """Convert HTML to Markdown, stripping nav/footer/sidebar noise."""
    markdown = md_convert(
        html,
        heading_style="ATX",
        strip=['nav', 'footer', 'aside', 'script', 'style', 'noscript', 'iframe'],
    )
    markdown = re.sub(r'\n{3,}', '\n\n', markdown)
    return markdown.strip()


def has_images_in_html(html):
    """Check if HTML contains img tags (excluding tracking pixels)."""
    imgs = re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', html, re.I)
    for src in imgs:
        if not re.search(r'(tracking|pixel|1x1|spacer|blank)', src, re.I):
            return True
    return False


def parse_published_date(date_str):
    """Parse ISO date string to YYYY-MM-DD format, or return None."""
    if not date_str:
        return None
    match = re.match(r'(\d{4}-\d{2}-\d{2})', date_str)
    return match.group(1) if match else None

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


def fetch_thread_from_browser(browser):
    """Extract a full thread from the active browser tab on X/Twitter.
    Returns thread data dict or None if not a thread / extraction fails."""
    js = "(function(){var articles=document.querySelectorAll('article[data-testid=tweet]');var tweets=[];var mainHandle='';var mainAuthor='';for(var i=0;i<articles.length;i++){var a=articles[i];var textEl=a.querySelector('[data-testid=tweetText]');var nameEl=a.querySelector('[data-testid=User-Name]');if(!textEl)continue;var text=textEl.innerText||'';var handle='';var author='';if(nameEl){var spans=nameEl.querySelectorAll('span');for(var j=0;j<spans.length;j++){var s=spans[j].textContent||'';if(s.indexOf('@')===0){handle=s.substring(1);break;}}var nameSpan=nameEl.querySelector('span');if(nameSpan)author=nameSpan.textContent||'';}if(tweets.length===0){mainHandle=handle;mainAuthor=author;}if(handle&&handle===mainHandle){tweets.push(text);}else if(tweets.length>0){break;}}return JSON.stringify({author:mainAuthor,handle:mainHandle,tweets:tweets,is_thread:tweets.length>1});})()"

    escaped_js = js.replace("\\", "\\\\").replace('"', '\\"')
    if browser == "chrome":
        jxa = f'var app=Application("Google Chrome");app.windows[0].activeTab().execute({{javascript:"{escaped_js}"}});'
    elif browser == "safari":
        jxa = f'var app=Application("Safari");app.doJavaScript("{escaped_js}",{{in:app.windows[0].currentTab()}});'
    else:
        return None

    result = subprocess.run(["osascript", "-l", "JavaScript"], input=jxa, capture_output=True, text=True)
    if result.returncode != 0:
        return None

    try:
        data = json.loads(result.stdout.strip())
        if not data.get("is_thread") or len(data.get("tweets", [])) < 2:
            return None
        return data
    except Exception as e:
        return None


def fetch_article_from_browser(browser):
    """Extract an X Article from the browser tab via JXA.
    Returns article data dict or None if not an article.
    
    Detection: X Articles have article[data-testid=tweet] with large content
    but NO [data-testid=tweetText] element (regular tweets have tweetText)."""
    js = "(function(){var tweetText=document.querySelector('[data-testid=tweetText]');if(tweetText)return JSON.stringify({is_article:false});var article=document.querySelector('article[data-testid=tweet]');if(!article||article.innerText.length<500)return JSON.stringify({is_article:false});var nameEl=article.querySelector('[data-testid=User-Name]');var handle='';var author='';if(nameEl){var spans=nameEl.querySelectorAll('span');for(var j=0;j<spans.length;j++){var s=spans[j].textContent||'';if(s.indexOf('@')===0){handle=s.substring(1);break;}}var nameSpan=nameEl.querySelector('span');if(nameSpan)author=nameSpan.textContent||'';}return JSON.stringify({is_article:true,author:author,handle:handle,html:article.innerHTML,textLen:article.innerText.length});})()"

    escaped_js = js.replace("\\", "\\\\").replace('"', '\\"')
    if browser == "chrome":
        jxa = f'var app=Application("Google Chrome");app.windows[0].activeTab().execute({{javascript:"{escaped_js}"}});'
        result = subprocess.run(["osascript", "-l", "JavaScript"], input=jxa, capture_output=True, text=True)
    elif browser == "safari":
        jxa = f'var app=Application("Safari");app.doJavaScript("{escaped_js}",{{in:app.windows[0].currentTab()}});'
        result = subprocess.run(["osascript", "-l", "JavaScript"], input=jxa, capture_output=True, text=True)
    else:
        return None

    if result.returncode != 0:
        return None

    try:
        data = json.loads(result.stdout.strip())
        if not data.get("is_article"):
            return None
        return data
    except Exception:
        return None


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
    Bypasses bot protection since the browser has already loaded the page.
    Returns HTML content for markdown conversion."""
    js = "(function(){var el=document.querySelector('article')||document.querySelector('[role=\"main\"]')||document.querySelector('main')||document.body;var title=document.title;var html=el.innerHTML;var metas=document.querySelectorAll('meta[name=\"author\"],meta[property=\"author\"],meta[property=\"article:author\"]');var author=metas.length?metas[0].getAttribute('content'):'';var pubMeta=document.querySelector('meta[property=\"article:published_time\"],meta[name=\"date\"]');var published=pubMeta?pubMeta.getAttribute('content'):'';var scripts=document.querySelectorAll('script[type=\"application/ld+json\"]');for(var i=0;i<scripts.length;i++){try{var data=JSON.parse(scripts[i].textContent);if(!author&&data.author){author=typeof data.author==='string'?data.author:(data.author.name||'');}if(!published&&data.datePublished)published=data.datePublished;if(Array.isArray(data['@graph'])){for(var j=0;j<data['@graph'].length;j++){var item=data['@graph'][j];if(!author&&item.author)author=item.author.name||'';if(!published&&item.datePublished)published=item.datePublished;}}}catch(e){}}return JSON.stringify({title:title,html:html,author:author,published:published});})()"

    escaped_js = js.replace("\\", "\\\\").replace('"', '\\"')
    if browser == "chrome":
        # Use JXA for Chrome (AppleScript JS execution is blocked)
        jxa = f'var app=Application("Google Chrome");app.windows[0].activeTab().execute({{javascript:"{escaped_js}"}});'
        result = subprocess.run(["osascript", "-l", "JavaScript"], input=jxa, capture_output=True, text=True)
    elif browser == "safari":
        # AppleScript works fine for Safari
        jxa = f'var app=Application("Safari");app.doJavaScript("{escaped_js}",{{in:app.windows[0].currentTab()}});'
        result = subprocess.run(["osascript", "-l", "JavaScript"], input=jxa, capture_output=True, text=True)
    else:
        return None

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
        if browser_data and len(browser_data.get("html", "")) > 100:
            title = browser_data.get("title", "")
            title = re.split(r"\s*[|\-—]\s*", title)[0].strip()
            html = browser_data["html"]
            content = html_to_markdown(html)
            return {
                "title": title,
                "author": browser_data.get("author", ""),
                "content": content[:max_chars],
                "published": parse_published_date(browser_data.get("published", "")),
                "has_images": has_images_in_html(html),
            }

    # Fall back to trafilatura (for clipboard URLs without browser context)
    downloaded = trafilatura.fetch_url(url)
    
    # Try to get HTML output first for better markdown conversion
    html_content = trafilatura.extract(
        downloaded,
        include_comments=False,
        include_tables=True,
        include_links=True,
        include_images=True,
        output_format='html',
        no_fallback=False,
    ) or ""
    
    content = ""
    has_images = False
    if html_content:
        has_images = has_images_in_html(html_content)
        content = html_to_markdown(html_content)
    
    # Fall back to plain text if HTML extraction failed
    if not content:
        content = trafilatura.extract(
            downloaded,
            include_comments=False,
            include_tables=False,
            no_fallback=False,
        ) or ""

    title = ""
    author = ""
    published = None
    if downloaded:
        title, author, description = extract_html_meta(downloaded)
        
        # Try to extract published date from raw HTML
        pub_match = re.search(
            r'<meta[^>]+(?:property=["\']article:published_time["\']|name=["\']date["\'])[^>]+content=["\']([^"\']+)["\']',
            downloaded, re.I
        ) or re.search(
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property=["\']article:published_time["\']|name=["\']date["\'])',
            downloaded, re.I
        )
        if pub_match:
            published = parse_published_date(pub_match.group(1))
        
        # Try JSON-LD for published date
        if not published:
            ld_match = re.search(r'"datePublished"\s*:\s*"([^"]+)"', downloaded)
            if ld_match:
                published = parse_published_date(ld_match.group(1))

        # If trafilatura extracted nothing, try stripping HTML tags directly
        if not content:
            content = strip_html_to_text(downloaded)

        # Last resort: use meta description if we still have nothing
        if not content and description:
            content = description

    return {
        "title": title,
        "author": author,
        "content": content[:max_chars],
        "published": published,
        "has_images": has_images,
    }

# ── AI ────────────────────────────────────────────────────────────────────────

def build_prompt(content_type, data, tag_count):
    tag_instruction = f"array of {tag_count} broad topic tags — single words only, split compound ideas into separate tags (e.g. 'growth' and 'marketing' NOT 'growth-marketing'; 'ai' and 'tools' NOT 'ai-tools'; 'productivity' NOT 'productivity-hacks'). Use reusable domain words that will appear across many notes (e.g. 'marketing', 'ai', 'productivity', 'design', 'growth'). Include specific product names only when central (e.g. 'claude', 'figma'). NEVER join words with hyphens unless it is a single well-known concept (e.g. 'machine-learning', 'mental-health')"

    if content_type == "tweet":
        return f"""Tweet by @{data['handle']} ({data['author']}):

{data['content']}

Return JSON with:
- "title": 3-6 word specific title capturing the topic
- "summary": 1-2 sentences capturing the key insight
- "tags": {tag_instruction}
- "type": one of: insight, resource, opinion, announcement, question"""

    elif content_type == "thread":
        return f"""X/Twitter thread by @{data['handle']} ({data['author']}), {data['tweet_count']} tweets:

{data['content']}

Return JSON with:
- "title": 3-6 word specific title capturing the thread's main topic
- "summary": 2-4 sentences synthesizing the thread's full argument or narrative
- "points": array of 3-5 key takeaways from the thread
- "tags": {tag_instruction}
- "type": one of: insight, resource, opinion, announcement, tutorial, thread"""

    elif content_type == "article":
        return f"""X/Twitter Article by @{data.get('handle', '')} ({data.get('author', '')}):

{data['content']}

Return JSON with:
- "title": 3-8 word specific title capturing the article's main topic
- "summary": 2-4 sentences synthesizing the article's argument or thesis
- "points": array of 3-7 key takeaways from the article
- "tags": {tag_instruction}
- "type": one of: article, insight, opinion, tutorial, resource"""

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
    # Tweets, threads, and articles get an AI-generated title; webpages and YouTube use the source title
    if content_type in ("tweet", "thread", "article"):
        title = ai.get("title", "Untitled")
    else:
        title = data.get("title") or ai.get("title", "Untitled")
    summary = ai.get("summary", "")
    tags = [re.sub(r"\s+", "-", t.lower().strip()) for t in ai.get("tags", [])]
    points = ai.get("points", [])
    clip_type = ai.get("type", content_type)
    
    # Wiki integration fields
    domain = detect_domain(tags)
    has_images = data.get("has_images", False)
    published = data.get("published")

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

    elif content_type == "thread":
        handle = data.get("handle", "")
        author = data.get("author", "")
        tweets = data.get("tweets", [])
        thread_quotes = "\n>\n".join(f"> {t}" for t in tweets)
        body = f"""## Thread ({len(tweets)} tweets)

{thread_quotes}
>
> — [{author}](https://x.com/{handle}) (@{handle})"""
        if points_md:
            body += f"\n\n## Key Points\n\n{points_md}"

    elif content_type == "article":
        handle = data.get("handle", "")
        author = data.get("author", "")
        body = f"## Article\n\n[X Article by {author}]({url}) — @{handle}"
        if points_md:
            body += f"\n\n## Key Points\n\n{points_md}"
        article_content = data.get("content", "")
        if article_content:
            truncated = article_content[:5000]
            body += f"\n\n## Full Content\n\n{truncated}"

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

    # Build optional frontmatter fields
    optional_fields = ""
    if published:
        optional_fields += f"published: {published}\n"
    optional_fields += f"has_images: {str(has_images).lower()}\n"

    return title, f"""---
title: "{title}"
type: clip
subtype: {clip_type}
source: {url}
author: "{data.get('author', '')}"
tags:
{tags_yaml}
date: {date}
{optional_fields}processed: false
domain: {domain}
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

ICONS = {"tweet": "🐦", "thread": "🧵", "youtube": "▶️", "webpage": "🌐", "article": "📝"}

def fetch_for_url(url, config, from_browser=False):
    content_type = detect_type(url)
    if content_type == "tweet":
        if from_browser:
            # Try article extraction first (articles have no tweetText element)
            article_data = fetch_article_from_browser(config["browser"])
            if article_data:
                max_chars = config["capture"]["max_content_chars"]
                html = article_data["html"]
                content = html_to_markdown(html)
                return "article", {
                    "author": article_data["author"],
                    "handle": article_data.get("handle", ""),
                    "title": "",
                    "content": content[:max_chars],
                    "has_images": has_images_in_html(html),
                }

            # Then try thread extraction
            thread_data = fetch_thread_from_browser(config["browser"])
            if thread_data:
                max_chars = config["capture"]["max_content_chars"]
                tweets = thread_data["tweets"]
                content = "\n\n---\n\n".join(
                    f"[{i+1}/{len(tweets)}] {t}" for i, t in enumerate(tweets)
                )
                return "thread", {
                    "author": thread_data["author"],
                    "handle": thread_data["handle"],
                    "content": content[:max_chars],
                    "tweet_count": len(tweets),
                    "tweets": tweets,
                }

        # Fall back to regular tweet via oembed
        data = fetch_tweet(url)
        return content_type, data
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

    if content_type == "thread":
        print(f"🧵 Thread detected ({data.get('tweet_count', '?')} tweets)")

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
