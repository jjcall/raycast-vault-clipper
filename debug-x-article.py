#!/usr/bin/env python3
"""
Debug script: run with the X article page open in Chrome.
Uses JXA (not AppleScript) to match how the clipper's thread extraction works.
"""

import subprocess
import json

def run_jxa_in_chrome(js_code):
    """Execute JS in Chrome via JXA (same method as fetch_thread_from_browser)."""
    escaped = js_code.replace("\\", "\\\\").replace('"', '\\"')
    jxa = f'var app=Application("Google Chrome");var result=app.windows[0].activeTab().execute({{javascript:"{escaped}"}});result;'
    result = subprocess.run(
        ["osascript", "-l", "JavaScript"],
        input=jxa,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"❌ JXA error: {result.stderr.strip()}")
        return None
    return result.stdout.strip()

print("=" * 60)
print("DEBUG: X Article Page Extraction (JXA)")
print("=" * 60)

# 1. Basic page info
raw = run_jxa_in_chrome("JSON.stringify({url: window.location.href, title: document.title})")
if raw:
    try:
        info = json.loads(raw)
        print(f"\n📍 URL: {info['url']}")
        print(f"📝 Title: {info['title']}")
    except:
        print(f"Raw: {raw[:200]}")

# 2. Selector scan
print(f"\n{'='*60}")
print("SELECTOR SCAN")
print(f"{'='*60}")

selectors = [
    'article[data-testid=tweet]',
    '[data-testid=tweetText]',
    '[data-testid=article-body]',
    'article [role=article]',
    '[role=main]',
    'main',
    'article',
]

for sel in selectors:
    js = f"""(function(){{var els=document.querySelectorAll('{sel}');if(!els.length)return JSON.stringify({{found:0,sel:'{sel}'}});var samples=[];for(var i=0;i<Math.min(els.length,3);i++){{samples.push({{tag:els[i].tagName,textLen:els[i].innerText.length,htmlLen:els[i].innerHTML.length,preview:els[i].innerText.substring(0,150).replace(/\\n/g,' ')}});}};return JSON.stringify({{found:els.length,sel:'{sel}',samples:samples}});}})()"""

    raw = run_jxa_in_chrome(js)
    if raw:
        try:
            data = json.loads(raw)
            if data["found"] == 0:
                print(f"  ❌ {sel}: not found")
            else:
                print(f"  ✅ {sel}: {data['found']} found")
                for i, s in enumerate(data.get("samples", [])):
                    print(f"     [{i}] {s['tag']} | text:{s['textLen']} chars | html:{s['htmlLen']} chars")
                    print(f"         {s['preview'][:120]}...")
        except:
            print(f"  ⚠️ {sel}: parse error — {raw[:150]}")

# 3. Full page text length
print(f"\n{'='*60}")
print("PAGE CONTENT SIZE")
print(f"{'='*60}")

raw = run_jxa_in_chrome("JSON.stringify({bodyText: document.body.innerText.length, bodyHtml: document.body.innerHTML.length})")
if raw:
    try:
        data = json.loads(raw)
        print(f"  body.innerText: {data['bodyText']} chars")
        print(f"  body.innerHTML: {data['bodyHtml']} chars")
    except:
        print(f"  Raw: {raw[:200]}")

# 4. Content dump - first 3000 chars from the biggest content area
print(f"\n{'='*60}")
print("CONTENT DUMP (role=main innerText, first 3000 chars)")
print(f"{'='*60}")

raw = run_jxa_in_chrome("""(function(){var el=document.querySelector('[role=main]')||document.querySelector('main')||document.body;return el.innerText.substring(0,3000);})()""")
if raw:
    print(raw)

# 5. iframe and shadow DOM check
print(f"\n{'='*60}")
print("IFRAME & SHADOW DOM")
print(f"{'='*60}")

raw = run_jxa_in_chrome("""(function(){var frames=document.querySelectorAll('iframe');var srcs=[];for(var i=0;i<frames.length;i++)srcs.push(frames[i].src||'(empty)');var shadow=0;var all=document.querySelectorAll('*');for(var i=0;i<Math.min(all.length,5000);i++)if(all[i].shadowRoot)shadow++;return JSON.stringify({iframes:frames.length,iframeSrcs:srcs.slice(0,5),shadowHosts:shadow});})()""")
if raw:
    try:
        data = json.loads(raw)
        print(f"  Iframes: {data['iframes']}")
        for src in data.get("iframeSrcs", []):
            print(f"    {src[:100]}")
        print(f"  Shadow DOM hosts: {data['shadowHosts']}")
    except:
        print(f"  Raw: {raw[:200]}")

print(f"\n{'='*60}")
print("DONE")
print(f"{'='*60}")
