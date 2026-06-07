#!/usr/bin/env python3

# Required parameters:
# @raycast.schemaVersion 1
# @raycast.title Read Later to Daily
# @raycast.mode compact
# @raycast.packageName Obsidian

# Optional parameters:
# @raycast.icon 🔖
# @raycast.description Active browser tab → bookmark link in today's daily note

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta
from html import unescape
from pathlib import Path


BROWSER_SCRIPTS = {
    "chrome": {
        "url": 'tell application "Google Chrome" to get URL of active tab of front window',
        "title": 'tell application "Google Chrome" to get title of active tab of front window',
    },
    "safari": {
        "url": 'tell application "Safari" to get URL of current tab of front window',
        "title": 'tell application "Safari" to get name of current tab of front window',
    },
}


TITLE_JS = r"""
(function() {
  function clean(value) {
    return (value || "").replace(/\s+/g, " ").trim();
  }

  function compactTweetTitle(text) {
    text = clean(text)
      .replace(/https?:\/\/\S+/g, "")
      .replace(/\s+/g, " ")
      .trim();

    var tailStarts = [
      " Thank you @",
      " Thanks @",
      " h/t @",
      " cc @",
      " via @"
    ];
    for (var i = 0; i < tailStarts.length; i++) {
      var idx = text.indexOf(tailStarts[i]);
      if (idx > 20) {
        text = text.slice(0, idx).trim();
        break;
      }
    }

    var firstLine = text.split(/\n+/)[0].trim();
    if (firstLine) text = firstLine;

    text = text.replace(/^(@\w+\s+)+/, "").trim();
    if (text.length <= 72) return text;

    var clipped = text.slice(0, 72);
    var lastSpace = clipped.lastIndexOf(" ");
    if (lastSpace > 45) clipped = clipped.slice(0, lastSpace);
    return clipped.replace(/[.,;:!?]+$/, "") + "...";
  }

  var url = location.href;
  var title = "";
  var meta =
    document.querySelector('meta[property="og:title"]') ||
    document.querySelector('meta[name="twitter:title"]') ||
    document.querySelector('meta[name="title"]');

  if (meta) title = clean(meta.getAttribute("content"));

  if (/\/\/(x|twitter)\.com\/[^/]+\/status\//.test(url)) {
    var tweet = document.querySelector('[data-testid="tweetText"]');
    var text = tweet ? clean(tweet.innerText) : "";
    var name = "";
    var nameEl = document.querySelector('article [data-testid="User-Name"]');
    if (nameEl) {
      var first = nameEl.querySelector("span");
      if (first) name = clean(first.textContent);
    }
    if (text) {
      var compact = compactTweetTitle(text);
      title = compact ? (name ? name + ": " + compact : compact) : title;
    }
  }

  if (!title) title = clean(document.title);
  return JSON.stringify({url: url, title: title});
})()
"""


def load_config():
    script_dir = Path(__file__).resolve().parent
    config_path = script_dir / "config.json"
    example_path = script_dir / "config.example.json"
    path = config_path if config_path.exists() else example_path

    if not path.exists():
        print("No config.json found. Copy config.example.json to config.json first.")
        sys.exit(1)

    with path.open(encoding="utf-8") as f:
        config = json.load(f)

    config["vault_path"] = str(Path(config["vault_path"]).expanduser())
    return config


def run_osascript(args, stdin=None):
    result = subprocess.run(args, input=stdin, capture_output=True, text=True)
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def browser_payload_from_js(browser):
    js = TITLE_JS.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")

    if browser == "chrome":
        jxa = (
            'var app=Application("Google Chrome");'
            'app.windows[0].activeTab().execute({javascript:"' + js + '"});'
        )
    elif browser == "safari":
        jxa = (
            'var app=Application("Safari");'
            'app.doJavaScript("' + js + '", {in: app.windows[0].currentTab()});'
        )
    else:
        return None

    raw = run_osascript(["osascript", "-l", "JavaScript"], stdin=jxa)
    if not raw:
        return None

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None

    if payload.get("url", "").startswith("http"):
        return payload
    return None


def browser_payload_from_applescript(browser):
    scripts = BROWSER_SCRIPTS.get(browser)
    if not scripts:
        return None

    url = run_osascript(["osascript", "-e", scripts["url"]])
    if not url.startswith("http"):
        return None

    title = run_osascript(["osascript", "-e", scripts["title"]])
    return {"url": url, "title": title}


def clipboard_url():
    clip = run_osascript(["pbpaste"])
    return clip if clip.startswith("http") else ""


def get_link_target(config, title_arg="", url_arg=""):
    if url_arg:
        return {"url": url_arg, "title": title_arg or url_arg}

    browser = config.get("browser", "chrome")
    payload = browser_payload_from_js(browser) or browser_payload_from_applescript(browser)
    if payload:
        return payload

    url = clipboard_url()
    if url:
        return {"url": url, "title": title_arg or url}

    return None


def clean_title(title, url):
    title = unescape(title or "").strip()
    title = re.sub(r"\s+", " ", title)

    if is_x_status_url(url):
        title = compact_x_title(title)

    for separator in (" | ", " - "):
        parts = title.split(separator)
        if len(parts) > 1 and len(parts[-1]) <= 28:
            title = separator.join(parts[:-1]).strip()
            break

    if not title:
        title = url

    if len(title) > 160:
        title = title[:157].rstrip() + "..."

    return title


def is_x_status_url(url):
    return bool(re.search(r"https?://(x|twitter)\.com/[^/]+/status/", url))


def compact_x_title(title):
    title = re.sub(r"\s*/\s*X$", "", title).strip()
    title = re.sub(r"\s+on X:\s*[\"“”]?", ": ", title).strip()
    title = title.strip("\"“”")
    title = re.sub(r"https?://\S+", "", title)

    for marker in (" Thank you @", " Thanks @", " h/t @", " cc @", " via @"):
        idx = title.find(marker)
        if idx > 20:
            title = title[:idx].strip()
            break

    title = re.sub(r"^(@\w+\s+)+", "", title).strip()
    if len(title) <= 88:
        return title

    clipped = title[:88]
    last_space = clipped.rfind(" ")
    if last_space > 55:
        clipped = clipped[:last_space]
    return clipped.rstrip(".,;:!?") + "..."


def escape_markdown_title(title):
    return title.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")


def today_parts(now):
    iso = now.date().isoformat()
    week = f"{now.isocalendar().year}-W{now.isocalendar().week:02d}"
    quarter = f"{now.year}-Q{((now.month - 1) // 3) + 1}"
    heading = f"{now.strftime('%A, %B')} {now.day}, {now.year}"
    return iso, week, quarter, heading


def render_daily(now):
    iso, week, quarter, heading = today_parts(now)
    prev_day = (now - timedelta(days=1)).date().isoformat()
    next_day = (now + timedelta(days=1)).date().isoformat()

    return f"""---
type: daily
date: {iso}
week: {week}
quarter: {quarter}
tags:
  - daily
weight:
sleep_hours:
energy:
mood:
focus:
---

[[Journal/Daily/{prev_day}|<- Previous]] | [[Journal/Daily/{iso}|Today]] | [[Journal/Daily/{next_day}|Next ->]]
# {heading}

## Check-in
- [ ] Worked out
- [ ] Protein 180g+
- [ ] Creatine
- [ ] Reta (weekly)


## Morning Brief
[[Mentor/Briefs/{iso}|Today's brief]]

## Carry forward
-

## Today's meetings
-

## Notes
-


## Projects I'm Actively Touching
```dataview
LIST
FROM "Projects"
WHERE up_next = true AND status = "active"
SORT file.name ASC
```
"""


def daily_path(config, now):
    iso = now.date().isoformat()
    return Path(config["vault_path"]) / "Journal" / "Daily" / f"{iso}.md"


def ensure_daily(path, now):
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_daily(now), encoding="utf-8")
    return True


def append_to_notes(text, line, url):
    if line in text or url in text:
        return text, False

    notes_match = re.search(r"^## Notes\s*$", text, flags=re.MULTILINE)
    if not notes_match:
        if not text.endswith("\n"):
            text += "\n"
        return f"{text}\n## Notes\n{line}\n", True

    section_start = notes_match.end()
    next_header = re.search(r"^##\s+", text[section_start:], flags=re.MULTILINE)
    insert_at = section_start + next_header.start() if next_header else len(text)

    before = text[:insert_at].rstrip()
    after = text[insert_at:]

    before = re.sub(r"\n-\s*$", "", before)
    updated = f"{before}\n{line}\n"
    if after and not after.startswith("\n"):
        updated += "\n"
    return updated + after.lstrip("\n"), True


def append_read_later(config, title, url, now, dry_run=False):
    path = daily_path(config, now)
    created = False if dry_run else ensure_daily(path, now)

    title = escape_markdown_title(clean_title(title, url))
    line = f"- [b] [{title}](<{url}>)"

    if dry_run:
        print(line)
        return path, created, True

    text = path.read_text(encoding="utf-8")
    updated, inserted = append_to_notes(text, line, url)
    if inserted:
        path.write_text(updated, encoding="utf-8")
    return path, created, inserted


def parse_args():
    parser = argparse.ArgumentParser(description="Append the active tab as a read-later link to today's daily note.")
    parser.add_argument("--url", help="Use a specific URL instead of the active browser tab.")
    parser.add_argument("--title", help="Use a specific title instead of the browser/page title.")
    parser.add_argument("--date", help="Override the target date, YYYY-MM-DD. Useful for testing.")
    parser.add_argument("--dry-run", action="store_true", help="Print the line that would be appended.")
    return parser.parse_args()


def main():
    args = parse_args()
    config = load_config()
    target = get_link_target(config, args.title or "", args.url or "")

    if not target:
        print("No URL found. Open a browser tab or copy a URL to clipboard.")
        sys.exit(1)

    try:
        now = datetime.strptime(args.date, "%Y-%m-%d") if args.date else datetime.now()
    except ValueError:
        print("Invalid --date. Use YYYY-MM-DD.")
        sys.exit(1)

    path, created, inserted = append_read_later(
        config=config,
        title=target.get("title", ""),
        url=target["url"],
        now=now,
        dry_run=args.dry_run,
    )

    if args.dry_run:
        return
    if not inserted:
        print(f"Already saved in {path.name}")
        return

    action = "Created daily and saved" if created else "Saved"
    print(f"{action} read-later link -> {os.path.relpath(path, config['vault_path'])}")


if __name__ == "__main__":
    main()
