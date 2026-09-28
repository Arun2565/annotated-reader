---
name: annotated-reader
description: "Read your MoonReader annotations overlaid on the original EPUB chapter text — like Apple Books. Generates a self-contained HTML reader per chapter with floating TOC, syntax-highlighted code blocks, and progress tracking. Works with any MoonReader-exported .mrexpt annotation file and its source EPUB."
version: 0.1.0
author: Rohit (Arun2565), Hermes Agent
license: MIT
platforms: [windows]
metadata:
  hermes:
    tags: [moonreader, epub, annotations, highlights, reader]
    related_skills: [mrexpt-to-notes]
---

# Annotated Reader

Read your MoonReader annotations overlaid on the original EPUB chapter text — like Apple Books.

## When to use

- User wants to read their MoonReader annotations on the original book chapter text
- User says "show highlights on chapter text", "make a reader view", "read my book with highlights"
- Don't use for: text summaries/notes (use `mrexpt-to-notes` instead)

## Prerequisites

- The original `.epub` file (the `.mrexpt` only stores phone paths — ask the user to share it)
- Python packages: `beautifulsoup4` (auto-installed by script if missing)

## Quick Reference

| Goal | Command |
|------|--------|
| Generate reader | `terminal(command="python scripts/moonreader_reader.py file.mrexpt book.epub --output-dir out/")` |

## Procedure

### 1. Obtain the EPUB
The `.mrexpt` references phone paths (`/sdcard/...`) — ask the user to share the EPUB file.

### 2. Generate reader
```bash
python scripts/moonreader_reader.py file.mrexpt book.epub --output-dir output/
```

### 3. Verify output
- `index.html` exists in output directory
- One `_reader.html` file per chapter with annotations
- Each reader page opens in browser with highlights visible
- TOC panel slides out when clicking ☰
- Code blocks render with syntax highlighting (Prism.js)
- Images load correctly

Run verification:
```bash
ls output/*_reader.html | wc -l
```
Expected: count matches number of chapters with annotations.

## Reader features

- Floating TOC panel (☰ button → slide-out, ▶ to expand subheadings)
- Preface sorted first; colophon/afterword excluded
- Progress bar + bottom bar with %
- Font stack: Newsreader → EB Garamond → Baskerville → Garamond → Georgia → serif
- Code blocks: JetBrains Mono font, Prism.js syntax highlighting (tomorrow theme)
- Fixed table rendering (overrides EPUB `display:block`)
- 900px wide body, 60px side padding
- Line numbers on code blocks

## Pitfalls

- **EPUB subdirectory structure**: Chapters may be in `OEBPS/text/` or other subdirectories. Script uses `rglob("*.xhtml")` to find them recursively. If chapters are still missing, check the EPUB's internal structure with `unzip -l book.epub`.
- **nav.xhtml nested subheadings**: The table of contents file has nested `<li>` items. Script only parses direct children of the main `<ol>` to determine chapter order. If order is still wrong, verify with `unzip -p book.epub OEBPS/nav.xhtml`.
- **Whitespace mismatch**: Annotation text may have slight differences from chapter text (e.g., "(RAG)" vs "( RAG )"). Script uses space-insensitive matching as fallback when exact match fails.
- **Image path fixing**: EPUB images often use relative paths like `../images/foo.png`. Script rewrites all `src="..."` to `src="Images/filename.png"` for local viewing.
- **Code block transformation**: Script converts `<pre class="code" data-lang="python"><code>` to `<pre class="line-numbers language-python"><code class="language-python">` for Prism.js compatibility. Nested `<code>` tags are flattened.
- **No inline token styles**: Do NOT add `.token.*` CSS rules — they override Prism.js theme colors with `!important`. Let the Prism theme handle syntax coloring.
- **Font loading**: JetBrains Mono and Newsreader are loaded via Google Fonts `@import` in the `<head>`. No local font files needed.
- **Input validation**: Missing/empty files, corrupted EPUB, no-chapter EPUB all exit with clear error messages (exit code 1).
- **Per-chapter error isolation**: If one chapter fails, others still generate. Errors are reported at the end.

## Support files

- `scripts/parse_mrexpt.py` — Shared parser
- `scripts/moonreader_reader.py` — Apple Books-style reader
