#!/usr/bin/env python3

# Required parameters:
# @raycast.schemaVersion 1
# @raycast.title Diagnose Current Tab
# @raycast.mode fullOutput
# @raycast.packageName Obsidian

# Optional parameters:
# @raycast.icon 🔬
# @raycast.description Shows which selectors the clipper sees on the active tab and which extraction path it would take.

"""Diagnose what the clipper sees on the current browser tab.

When the clipper misclassifies a page (article saved as a tweet, summary
truncated, etc.) run this and you'll see exactly which DOM selectors fire,
how much content each one has, and which extraction path the main script
would take. Faster than guessing at the JXA.
"""

import json
import subprocess
import sys
from pathlib import Path

# ── Auto-bootstrap (shared with save-to-vault.py) ─────────────────────────────
import os

_VENV_DIR = Path(__file__).resolve().parent / ".venv"
_VENV_PYTHON = _VENV_DIR / "bin" / "python3"


def _ensure_venv():
    try:
        if Path(sys.executable).resolve() == _VENV_PYTHON.resolve():
            return
    except OSError:
        pass
    if _VENV_PYTHON.exists():
        script = str(Path(__file__).resolve())
        os.execv(str(_VENV_PYTHON), [str(_VENV_PYTHON), script, *sys.argv[1:]])
        return
    # If the venv doesn't exist yet, just run save-to-vault.py once to build it.
    print("ℹ️  No venv found. Run save-to-vault.py once first to bootstrap dependencies.")
    sys.exit(1)


# ── Config (shared shape with save-to-vault.py) ───────────────────────────────

def load_browser():
    cfg = Path(__file__).resolve().parent / "config.json"
    example = Path(__file__).resolve().parent / "config.example.json"
    path = cfg if cfg.exists() else example
    with open(path) as f:
        return json.load(f).get("browser", "chrome")


# ── JXA runner ────────────────────────────────────────────────────────────────

def run_in_browser(browser, js):
    escaped = js.replace("\\", "\\\\").replace('"', '\\"')
    if browser == "chrome":
        jxa = f'var app=Application("Google Chrome");var r=app.windows[0].activeTab().execute({{javascript:"{escaped}"}});r;'
    elif browser == "safari":
        jxa = f'var app=Application("Safari");var r=app.doJavaScript("{escaped}",{{in:app.windows[0].currentTab()}});r;'
    else:
        return None
    result = subprocess.run(["osascript", "-l", "JavaScript"], input=jxa, capture_output=True, text=True)
    if result.returncode != 0:
        return None
    return result.stdout.strip()


# ── Diagnostic JS ─────────────────────────────────────────────────────────────

PROBE_JS = """(function(){
  function safe(el, prop){ try { return el ? (el[prop] || '') : ''; } catch(e){ return ''; } }
  function preview(s, n){ return (s||'').replace(/\\s+/g, ' ').substring(0, n); }
  var selectors = [
    'article[data-testid=tweet]',
    '[data-testid=tweetText]',
    '[data-testid=article-body]',
    '[data-testid=User-Name]',
    'article',
    '[role=main]',
    'main',
    '[itemtype*="Article"]'
  ];
  var results = [];
  for (var i=0; i<selectors.length; i++) {
    var els = document.querySelectorAll(selectors[i]);
    var samples = [];
    for (var j=0; j<Math.min(els.length, 2); j++) {
      samples.push({
        textLen: safe(els[j], 'innerText').length,
        htmlLen: safe(els[j], 'innerHTML').length,
        preview: preview(safe(els[j], 'innerText'), 160)
      });
    }
    results.push({sel: selectors[i], found: els.length, samples: samples});
  }
  return JSON.stringify({
    url: window.location.href,
    title: document.title,
    bodyTextLen: document.body.innerText.length,
    selectors: results
  });
})()"""


# ── Verdict logic mirrors save-to-vault.py fetch_for_url ──────────────────────

def verdict(probe):
    """Decide which extraction path the clipper would take, given probe data."""
    by_sel = {r["sel"]: r for r in probe["selectors"]}
    tweet_articles = by_sel.get("article[data-testid=tweet]", {}).get("found", 0)
    tweet_text_nodes = by_sel.get("[data-testid=tweetText]", {}).get("found", 0)
    tweet_text_len = 0
    if tweet_text_nodes:
        s = by_sel["[data-testid=tweetText]"]["samples"]
        if s:
            tweet_text_len = s[0]["textLen"]
    main_article_len = 0
    if tweet_articles:
        s = by_sel["article[data-testid=tweet]"]["samples"]
        if s:
            main_article_len = s[0]["textLen"]

    # 1. X Article (no tweetText, large article body)
    if tweet_articles >= 1 and tweet_text_nodes == 0 and main_article_len >= 500:
        return "ARTICLE (X Article — no tweetText, large body)"
    # 2. Thread (multiple tweetText elements)
    if tweet_text_nodes >= 2:
        return f"THREAD ({tweet_text_nodes} tweetText elements)"
    # 3. Long-form tweet (one tweetText, very long)
    if tweet_text_nodes == 1 and tweet_text_len >= 800:
        return f"ARTICLE (long-form tweet — single tweetText, {tweet_text_len} chars)"
    # 4. Regular tweet
    if tweet_text_nodes == 1:
        return f"TWEET (oembed — single tweetText, only {tweet_text_len} chars)"
    # 5. Webpage / other
    if not tweet_articles and not tweet_text_nodes:
        return "WEBPAGE (no X-specific selectors hit)"
    return "AMBIGUOUS (none of the paths matched cleanly)"


# ── Output ────────────────────────────────────────────────────────────────────

def main():
    browser = load_browser()
    raw = run_in_browser(browser, PROBE_JS)
    if not raw:
        print("❌ Couldn't read the browser tab. Is the browser open and focused?")
        sys.exit(1)

    try:
        probe = json.loads(raw)
    except Exception as e:
        print(f"❌ Couldn't parse JXA output: {e}")
        print(f"Raw output: {raw[:500]}")
        sys.exit(1)

    print("=" * 60)
    print(f"URL:   {probe['url']}")
    print(f"Title: {probe['title']}")
    print(f"Body text length: {probe['bodyTextLen']} chars")
    print("=" * 60)
    print()
    print("Selector hits:")
    print()
    for r in probe["selectors"]:
        if r["found"] == 0:
            print(f"  ❌ {r['sel']}: not found")
            continue
        print(f"  ✅ {r['sel']}: {r['found']} found")
        for i, s in enumerate(r["samples"]):
            print(f"     [{i}] text:{s['textLen']} chars / html:{s['htmlLen']} chars")
            if s["preview"]:
                print(f"         \"{s['preview']}...\"")
    print()
    print("=" * 60)
    print(f"Verdict: {verdict(probe)}")
    print("=" * 60)


if __name__ == "__main__":
    _ensure_venv()
    main()
