#!/usr/bin/env python3

# Required parameters:
# @raycast.schemaVersion 1
# @raycast.title Save to Vault
# @raycast.mode compact
# @raycast.packageName Obsidian

# Optional parameters:
# @raycast.icon 🗂️
# @raycast.description Active browser tab → AI summary + tags → Obsidian vault

import os
import subprocess
import sys
import json
import re
from datetime import datetime
from pathlib import Path
from html import unescape
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

# ── Auto-bootstrap venv ───────────────────────────────────────────────────────
# Portability strategy: on first run, create a .venv next to the script and
# install our deps into it, then re-exec ourselves with the venv's python.
# After that, every run uses the venv. No PATH games, no PEP 668 errors, no
# Homebrew-vs-Apple Python confusion.

REQUIRED_PACKAGES = ["requests", "trafilatura", "markdownify", "youtube-transcript-api"]
PACKAGE_IMPORTS = {
    "requests": "requests",
    "trafilatura": "trafilatura",
    "markdownify": "markdownify",
    "youtube-transcript-api": "youtube_transcript_api",
}
_SCRIPT_DIR = Path(__file__).resolve().parent
_VENV_DIR = _SCRIPT_DIR / ".venv"
_VENV_PYTHON = _VENV_DIR / "bin" / "python3"


def _install_packages(packages):
    try:
        subprocess.check_call(
            [str(_VENV_PYTHON), "-m", "pip", "install", "--quiet", "--disable-pip-version-check", *packages],
        )
    except subprocess.CalledProcessError as e:
        # Bootstrap failed (offline, pip down, etc). Leave the venv so a
        # retry doesn't have to recreate it; user can rerun and pip resumes.
        print(f"❌ Bootstrap failed during pip install: {e}", file=sys.stderr)
        print("    Try running the script again once you have network access.", file=sys.stderr)
        sys.exit(1)


def _missing_required_packages():
    import importlib.util

    missing = []
    for package, module in PACKAGE_IMPORTS.items():
        if importlib.util.find_spec(module) is None:
            missing.append(package)
    return missing


def _bootstrap_venv():
    """Create the venv and install dependencies. Runs once, ever."""
    import venv

    print("⚙️  First-run setup: creating venv and installing dependencies...", file=sys.stderr)
    print("    (this takes 10-30 seconds, only happens once)", file=sys.stderr)
    venv.create(_VENV_DIR, with_pip=True, clear=False, upgrade_deps=False)
    _install_packages(REQUIRED_PACKAGES)


def _ensure_venv():
    """Make sure we're running inside our venv. Bootstrap and re-exec if not."""
    # Already inside our venv? Continue with the real script.
    try:
        if Path(sys.executable).resolve() == _VENV_PYTHON.resolve():
            missing = _missing_required_packages()
            if missing:
                print(f"⚙️  Installing missing dependencies: {', '.join(missing)}", file=sys.stderr)
                _install_packages(missing)
                script = str(Path(__file__).resolve())
                os.execv(str(_VENV_PYTHON), [str(_VENV_PYTHON), script, *sys.argv[1:]])
            return
    except OSError:
        pass

    script = str(Path(__file__).resolve())

    # Venv exists from a previous run. Re-exec immediately, no install.
    if _VENV_PYTHON.exists():
        os.execv(str(_VENV_PYTHON), [str(_VENV_PYTHON), script, *sys.argv[1:]])
        return  # only reachable if execv was mocked or somehow failed

    # First run ever. Build the venv, then re-exec.
    _bootstrap_venv()
    os.execv(str(_VENV_PYTHON), [str(_VENV_PYTHON), script, *sys.argv[1:]])
    return  # same as above


# Bootstrap is invoked from main() so that importing this module (for tests
# or external tooling) doesn't trigger a venv build. The real entry point
# always calls _ensure_venv() before doing anything else.

# ── Dependencies (guaranteed present after _ensure_venv) ──────────────────────
# These imports succeed at runtime because main() runs _ensure_venv() first,
# which re-execs us inside the venv that has them installed.
try:
    import requests
    import trafilatura
    from markdownify import markdownify as md_convert
    from youtube_transcript_api import YouTubeTranscriptApi
except ImportError:
    # Imported outside the venv (e.g. from a test harness that mocks these).
    # We don't fail here because the real entry point will bootstrap before
    # ever using them.
    pass

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


def clean_chrome(markdown):
    """Generic cleanup for content-platform UI chrome (X, Substack, Medium,
    Ghost, generic blogs). Strips:
      - Image markdown (profile avatars, header images, inline)
      - Empty link skeletons left by image stripping
      - Standalone engagement counts (8.6K, 184M, 484)
      - Subscribe / Unsubscribe / Restack / Share / Follow nudges
      - Author/handle links, analytics links
      - X-specific: timestamp permalinks, View quotes/replies, ·/• separators,
        Relevant / For You / Following tab headers
      - Substack: sponsor blocks, "X Likes∙", "Y Restacks", date stamps,
        "reader-supported publication" footer
      - Generic: Previous / Next nav, "Edited by ...", "Find this interesting?"
    Safe to apply to any article-shaped content."""
    # Strip inline + standalone images first (covers most platform chrome)
    markdown = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", markdown)

    # Strip multi-line sponsor blocks. Substack pattern is:
    #   **Sponsored by [Name](url)**: <paragraph>
    #   (optional image)
    # Catch the bold-prefixed paragraph; the image after it is already gone.
    markdown = re.sub(
        r"\*\*\s*Sponsored\s+by[^\n]*\*\*[^\n]*",
        "",
        markdown,
        flags=re.IGNORECASE,
    )
    # Also catch unbolded "Sponsored by ..." lines
    markdown = re.sub(
        r"^Sponsored\s+by[^\n]*$",
        "",
        markdown,
        flags=re.MULTILINE | re.IGNORECASE,
    )

    lines = []
    for raw in markdown.split("\n"):
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped:
            lines.append(line)
            continue
        # Standalone engagement counts: "8.6K", "184M", "1,234", "484"
        if re.fullmatch(r"[\d,.]+\s*[KMB]?", stripped, re.I):
            continue
        # Subscribe / Unsubscribe / Restack nudges
        if re.fullmatch(r"(Click to )?(Sub|Unsub|Re)scribe.*", stripped, re.I):
            continue
        # Single-word UI buttons (common across platforms)
        if re.fullmatch(
            r"(Share|Like|Subscribe|Restack|Previous|Next|Comment|Follow|Following)",
            stripped,
            re.I,
        ):
            continue
        # Bare author/handle links: "[NAME](/handle)" or "[@handle](/handle)"
        if re.fullmatch(r"\[@?[^\]]+\]\(/[\w-]+\)", stripped):
            continue
        # Analytics link
        if re.fullmatch(r"\[[^\]]+\]\([^)]*/analytics\)", stripped):
            continue
        # Empty link skeleton left after image-strip: "[](href)"
        if re.fullmatch(r"\[\s*\]\([^)]+\)", stripped):
            continue
        # X timestamp permalink: "[7:23 AM · May 15, 2026](/handle/status/123)"
        if re.fullmatch(
            r"\[\s*\d{1,2}:\d{2}\s*[AP]M\s*[·•]\s*\w+\s+\d{1,2},?\s+\d{4}\s*\]\([^)]+\)",
            stripped,
        ):
            continue
        # View quotes / View replies / View tweet
        if re.fullmatch(r"\[\s*View\s+\w+\s*\]\([^)]+\)", stripped):
            continue
        # Standalone middle-dot separator
        if re.fullmatch(r"[·•∙]", stripped):
            continue
        # X tab headers
        if re.fullmatch(r"(Relevant|For You|Following)", stripped):
            continue
        # Substack-style standalone date: "May 14, 2026"
        if re.fullmatch(r"\w+\s+\d{1,2},?\s+\d{4}", stripped):
            continue
        # Substack engagement summary: "484 Likes∙", "33 Restacks"
        if re.fullmatch(r"\d+\s*Likes?\s*[∙·•]?", stripped, re.I):
            continue
        if re.fullmatch(r"\[?\s*\d+\s+Restacks?\s*\]?\(?[^)]*\)?", stripped, re.I):
            continue
        # "Find this interesting? Subscribe to my blog!" / "join us if you're into..."
        if re.match(r"^(Find this interesting\?|Join us if)", stripped, re.I):
            continue
        # Editor credit: "*Edited by [Name](url).*"
        if re.fullmatch(r"\*?\s*Edited\s+by\s+\[[^\]]+\]\([^)]+\)\.?\s*\*?", stripped, re.I):
            continue
        # Substack "reader-supported publication" footer
        if re.search(r"reader-supported publication", stripped, re.I):
            continue
        lines.append(line)
    cleaned = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


# Backward-compat alias for existing call sites and tests
clean_x_chrome = clean_chrome


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
    if re.search(r"(youtube\.com/(watch|shorts|embed)|youtu\.be/)", url):
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
    but NO [data-testid=tweetText] element (regular tweets have tweetText).

    Before returning HTML we clone the article and strip X-specific UI chrome
    (author header, subscribe button, engagement counts, action bar) so the
    LLM never sees them. Author/handle are read BEFORE stripping so we keep
    them as separate fields."""
    js = (
        "(function(){"
        "var tweetText=document.querySelector('[data-testid=tweetText]');"
        "if(tweetText)return JSON.stringify({is_article:false});"
        "var article=document.querySelector('article[data-testid=tweet]');"
        "if(!article||article.innerText.length<500)return JSON.stringify({is_article:false});"
        # Read author/handle before stripping
        "var nameEl=article.querySelector('[data-testid=User-Name]');"
        "var handle='';var author='';"
        "if(nameEl){var spans=nameEl.querySelectorAll('span');"
        "for(var j=0;j<spans.length;j++){var s=spans[j].textContent||'';"
        "if(s.indexOf('@')===0){handle=s.substring(1);break;}}"
        "var nameSpan=nameEl.querySelector('span');"
        "if(nameSpan)author=nameSpan.textContent||'';}"
        # Clone and strip X UI noise
        "var clone=article.cloneNode(true);"
        "var noise=["
        "'[data-testid=User-Name]',"               # author/handle header
        "'[role=group]',"                          # action bar (reply/retweet/like)
        "'[data-testid=caret]',"                   # ... menu
        "'[data-testid=app-text-transition-container]',"  # animated counters
        "'[aria-label*=\"reposts\"]',"             # retweet count
        "'[aria-label*=\"Repost\"]',"
        "'[aria-label*=\"likes\"]',"               # like count
        "'[aria-label*=\"Like\"]',"
        "'[aria-label*=\"replies\"]',"             # reply count
        "'[aria-label*=\"Repl\"]',"
        "'[aria-label*=\"views\"]',"               # view count
        "'[aria-label*=\"View\"]',"
        "'[aria-label*=\"Bookmark\"]',"
        "'a[href$=\"/analytics\"]',"               # analytics link
        "'[data-testid*=\"ubscribe\"]',"           # Subscribe / Unsubscribe
        "'[data-testid=tweetButtonInline]'"
        "];"
        "for(var k=0;k<noise.length;k++){"
        "var nodes=clone.querySelectorAll(noise[k]);"
        "for(var l=0;l<nodes.length;l++)nodes[l].remove();}"
        "return JSON.stringify({is_article:true,author:author,handle:handle,html:clone.innerHTML,textLen:clone.innerText.length});"
        "})()"
    )

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


def fetch_long_tweet_from_browser(browser, min_chars=800):
    """Extract a long-form tweet's full body from the browser.

    Why this exists: X Premium tweets can be up to 25k chars. The oembed API
    truncates them to a snippet, so we lose almost all the content. This path
    reads the rendered tweetText element directly from the DOM, giving us the
    real body for posts like multi-point lists or essay-style tweets.

    Distinguishes from regular tweets by content length (>= min_chars).
    Distinguishes from X Articles (which lack tweetText entirely).
    Distinguishes from threads (which have multiple tweetText elements).
    """
    js = (
        "(function(){"
        "var nodes=document.querySelectorAll('[data-testid=tweetText]');"
        "if(nodes.length!==1)return JSON.stringify({is_long:false});"
        "var text=nodes[0].innerText||'';"
        "if(text.length<MIN_CHARS)return JSON.stringify({is_long:false});"
        "var article=document.querySelector('article[data-testid=tweet]');"
        "var nameEl=article?article.querySelector('[data-testid=User-Name]'):null;"
        "var handle='';var author='';"
        "if(nameEl){var spans=nameEl.querySelectorAll('span');"
        "for(var j=0;j<spans.length;j++){var s=spans[j].textContent||'';"
        "if(s.indexOf('@')===0){handle=s.substring(1);break;}}"
        "var nameSpan=nameEl.querySelector('span');if(nameSpan)author=nameSpan.textContent||'';}"
        "return JSON.stringify({is_long:true,author:author,handle:handle,content:text,length:text.length});"
        "})()"
    ).replace("MIN_CHARS", str(min_chars))

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
        if not data.get("is_long"):
            return None
        return data
    except Exception:
        return None


def extract_youtube_video_id(url):
    parsed = urlparse(url)
    host = parsed.netloc.lower().removeprefix("www.")

    if host == "youtu.be":
        return parsed.path.strip("/").split("/")[0]

    if host.endswith("youtube.com"):
        if parsed.path == "/watch":
            return parse_qs(parsed.query).get("v", [""])[0]
        for prefix in ("/shorts/", "/embed/"):
            if parsed.path.startswith(prefix):
                return parsed.path[len(prefix):].strip("/").split("/")[0]

    return ""


def transcript_entries_to_markdown(transcript):
    if hasattr(transcript, "to_raw_data"):
        transcript = transcript.to_raw_data()

    chunks = []
    current = []
    current_len = 0

    for entry in transcript or []:
        if isinstance(entry, dict):
            text = entry.get("text", "")
        else:
            text = getattr(entry, "text", "")

        text = unescape(text)
        text = re.sub(r"\s+", " ", text).strip()
        if not text or re.fullmatch(r"\[[^\]]+\]", text):
            continue

        if current and current_len + len(text) > 900:
            chunks.append(" ".join(current))
            current = []
            current_len = 0

        current.append(text)
        current_len += len(text) + 1

    if current:
        chunks.append(" ".join(current))

    return "\n\n".join(chunks).strip()


def fetch_youtube_transcript(video_id):
    if not video_id or "YouTubeTranscriptApi" not in globals():
        return ""

    preferred_languages = ["en", "en-US", "en-GB"]
    fetch_attempts = []

    if hasattr(YouTubeTranscriptApi, "get_transcript"):
        fetch_attempts.append(lambda: YouTubeTranscriptApi.get_transcript(video_id, languages=preferred_languages))

    fetch_attempts.append(lambda: YouTubeTranscriptApi().fetch(video_id, languages=preferred_languages))
    fetch_attempts.append(lambda: YouTubeTranscriptApi().fetch(video_id))

    for attempt in fetch_attempts:
        try:
            transcript = attempt()
            markdown = transcript_entries_to_markdown(transcript)
            if markdown:
                return markdown
        except Exception:
            continue

    return ""


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

    video_id = extract_youtube_video_id(url)
    transcript = fetch_youtube_transcript(video_id)

    if transcript:
        return {
            "title": title,
            "author": author,
            "content": transcript,
            "description": desc,
            "video_id": video_id,
            "content_source": "transcript",
            "transcript_available": True,
            "has_images": False,
        }

    return {
        "title": title,
        "author": author,
        "content": desc,
        "description": desc,
        "video_id": video_id,
        "content_source": "description",
        "transcript_available": False,
        "has_images": False,
    }


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


def fetch_webpage(url, browser=None):
    """Returns the full article content (Web Clipper parity). Truncation for
    LLM context happens later in ai_process, not here."""
    # Try direct browser extraction first (bypasses bot protection)
    if browser:
        browser_data = fetch_from_browser(browser)
        if browser_data and len(browser_data.get("html", "")) > 100:
            title = browser_data.get("title", "")
            title = re.split(r"\s*[|\-—]\s*", title)[0].strip()
            html = browser_data["html"]
            content = clean_chrome(html_to_markdown(html))
            return {
                "title": title,
                "author": browser_data.get("author", ""),
                "content": content,
                "published": parse_published_date(browser_data.get("published", "")),
                # clean_chrome strips images, so the saved note has none.
                "has_images": False,
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
        content = clean_chrome(html_to_markdown(html_content))

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
        "content": content,
        "published": published,
        # clean_chrome already stripped images from this content path; the
        # has_images flag reflects what's in the saved note, not what was
        # on the source page.
        "has_images": False,
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
        return f"""X/Twitter long-form post by @{data.get('handle', '')} ({data.get('author', '')}):

{data['content']}

Return JSON with:
- "title": 3-8 word title that captures the SCOPE of the post. If the post is a list of N distinct items or observations, name the scope (e.g. "30+ AI Agent Opportunities", "10 Lessons from Failed Startups"), do NOT pick the first item as the title.
- "summary": 2-4 sentences synthesizing the post's full argument or the breadth of ideas it covers
- "points": array of key takeaways. CRITICAL: if the post has explicit numbered or sectioned structure (Roman numerals like "I, II, III", numbered headers "1.", "2.", "3.", or any explicit section breaks) you MUST preserve those exact sections as the points, one per section, in order. Each point should be a specific claim (not a generic restatement). Otherwise, return 5-12 takeaways: 10-12 for long lists of distinct observations, 5-7 for a single argument with supporting points. Do not include questions, hedges, or generic platitudes.
- "tags": {tag_instruction}
- "type": one of: article, insight, opinion, tutorial, resource"""

    elif content_type == "youtube":
        source_label = "Transcript" if data.get("content_source") == "transcript" else "Description"
        return f"""YouTube video: "{data['title']}" by {data['author']}

{source_label}: {data['content']}

Return JSON with:
- "summary": 2-3 sentences on what the video covers and why it matters
- "points": array of 3-4 key takeaways
- "tags": {tag_instruction}
- "type": always "resource" """

    else:
        return f"""Article: "{data.get('title', '')}"
Author: {data.get('author', 'unknown')}

{data['content']}

Return a single JSON OBJECT with EXACTLY these four top-level keys: summary, points, tags, type. Do NOT include any other keys. Do NOT include the strings "tags", "type", "summary", or "points" inside the points array.

Field requirements:
- summary (string): 2-3 sentences on what this covers and why it matters.
- points (array of strings): 5-12 distinct, specific takeaways. Each item must be a complete sentence claim, NOT a JSON field name. If the article has explicit sections (numbered or headed), preserve those exact sections one-per-point.
- tags (array of strings): {tag_instruction}
- type (string): one of: article, resource, opinion, tutorial, reference

Example shape (do not copy the values, just the structure):
{{"summary": "One to three sentences here.", "points": ["Specific claim 1.", "Specific claim 2.", "Specific claim 3."], "tags": ["topic", "domain"], "type": "article"}}"""


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
            # 4096 leaves room for a long title + summary + 5-12 detailed
            # points + tags + JSON scaffolding. 512 was way too low and
            # truncated the response mid-list, causing the "1 key point"
            # symptom on long articles.
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": prompt + "\n\nReturn only valid JSON."}],
        },
        timeout=60,
    )
    resp.raise_for_status()
    return json.loads(resp.json()["content"][0]["text"])


_JSON_FIELD_NAMES = {
    "title", "summary", "points", "tags", "type", "subtype", "domain", "author",
}


def _sanitize_ai_response(ai):
    """Local Ollama models sometimes flatten the JSON structure and put field
    names (tags, type, etc.) inside the points array as literal strings.
    Drop those plus JSON-literal stragglers so the final note isn't polluted."""
    if not isinstance(ai, dict):
        return ai

    points = ai.get("points")
    if isinstance(points, list):
        cleaned = []
        for p in points:
            if not isinstance(p, str):
                continue
            s = p.strip().rstrip(":").rstrip(",").strip()
            if not s:
                continue
            # Skip literal field names
            if s.lower() in _JSON_FIELD_NAMES:
                continue
            # Skip strings that look like raw JSON literals: ["x","y"] or "x"
            if re.fullmatch(r"\[.*\]", s) or re.fullmatch(r'".*"', s):
                continue
            # Skip values that are single-word "type" values
            if s.lower() in {"article", "insight", "opinion", "resource", "tutorial", "reference"}:
                continue
            cleaned.append(p)
        ai["points"] = cleaned

    # If tags came back as a string instead of a list, try to parse it
    tags = ai.get("tags")
    if isinstance(tags, str):
        try:
            parsed = json.loads(tags)
            if isinstance(parsed, list):
                ai["tags"] = parsed
        except Exception:
            pass

    return ai


def ai_process(content_type, data, config):
    """Run the LLM. Stored data["content"] may be arbitrarily long (full article
    captured for Web Clipper parity). We truncate ONLY for the prompt so the
    LLM context stays bounded. The note keeps the full content untouched."""
    llm = config["llm"]
    tag_count = config["capture"]["tag_count"]
    llm_data = dict(data)

    # Article-like content (long-form posts, threads, full webpages, and
    # YouTube transcripts) gets a bigger budget; short tweets and video
    # descriptions stay small.
    if (
        content_type in ("article", "thread", "webpage")
        or (content_type == "youtube" and llm_data.get("content_source") == "transcript")
    ):
        llm_max = config["capture"].get("article_max_chars", 16000)
    else:
        llm_max = config["capture"].get("max_content_chars", 3000)

    if "content" in llm_data and isinstance(llm_data["content"], str):
        llm_data["content"] = llm_data["content"][:llm_max]

    prompt = build_prompt(content_type, llm_data, tag_count)
    provider = llm["provider"]

    if provider == "ollama":
        result = call_ollama(prompt, llm["model"], llm["base_url"])
    elif provider == "openai":
        result = call_openai(prompt, llm["model"], llm["base_url"], llm["api_key"])
    elif provider == "anthropic":
        result = call_anthropic(prompt, llm["model"], llm["api_key"])
    else:
        print(f"❌ Unknown provider '{provider}'. Use: ollama, openai, anthropic")
        sys.exit(1)
    return _sanitize_ai_response(result)

# ── Note builder ──────────────────────────────────────────────────────────────

def interim_title(content_type, data):
    """Best-effort title before the LLM has weighed in. Used for stub notes."""
    if content_type == "tweet":
        text = (data.get("content") or "").strip().replace("\n", " ")
        if text:
            snippet = text[:50].rstrip()
            return snippet + ("..." if len(text) > 50 else "")
        handle = data.get("handle") or "unknown"
        return f"Tweet by @{handle}"
    if content_type == "thread":
        handle = data.get("handle") or "unknown"
        count = data.get("tweet_count", len(data.get("tweets") or []))
        return f"Thread by @{handle} ({count} tweets)"
    if content_type == "article":
        handle = data.get("handle") or "unknown"
        return f"X Article by @{handle}"
    return data.get("title") or "Untitled"


def build_note(url, content_type, data, ai):
    """Render the full markdown note. If `ai` is empty/None this is a stub
    (no summary, no tags, processed: false) that the background processor
    will rewrite once the LLM call completes."""
    ai = ai or {}
    is_stub = not ai

    date = datetime.now().strftime("%Y-%m-%d")
    # Tweets, threads, and articles get an AI-generated title; webpages and YouTube use the source title.
    # Stubs always use the interim title so filenames stay stable across enrichment.
    if is_stub:
        title = interim_title(content_type, data)
    elif content_type in ("tweet", "thread", "article"):
        title = ai.get("title", interim_title(content_type, data))
    else:
        title = data.get("title") or ai.get("title", "Untitled")
    summary = ai.get("summary", "")
    tags = [re.sub(r"\s+", "-", t.lower().strip()) for t in ai.get("tags", [])]
    points = ai.get("points", [])
    clip_type = ai.get("type", content_type) if not is_stub else content_type

    # Wiki integration fields
    domain = detect_domain(tags) if tags else "unprocessed"
    has_images = data.get("has_images", False)
    published = data.get("published")

    if tags:
        tags_block = "tags:\n" + "\n".join(f"  - {t}" for t in tags)
    else:
        tags_block = "tags: []"
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
            # Full content, no truncation (Web Clipper parity)
            body += f"\n\n## Full Content\n\n{article_content}"

    elif content_type == "youtube":
        author = data.get("author", "")
        body = f"## Video\n\n[{data.get('title', title)}]({url}) — {author}"
        if points_md:
            body += f"\n\n## Key Points\n\n{points_md}"
        description = data.get("description", "")
        video_content = data.get("content", "")
        content_source = data.get("content_source", "description")
        if description and content_source == "transcript":
            body += f"\n\n## Description\n\n{description}"
        if video_content:
            heading = "Transcript" if content_source == "transcript" else "Description"
            body += f"\n\n## {heading}\n\n{video_content}"

    else:
        author = data.get("author", "")
        body = f"## Source\n\n[{data.get('title', title)}]({url}){f' — {author}' if author else ''}"
        if points_md:
            body += f"\n\n## Key Points\n\n{points_md}"
        # Webpage clips get the full article body too (Web Clipper parity)
        webpage_content = data.get("content", "")
        if webpage_content:
            # Drop a leading H1 that duplicates the note's own title.
            webpage_content = re.sub(
                r"^\s*#\s+[^\n]+\n+", "", webpage_content, count=1
            )
            body += f"\n\n## Article\n\n{webpage_content}"

    # Build optional frontmatter fields
    optional_fields = ""
    if published:
        optional_fields += f"published: {published}\n"
    optional_fields += f"has_images: {str(has_images).lower()}\n"
    if content_type == "youtube":
        optional_fields += f"content_source: {data.get('content_source', 'description')}\n"
        optional_fields += f"transcript_available: {str(data.get('transcript_available', False)).lower()}\n"

    # State machine for wiki-ingest contract:
    #   Stub (AI pending):       enriched: false   (no processed field)
    #   Enriched (ready):        enriched: true    processed: false
    #   After wiki-ingest:       enriched: true    processed: true   (ingest flips it)
    #
    # The Wiki/CLAUDE.md ingest spec filters on `processed: false`. Stubs
    # don't have that field, so wiki-ingest naturally skips them until the
    # background AI step finishes and writes the full frontmatter.
    if is_stub:
        state_fields = "enriched: false\n"
    else:
        state_fields = "enriched: true\nprocessed: false\n"

    # Escape any literal double quotes in the title so the YAML stays valid
    title_escaped = title.replace('"', '\\"')
    author_escaped = (data.get("author") or "").replace('"', '\\"')

    summary_block = f"## Summary\n\n{summary}\n\n" if summary else ""
    tags_links_block = f"\n{tags_links}\n" if tags_links else ""

    return title, f"""---
title: "{title_escaped}"
type: clip
subtype: {clip_type}
source: {url}
author: "{author_escaped}"
{tags_block}
date: {date}
{optional_fields}{state_fields}domain: {domain}
---

# {title}

{summary_block}{body}

## Notes

---
{tags_links_block}"""

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


def output_dir(config):
    return Path(config["vault_path"]) / config["output_folder"]


def pending_dir(config):
    return output_dir(config) / "_pending"


TRACKING_QUERY_PREFIXES = ("utm_",)
TRACKING_QUERY_KEYS = {
    "fbclid",
    "gclid",
    "igshid",
    "mc_cid",
    "mc_eid",
    "si",
}


def canonicalize_url(url):
    """Normalize source URLs so dedupe works across tracking params and
    common video/share URL variants."""
    parsed = urlparse((url or "").strip())
    if not parsed.scheme or not parsed.netloc:
        return url.strip()

    scheme = parsed.scheme.lower()
    host = parsed.netloc.lower().removeprefix("www.")
    query = parse_qs(parsed.query, keep_blank_values=False)

    video_id = extract_youtube_video_id(url)
    if video_id and (host == "youtu.be" or host.endswith("youtube.com")):
        return f"https://www.youtube.com/watch?v={video_id}"

    if host in {"x.com", "twitter.com"} and re.search(r"/status/\d+", parsed.path):
        clean_path = parsed.path.rstrip("/")
        return urlunparse((scheme, "x.com", clean_path, "", "", ""))

    clean_query = {}
    for key, values in query.items():
        key_lower = key.lower()
        if key_lower in TRACKING_QUERY_KEYS:
            continue
        if any(key_lower.startswith(prefix) for prefix in TRACKING_QUERY_PREFIXES):
            continue
        clean_query[key] = values

    clean_query_string = urlencode(clean_query, doseq=True)
    clean_path = parsed.path.rstrip("/") if parsed.path != "/" else parsed.path
    return urlunparse((scheme, host, clean_path, "", clean_query_string, ""))


def extract_source_from_note(path):
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return ""

    match = re.search(r"^source:\s*(.+?)\s*$", text, flags=re.MULTILINE)
    if not match:
        return ""
    return match.group(1).strip().strip('"').strip("'")


def find_existing_capture(config, url):
    """Return an existing clip path/sidecar for this canonical source URL."""
    canonical = canonicalize_url(url)
    output = output_dir(config)

    if output.exists():
        for clip in output.glob("*.md"):
            source = extract_source_from_note(clip)
            if source and canonicalize_url(source) == canonical:
                return clip

    pdir = pending_dir(config)
    if pdir.exists():
        for sidecar in pdir.glob("*.json"):
            try:
                payload = json.loads(sidecar.read_text(encoding="utf-8"))
            except Exception:
                continue
            source = payload.get("url", "")
            if source and canonicalize_url(source) == canonical:
                stub = Path(payload.get("stub_path", ""))
                return stub if stub.exists() else sidecar

    return None


def save(title, note, config):
    """Write the note to the vault, choosing a non-colliding filename."""
    output = output_dir(config)
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
    return path


def write_sidecar(stub_path, url, content_type, data, config):
    """Stash everything the background processor needs alongside the stub."""
    pdir = pending_dir(config)
    pdir.mkdir(parents=True, exist_ok=True)
    sidecar = pdir / f"{stub_path.stem}.json"
    payload = {
        "url": url,
        "content_type": content_type,
        "data": data,
        "stub_path": str(stub_path),
    }
    sidecar.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return sidecar


def spawn_processor(stub_path):
    """Fire-and-forget background subprocess to run the LLM enrichment.
    start_new_session detaches from Raycast so the toast fires immediately."""
    script = Path(__file__).resolve()
    subprocess.Popen(
        [sys.executable, str(script), "--process", str(stub_path)],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )

# ── Main ──────────────────────────────────────────────────────────────────────

ICONS = {"tweet": "🐦", "thread": "🧵", "youtube": "▶️", "webpage": "🌐", "article": "📝"}

def fetch_for_url(url, config, from_browser=False):
    """Returns (content_type, data) where data["content"] is the FULL article.
    Truncation for LLM context happens later in ai_process, not here, so the
    saved note keeps the complete source text (Web Clipper parity)."""
    content_type = detect_type(url)
    if content_type == "tweet":
        if from_browser:
            # Try X Article extraction first (Articles lack tweetText entirely)
            article_data = fetch_article_from_browser(config["browser"])
            if article_data:
                html = article_data["html"]
                content = clean_x_chrome(html_to_markdown(html))
                return "article", {
                    "author": article_data["author"],
                    "handle": article_data.get("handle", ""),
                    "title": "",
                    "content": content,
                    # We strip images in clean_x_chrome, so the saved note has none.
                    "has_images": False,
                }

            # Then try thread extraction (multiple tweetText elements, same author)
            thread_data = fetch_thread_from_browser(config["browser"])
            if thread_data:
                tweets = thread_data["tweets"]
                content = "\n\n---\n\n".join(
                    f"[{i+1}/{len(tweets)}] {t}" for i, t in enumerate(tweets)
                )
                return "thread", {
                    "author": thread_data["author"],
                    "handle": thread_data["handle"],
                    "content": content,
                    "tweet_count": len(tweets),
                    "tweets": tweets,
                }

            # Then try long-form tweet (single tweetText, but very long).
            # X Premium lets users post up to 25k chars in one tweet, and
            # oembed truncates these to a snippet. Pull from the DOM instead.
            long_data = fetch_long_tweet_from_browser(config["browser"])
            if long_data:
                cleaned = clean_x_chrome(long_data["content"])
                return "article", {
                    "author": long_data.get("author", ""),
                    "handle": long_data.get("handle", ""),
                    "title": "",
                    "content": cleaned,
                    "has_images": False,
                }

        # Fall back to regular tweet via oembed
        data = fetch_tweet(url)
        return content_type, data
    elif content_type == "youtube":
        data = fetch_youtube(url)
    else:
        browser = config["browser"] if from_browser else None
        data = fetch_webpage(url, browser)
    return content_type, data


def capture():
    """Sync path: read URL, fetch content, write a stub note, hand off to
    a background processor for the slow LLM call, return immediately."""
    config = load_config()

    print("Reading browser tab...")
    browser_url = get_url(config["browser"])
    clip_url = subprocess.run(["pbpaste"], capture_output=True, text=True).stdout.strip()
    clip_url = clip_url if clip_url.startswith("http") else None

    if not browser_url and not clip_url:
        print("❌ No URL found. Open a browser tab or copy a URL to clipboard.")
        sys.exit(1)

    # Try browser URL first, fall back to clipboard if extraction fails.
    # Canonicalization keeps repeated captures from slipping through as
    # separate notes because of tracking params, YouTube timestamps, etc.
    url = canonicalize_url(browser_url or clip_url)
    existing = find_existing_capture(config, url)
    if existing:
        print(f"↩️ Already saved → {existing.name}")
        return

    content_type = detect_type(url)
    print(f"{ICONS[content_type]} Fetching {content_type}...")

    fetch_error = None
    try:
        content_type, data = fetch_for_url(url, config, from_browser=bool(browser_url))
    except Exception as e:
        fetch_error = e
        data = {}

    if content_type == "thread":
        print(f"🧵 Thread detected ({data.get('tweet_count', '?')} tweets)")

    # If browser tab yielded no content, retry with clipboard URL
    if not data.get("content") and content_type != "youtube":
        if clip_url and clip_url != browser_url:
            print("↩️ Retrying with clipboard URL...")
            url = canonicalize_url(clip_url)
            existing = find_existing_capture(config, url)
            if existing:
                print(f"↩️ Already saved → {existing.name}")
                return
            content_type = detect_type(url)
            print(f"{ICONS[content_type]} Fetching {content_type}...")
            try:
                content_type, data = fetch_for_url(url, config, from_browser=False)
                fetch_error = None
            except Exception as e:
                print(f"❌ Fetch failed: {e}")
                sys.exit(1)

    if not data.get("content") and content_type != "youtube":
        if fetch_error:
            print(f"❌ Fetch failed: {fetch_error}")
        else:
            print("❌ Couldn't extract content. Page may require login.")
        sys.exit(1)

    # Write the stub note now so the user gets feedback instantly.
    title, stub_note = build_note(url, content_type, data, ai=None)
    stub_path = save(title, stub_note, config)
    write_sidecar(stub_path, url, content_type, data, config)
    print(f"✅ Saved → {stub_path.name} (enriching in background)")

    # Hand off to the background processor. start_new_session detaches the
    # subprocess so Raycast considers this command done.
    spawn_processor(stub_path)


def process_pending(stub_path):
    """Background path: read the sidecar, run the LLM, rewrite the note,
    delete the sidecar. If the LLM fails the sidecar stays put as a retry
    flag (re-run with --process or the sweep command picks it up)."""
    stub_path = Path(stub_path)
    if not stub_path.exists():
        return

    config = load_config()
    sidecar = pending_dir(config) / f"{stub_path.stem}.json"
    if not sidecar.exists():
        return  # already processed or never queued

    try:
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
    except Exception:
        return

    url = payload["url"]
    content_type = payload["content_type"]
    data = payload["data"]

    try:
        ai = ai_process(content_type, data, config)
    except Exception:
        # Leave the sidecar in place. A re-run will retry.
        return

    title, note = build_note(url, content_type, data, ai)

    # Rename the file to match the AI-generated title if it differs from the
    # stub. Safe because nothing else in the vault links to a freshly-clipped
    # stub yet (it was created seconds ago). Falls back to in-place write if
    # the target slug already exists for another clip.
    date = datetime.now().strftime("%Y-%m-%d")
    fmt = config["capture"]["filename_format"]
    target_filename = make_filename(title, date, fmt)
    target_path = stub_path.parent / target_filename

    if target_path.resolve() == stub_path.resolve():
        # Same slug — write in place.
        stub_path.write_text(note, encoding="utf-8")
        final_path = stub_path
    elif target_path.exists():
        # Collision with a different clip — keep the stub filename to avoid
        # overwriting unrelated content. AI title still lives in frontmatter.
        stub_path.write_text(note, encoding="utf-8")
        final_path = stub_path
    else:
        # Clean rename to the AI title.
        target_path.write_text(note, encoding="utf-8")
        try:
            stub_path.unlink()
        except FileNotFoundError:
            pass
        final_path = target_path

    try:
        sidecar.unlink()
    except FileNotFoundError:
        pass
    return final_path


def fix_orphans():
    """Find clips marked processed: true that have no matching Wiki/Summaries
    page and flip them back to processed: false so wiki-ingest picks them up.

    Useful any time you suspect ingest got out of sync (e.g. after a buggy
    clipper version, or if you imported clips manually). Reversible: just
    re-run wiki-ingest after this to backfill the missing summaries.

    Run via: save-to-vault.py --fix-orphans"""
    config = load_config()
    clips_dir = output_dir(config)
    vault = Path(config["vault_path"])
    summaries = vault / "Wiki" / "Summaries"

    if not clips_dir.exists():
        print(f"No clips folder at {clips_dir}. Nothing to check.")
        return

    if not summaries.exists():
        print(f"No Wiki/Summaries folder at {summaries}.")
        print("If you're new to wiki-ingest, that's expected — there's nothing to be orphaned from.")
        return

    orphans = []
    for clip in clips_dir.glob("*.md"):
        text = clip.read_text(encoding="utf-8")
        # Cheap frontmatter check; we only look at the processed line
        if not re.search(r"^processed:\s*true\s*$", text, re.MULTILINE):
            continue
        # Look for a matching summary page (clipper preserves filenames).
        # Wiki-ingest links source_file: "[[Sources/clips/<name>]]" so by
        # convention the summary shares the clip's stem.
        if not (summaries / clip.name).exists():
            orphans.append(clip)

    if not orphans:
        print(f"✅ No orphans. All processed clips have matching summaries.")
        return

    print(f"Found {len(orphans)} orphan(s) (processed: true, no Wiki/Summaries page):")
    for o in orphans:
        print(f"  - {o.name}")
    print()
    print(f"Flipping processed: true → processed: false on each so the next")
    print(f"wiki-ingest run picks them up.")

    for clip in orphans:
        text = clip.read_text(encoding="utf-8")
        text = re.sub(r"^processed:\s*true\s*$", "processed: false", text, count=1, flags=re.MULTILINE)
        clip.write_text(text, encoding="utf-8")
    print(f"✅ Flipped {len(orphans)} clip(s).")


def sweep_pending():
    """Process every leftover sidecar in _pending/. Useful if the laptop
    slept mid-process or the LLM was down. Run via: save-to-vault.py --sweep"""
    config = load_config()
    pdir = pending_dir(config)
    if not pdir.exists():
        print("Nothing to sweep.")
        return
    sidecars = sorted(pdir.glob("*.json"))
    if not sidecars:
        print("Nothing to sweep.")
        return
    for sidecar in sidecars:
        stub = output_dir(config) / f"{sidecar.stem}.md"
        if not stub.exists():
            continue
        print(f"⚙️  Processing {stub.name}...")
        process_pending(stub)
    print(f"✅ Swept {len(sidecars)} clips.")


def main():
    args = sys.argv[1:]
    if args and args[0] == "--process" and len(args) >= 2:
        process_pending(args[1])
        return
    if args and args[0] == "--sweep":
        sweep_pending()
        return
    if args and args[0] == "--fix-orphans":
        fix_orphans()
        return
    capture()


if __name__ == "__main__":
    # Make sure deps are available before doing anything real. On first run
    # this builds .venv/ and re-execs into it; subsequent runs no-op.
    _ensure_venv()
    main()
