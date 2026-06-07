# Backlog

Ranked, surf-and-clip use case in mind. Each item has a one-line "why."

## Up next

### 1. Dedup + daily inbox
- **Why:** You will re-encounter the same article. You will also lose track of what you saved today.
- **Sketch:** Before writing the stub, scan existing notes' `source:` frontmatter for the URL. If found, append a timestamp to the existing note's `## Notes` section instead of creating a duplicate. On every save, also append a link to `Daily/<today>.md` (or whatever the daily-note path pattern is, surfaced via config).

### 2. Tag consistency (vault-aware prompt)
- **Why:** Independent tagging fragments the graph. `ai`, `AI`, `artificial-intelligence` all show up as separate nodes.
- **Sketch:** On capture, walk `output_folder` once, extract every `tags:` value, rank by frequency. Inject the top N (say 30) into the LLM prompt as "prefer reusing these tags when they fit." Cache the list in `_pending/.tag-cache.json` and invalidate every N hours.

### 3. YouTube transcripts
- **Why:** Right now YouTube clips only carry the meta description. The actual content is in the transcript.
- **Sketch:** Add `youtube-transcript-api` to dependencies. In `fetch_youtube()`, try to pull the transcript first; fall back to description if unavailable. Truncate to `max_content_chars` before sending to LLM.

## Smaller fixes

### 4. Selection capture
- **Why:** Often the nugget is one paragraph, not the whole article.
- **Sketch:** JXA can read `window.getSelection().toString()`. If non-empty when the hotkey fires, treat it as the content instead of the full page. Note it in frontmatter as `subtype: highlight`.

### 5. Non-ASCII slug normalization
- **Why:** Filenames with em dashes, smart quotes, or unicode bullets can confuse some file watchers.
- **Sketch:** In `make_filename()`, run the title through `unicodedata.normalize("NFKD", ...)` and strip non-word characters before slugifying.

### 6. Domain field needs a controlled vocabulary
- **Why:** Currently `domain` = first tag, which is whatever the LLM picked first. Inconsistent across notes.
- **Sketch:** Define a small vocabulary in config (`["tech", "design", "business", "culture", "personal", ...]`) and ask the LLM to map to one of them.

### 7. Retry on LLM rate limits
- **Why:** OpenAI/Anthropic 429s currently throw and the sidecar sticks. A sweep handles it eventually, but adding exponential backoff inside the LLM call paths reduces the manual sweep need.
- **Sketch:** Wrap `call_openai` / `call_anthropic` in a retry decorator. Respect `Retry-After` header if present.

### 8. Better stub author for X Articles
- **Why:** Interim title says "X Article by @handle" but if the JXA extraction picked up the author name we have a better string.
- **Sketch:** Already partly there in `interim_title()`. Just polish.

## Web Clipper parity gaps

### Image downloading
- **Why:** Web Clipper downloads inline images into `vault/attachments/` and rewrites src URLs to local paths. We currently capture `<img>` tags as remote URLs only, so the note breaks if the source page deletes the image.
- **Sketch:** For each `![](url)` in the captured content, GET the URL, save bytes to `vault_path/attachments/<slug>-<n>.<ext>`, rewrite the markdown to `![](attachments/<slug>-<n>.<ext>)`. Skip if domain is blocked or content-type isn't image/*.
- **Tradeoff:** clip time goes up by a few seconds per image. Could be moved to the background `--process` path so capture stays instant.

### YouTube transcripts (already in earlier backlog)
- Still relevant. YouTube clips are the one content type that doesn't get a full body yet.

## Maybe later

- Screenshot of the tab saved next to the clip (for visual context on tweets / design articles).
- Append-to-existing when the same author publishes a series.
- Pipe captured clips through a weekly digest skill.
