#!/usr/bin/env python3
"""
MoonReader .mrexpt + EPUB → Apple Books-style annotated reader
with collapsible TOC panel. (Version with improved Substack cleanup)
"""

import argparse
import os
import re
import sys
import zipfile
from pathlib import Path
from datetime import datetime
from difflib import SequenceMatcher

try:
    from bs4 import BeautifulSoup, NavigableString, Tag
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "beautifulsoup4"])
    from bs4 import BeautifulSoup, NavigableString, Tag


def color_from_int(color_int):
    known = {
        -65536: {"name": "red", "bg": "#FF6B6B", "bg_soft": "rgba(255,107,107,0.3)", "border": "#D94444"},
        -256: {"name": "yellow", "bg": "#FFE066", "bg_soft": "rgba(255,224,102,0.3)", "border": "#E6AC00"},
        -16711936: {"name": "green", "bg": "#A6E22E", "bg_soft": "rgba(166,226,46,0.3)", "border": "#6BBF59"},
        -2013265665: {"name": "blue", "bg": "#66D9EF", "bg_soft": "rgba(102,217,239,0.3)", "border": "#2B9BC9"},
        -1996554240: {"name": "blue", "bg": "#66D9EF", "bg_soft": "rgba(102,217,239,0.3)", "border": "#2B9BC9"},
        -727187201: {"name": "blue", "bg": "#66D9EF", "bg_soft": "rgba(102,217,239,0.3)", "border": "#2B9BC9"},
    }
    if color_int in known:
        return known[color_int]
    unsigned = color_int & 0xFFFFFFFF
    r, g, b = (unsigned >> 16) & 0xFF, (unsigned >> 8) & 0xFF, unsigned & 0xFF
    bg = f"#{r:02X}{g:02X}{b:02X}"
    return {"name": f"custom_{color_int}", "bg": bg, "bg_soft": f"{bg}4D", "border": bg}


def validate_inputs(mrexpt_path, epub_path=None):
    if not mrexpt_path.exists():
        print(f"Error: File not found: {mrexpt_path}", file=sys.stderr)
        sys.exit(1)
    if mrexpt_path.stat().st_size == 0:
        print(f"Error: File is empty: {mrexpt_path}", file=sys.stderr)
        sys.exit(1)
    if epub_path and not epub_path.exists():
        print(f"Error: EPUB file not found: {epub_path}", file=sys.stderr)
        sys.exit(1)
    if epub_path:
        try:
            with zipfile.ZipFile(epub_path, 'r') as z:
                files = z.namelist()
                if not any(f.endswith(('.xhtml', '.html')) for f in files):
                    print(f"Error: No chapter files (.xhtml/.html) found in EPUB", file=sys.stderr)
                    sys.exit(1)
        except zipfile.BadZipFile:
            print(f"Error: Corrupted EPUB file (not a valid ZIP): {epub_path}", file=sys.stderr)
            sys.exit(1)
    return True


def parse_mrexpt(filepath):
    stats = {"total": 0, "skipped_incomplete": 0, "skipped_empty": 0, "parsed": 0}
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
    lines = content.split("\n")
    annotations = []
    current = {}
    in_entry = False
    entry_line_count = 0

    for i in range(3, len(lines)):
        line = lines[i].strip()
        if line == "#":
            if current:
                stats["total"] += 1
                if "text" not in current or "color" not in current:
                    stats["skipped_incomplete"] += 1
                elif not current.get("text", "").strip():
                    stats["skipped_empty"] += 1
                else:
                    annotations.append(current)
                    stats["parsed"] += 1
            current = {}
            in_entry = True
            entry_line_count = 0
            continue

        if in_entry:
            entry_line_count += 1
            if entry_line_count == 1: current["page"] = line
            elif entry_line_count == 2: current["title"] = line
            elif entry_line_count == 3: current["path1"] = line
            elif entry_line_count == 4: current["path2"] = line
            elif entry_line_count == 5: current["chapter"] = line
            elif entry_line_count == 6: current["flag1"] = line
            elif entry_line_count == 7: current["pos_start"] = line
            elif entry_line_count == 8: current["pos_end"] = line
            elif entry_line_count == 9:
                try: current["color"] = int(line)
                except: current["color"] = -65536
            elif entry_line_count == 10:
                current["timestamp"] = line
                try:
                    ts = int(line)
                    current["date"] = datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d %H:%M")
                except (ValueError, OSError):
                    current["date"] = "Unknown"
            elif entry_line_count == 13: current["text"] = line
            elif entry_line_count == 14: current["is_note"] = line
            elif entry_line_count == 16:
                current["flag4"] = line
                in_entry = False

    if current:
        stats["total"] += 1
        if "text" not in current or "color" not in current:
            stats["skipped_incomplete"] += 1
        elif not current.get("text", "").strip():
            stats["skipped_empty"] += 1
        else:
            annotations.append(current)
            stats["parsed"] += 1

    for a in annotations:
        text = a.get("text", "")
        text = text.replace("<BR><BR>", "\n\n")
        text = text.replace("<BR>", " ")
        a["text"] = text

    if stats["skipped_incomplete"] > 0:
        print(f"  Skipped {stats['skipped_incomplete']} incomplete entries")
    if stats["skipped_empty"] > 0:
        print(f"  Skipped {stats['skipped_empty']} empty annotations")

    return annotations


def extract_chapters(epub_dir):
    oebps = Path(epub_dir) / "OEBPS"
    if not oebps.exists(): oebps = Path(epub_dir) / "EPUB"
    if not oebps.exists(): oebps = Path(epub_dir)

    chapters = []
    xhtml_files = sorted(oebps.rglob("*.xhtml")) + sorted(oebps.rglob("*.html"))
    seen = set()
    for xhtml_file in xhtml_files:
        if xhtml_file.name in seen:
            continue
        seen.add(xhtml_file.name)
        with open(xhtml_file, "r", encoding="utf-8") as f: html = f.read()
        soup = BeautifulSoup(html, "html.parser")
        body = soup.find("body")
        if not body: continue

        title = ""
        h1 = body.find("h1")
        if h1: title = h1.get_text(strip=True)

        subheadings = []
        for h in body.find_all(["h2", "h3"]):
            subheadings.append({
                "level": int(h.name[1]),
                "text": h.get_text(strip=True),
            })

        paragraphs = []
        for p in body.find_all("p"):
            text = p.get_text(strip=True)
            if text and len(text) > 10: paragraphs.append(text)

        chapters.append({
            "file": xhtml_file.name,
            "title": title,
            "html": html,
            "paragraphs": paragraphs,
            "subheadings": subheadings,
        })

    def sort_key(ch):
        f = ch["file"]
        if "preface" in f.lower():
            return (0, f)
        elif "afterword" in f.lower() or "colophon" in f.lower():
            return (2, f)
        else:
            return (1, f)

    chapters.sort(key=sort_key)
    return chapters, oebps / "Images", oebps / "Styles"


def find_text_in_element(text, elem_text):
    text_clean = re.sub(r'\s+', ' ', text).strip()
    elem_clean = re.sub(r'\s+', ' ', elem_text).strip()
    if text_clean in elem_clean: return 1.0
    if len(text_clean) > 20:
        prefix = text_clean[:50]
        if prefix in elem_clean: return 0.9
    text_nospace = text_clean.replace(' ', '')
    elem_nospace = elem_clean.replace(' ', '')
    if text_nospace in elem_nospace: return 0.85
    ratio = SequenceMatcher(None, text_clean, elem_clean).ratio()
    if ratio > 0.7: return ratio
    return 0.0


def safe_annotate_element(elem, ann_text, colors, is_note=False):
    full_text = elem.get_text()
    ann_clean = re.sub(r'\s+', ' ', ann_text).strip()
    text_clean = re.sub(r'\s+', ' ', full_text).strip()

    found_pos = text_clean.find(ann_clean)
    if found_pos < 0:
        ann_nospace = ann_clean.replace(' ', '')
        text_nospace = text_clean.replace(' ', '')
        found_pos = text_nospace.find(ann_nospace)
        if found_pos < 0:
            return False
        nospace_idx = 0
        for i, ch in enumerate(text_clean):
            if ch != ' ':
                if nospace_idx == found_pos:
                    found_pos = i
                    break
                nospace_idx += 1

    orig_start = full_text.find(ann_text[:30].strip())
    if orig_start < 0:
        orig_start = full_text.find(ann_text[:5].strip())
    if orig_start < 0:
        return False
    orig_end = orig_start + len(ann_text)
    actual_text = full_text[orig_start:orig_end]

    import html as html_escape
    escaped_text = html_escape.escape(actual_text)

    if is_note:
        span = f'<span class="ann-note" style="background:{colors["bg_soft"]}; border-bottom:2px solid {colors["border"]}; padding:1px 2px; border-radius:2px;">{escaped_text}</span>'
    else:
        span = f'<span class="ann-hl" style="background:{colors["bg_soft"]}; border-bottom:2px solid {colors["border"]}; -webkit-box-decoration-break:clone; box-decoration-break:clone; padding:1px 2px; border-radius:2px;">{escaped_text}</span>'

    new_html = html_escape.escape(full_text[:orig_start]) + span + html_escape.escape(full_text[orig_end:])
    elem.clear()
    elem.append(BeautifulSoup(new_html, "html.parser"))
    return True


def generate_reader_html(chapter, annotations, output_path, chapters, chapter_annotations, chapter_idx, font_path="ACaslonPro-Regular.otf"):
    soup = BeautifulSoup(chapter["html"], "html.parser")
    body = soup.find("body")
    if not body: return 0

    text_elements = body.find_all(["p", "li", "blockquote", "dd", "dt"])
    matched = 0

    for ann in annotations:
        ann_text = ann.get("text", "").strip()
        if not ann_text or len(ann_text) < 5: continue
        color_int = ann.get("color", -65536)
        colors = color_from_int(color_int)
        is_note = ann.get("is_note", "0") == "1"

        best_elem, best_ratio = None, 0
        for elem in text_elements:
            elem_text = elem.get_text(strip=True)
            if not elem_text: continue
            ratio = find_text_in_element(ann_text, elem_text)
            if ratio > best_ratio:
                best_ratio = ratio
                best_elem = elem

        if best_elem and best_ratio >= 0.7:
            if safe_annotate_element(best_elem, ann_text, colors, is_note):
                matched += 1

    content_html = body.decode_contents()

    # Fix image paths
    import re as re_mod
    def fix_img_src(match):
        src = match.group(1)
        filename = src.split('/')[-1]
        return f'src="Images/{filename}"'
    content_html = re_mod.sub(r'src="([^"]*)"', fix_img_src, content_html)

    # Remove Substack-specific elements using BeautifulSoup
    from bs4 import BeautifulSoup as BS
    substack_soup = BS(content_html, "html.parser")

    def has_class(tag, target):
        try:
            classes = tag.get("class", [])
            if classes is None:
                return False
            return any(target in c for c in classes)
        except (AttributeError, TypeError):
            return False

    # Remove image-link anchors (keep inner img)
    for a_tag in substack_soup.find_all("a"):
        if has_class(a_tag, "image-link"):
            img = a_tag.find("img")
            if img:
                a_tag.replace_with(img)
            else:
                a_tag.unwrap()
        elif "substack.com" in a_tag.get("href", ""):
            a_tag.decompose()

    # Remove subscription links and source lines
    for tag in substack_soup.find_all(["em"]):
        if tag.string and "substack" in tag.string:
            tag.decompose()

    # Remove link icons, header anchors, empty paragraphs
    for tag in list(substack_soup.find_all(True)):
        if has_class(tag, "iconButton") or has_class(tag, "header-anchor") or has_class(tag, "lucide-link"):
            tag.decompose()
        elif tag.name in ["h2", "h3"] and has_class(tag, "header-anchor-post"):
            tag.attrs = {}
        elif tag.name == "p" and not tag.get_text(strip=True):
            tag.decompose()

    content_html = str(substack_soup)

    # Transform code blocks for Prism.js
    def fix_code_block(match):
        pre_attrs = match.group(1)
        code_content = match.group(2)
        lang_match = re_mod.search(r'data-lang="([^"]*)"', pre_attrs)
        lang = lang_match.group(1) if lang_match else ''
        lang_class = f'language-{lang}' if lang else 'language-plaintext'
        inner_content = re_mod.sub(r'^<code[^>]*>(.*)</code>$', r'\1', code_content.strip(), flags=re_mod.DOTALL)
        return f'<pre class="line-numbers {lang_class}"><code class="{lang_class}">{inner_content}</code></pre>'
    content_html = re_mod.sub(r'<pre([^>]*)>(.*?)</pre>', fix_code_block, content_html, flags=re_mod.DOTALL)

    chapter_title = chapter.get("title", "Chapter")
    ann_count = len(annotations)

    html = '<!DOCTYPE html>\n<html lang="en">\n<head>\n'
    html += '  <meta charset="UTF-8">\n'
    html += '  <meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
    html += f'  <title>{chapter_title}</title>\n'
    html += '  <style>\n'
    html += "    @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600&family=Newsreader:ital,opsz,wght@0,6..72,200..800;1,6..72,200..800&family=EB+Garamond:ital,wght@0,400..800;1,400..800&display=swap');\n\n"
    html += "    @import url('https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/themes/prism-tomorrow.min.css');\n\n"
    html += "    @import url('https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/plugins/line-numbers/prism-line-numbers.min.css');\n\n"
    html += '    :root {\n'
    html += '      --bg: #FAF6EE;\n      --surface: #FFFFFF;\n      --ink: #2D2522;\n      --ink-2: #6E625B;\n      --accent: #A34A2E;\n      --border: rgba(163,74,46,0.1);\n'
    html += "      --font-reader: 'Newsreader', 'EB Garamond', 'Baskerville', 'Garamond', Georgia, serif;\n"
    html += '      --toc-width: 280px;\n    }\n\n'
    html += '    [data-theme="dark"] {\n'
    html += '      --bg: #1a1a1a;\n      --surface: #2d2d2d;\n      --ink: #e0e0e0;\n      --ink-2: #a0a0a0;\n      --accent: #E28C68;\n      --border: rgba(243,239,233,0.1);\n    }\n\n'
    html += '    * { box-sizing: border-box; margin: 0; padding: 0; }\n\n'
    html += '    body {\n      font-family: var(--font-reader);\n      background: var(--bg);\n      color: var(--ink);\n      line-height: 1.7;\n      overflow-x: hidden;\n    }\n\n'
    html += '    .top-bar {\n      position: sticky;\n      top: 0;\n      height: 52px;\n      display: flex;\n      align-items: center;\n      justify-content: space-between;\n      padding: 0 20px;\n      background: rgba(250, 246, 238, 0.92);\n      backdrop-filter: blur(20px);\n      -webkit-backdrop-filter: blur(20px);\n      border-bottom: 1px solid var(--border);\n      z-index: 100;\n    }\n\n'
    html += '    .top-bar button {\n      background: none;\n      border: none;\n      color: var(--ink-2);\n      cursor: pointer;\n      padding: 8px;\n      border-radius: 50%;\n      display: flex;\n      align-items: center;\n      justify-content: center;\n    }\n\n'
    html += '    .top-bar button:hover {\n      background: rgba(163,74,46,0.08);\n    }\n\n'
    html += '    .top-bar button svg {\n      width: 20px;\n      height: 20px;\n    }\n\n'
    html += '    .top-bar-title {\n      font-size: 0.85rem;\n      font-weight: 500;\n      color: var(--ink-2);\n      white-space: nowrap;\n      overflow: hidden;\n      text-overflow: ellipsis;\n      max-width: 60%;\n    }\n\n'
    html += '    .reader-content {\n      max-width: 900px;\n      margin: 0 auto;\n      padding: 40px 60px 80px;\n    }\n\n'
    html += '    .reader-content h1 {\n      font-size: 2rem;\n      font-weight: 600;\n      margin-bottom: 24px;\n      line-height: 1.3;\n    }\n\n'
    html += '    .reader-content h2 {\n      font-size: 1.5rem;\n      font-weight: 600;\n      margin: 32px 0 16px;\n    }\n\n'
    html += '    .reader-content h3 {\n      font-size: 1.2rem;\n      font-weight: 600;\n      margin: 24px 0 12px;\n      color: var(--ink-2);\n    }\n\n'
    html += '    .reader-content p {\n      font-size: 1.15rem;\n      line-height: 1.85;\n      margin-bottom: 1.2em;\n      text-align: left;\n    }\n\n'
    html += '    .reader-content blockquote {\n      margin: 20px 0;\n      padding: 16px 20px;\n      border-left: 3px solid var(--accent);\n      background: rgba(163,74,46,0.04);\n      font-style: italic;\n    }\n\n'
    html += '    .reader-content dl {\n      margin: 20px 0;\n    }\n\n'
    html += '    .reader-content dt {\n      font-weight: 600;\n      margin: 16px 0 8px;\n      font-style: italic;\n    }\n\n'
    html += '    .reader-content dd {\n      margin-left: 20px;\n      margin-bottom: 12px;\n      font-size: 1.1rem;\n      line-height: 1.8;\n    }\n\n'
    html += '    .reader-content table {\n      display: table;\n      width: 100%;\n      margin: 24px 0;\n      border-collapse: collapse;\n      font-size: 1rem;\n      border: 1px solid #c3c3c3;\n      box-shadow: 0 1px 3px rgba(0,0,0,0.06);\n    }\n\n'
    html += '    .reader-content th {\n      display: table-cell;\n      background: #f0f4f8;\n      border-bottom: 2px solid #9d9d9d;\n      padding: 14px 16px;\n      font-weight: 600;\n      text-align: left;\n      font-size: 0.95rem;\n      font-family: var(--font-reader);\n    }\n\n'
    html += '    .reader-content td {\n      display: table-cell;\n      padding: 14px 16px;\n      border-bottom: 1px solid #ddd;\n      border-right: 1px solid #eee;\n      vertical-align: top;\n      font-size: 1rem;\n      line-height: 1.7;\n      font-family: var(--font-reader);\n    }\n\n'
    html += '    .reader-content td:last-child {\n      border-right: none;\n    }\n\n'
    html += '    .reader-content tr:nth-of-type(even) {\n      background-color: #fafbfd;\n    }\n\n'
    html += '    .reader-content figure,\n    .reader-content .figure {\n      margin: 24px auto;\n      text-align: center;\n    }\n\n'
    html += '    .reader-content img {\n      max-width: 100%;\n      height: auto;\n    }\n\n'
    html += '    .reader-content figcaption,\n    .reader-content figure h6,\n    .reader-content .figure h6 {\n      font-size: 0.9rem;\n      font-style: italic;\n      color: var(--ink-2);\n      margin-top: 8px;\n    }\n\n'
    html += '    .reader-content .note,\n    .reader-content [data-type="note"] {\n      margin: 20px 0;\n      padding: 16px 20px;\n      background: #f8f4e8;\n      border: 1px solid #e6d48a;\n      border-radius: 6px;\n    }\n\n'
    html += '    .ann-hl { border-radius: 2px; }\n    .ann-note { border-radius: 2px; }\n\n'
    html += '    pre.code, pre[data-lang], .code {\n      background: #1e1e1e !important;\n      border-radius: 8px !important;\n      padding: 16px 20px !important;\n      margin: 20px 0 !important;\n      overflow-x: auto !important;\n      position: relative !important;\n      border: 1px solid #333 !important;\n    }\n\n'
    html += '    pre.code[data-lang]::before, pre[data-lang]::before {\n      content: attr(data-lang);\n      position: absolute;\n      top: 8px;\n      right: 12px;\n      font-size: 0.7rem;\n      color: #888;\n      text-transform: uppercase;\n      letter-spacing: 0.05em;\n      font-family: "JetBrains Mono", "SF Mono", "Consolas", monospace;\n    }\n\n'
    html += '    pre.code code, pre[data-lang] code, .code code {\n      color: #e0e0e0 !important;\n      font-family: "JetBrains Mono", "SF Mono", "Consolas", monospace !important;\n      font-size: 0.9rem !important;\n      line-height: 1.6 !important;\n      background: none !important;\n      padding: 0 !important;\n      border: none !important;\n      white-space: pre !important;\n    }\n\n'
    html += '    p code, li code, td code {\n      background: rgba(0,0,0,0.06) !important;\n      padding: 2px 6px !important;\n      border-radius: 4px !important;\n      font-family: "JetBrains Mono", "SF Mono", "Consolas", monospace !important;\n      font-size: 0.85em !important;\n    }\n\n'
    html += '    .line-numbers-rows { border-right: 1px solid #444 !important; }\n\n'
    html += '    .progress-bar {\n      position: fixed;\n      top: 52px;\n      left: 0;\n      right: 0;\n      height: 2px;\n      background: var(--border);\n      z-index: 99;\n    }\n\n'
    html += '    .progress-fill {\n      height: 100%;\n      background: var(--accent);\n      width: 0%;\n      transition: width 0.2s ease;\n    }\n\n'
    html += '    .ann-badge {\n      display: inline-flex;\n      align-items: center;\n      gap: 6px;\n      background: var(--accent);\n      color: white;\n      font-size: 0.75rem;\n      padding: 4px 10px;\n      border-radius: 12px;\n      margin-bottom: 24px;\n    }\n\n'
    html += '    .chapter-title {\n      text-align: center;\n      padding: 40px 20px;\n      margin-bottom: 32px;\n      border-bottom: 1px solid var(--border);\n    }\n\n'
    html += '    .chapter-title h1 {\n      font-size: 2rem;\n      font-weight: 600;\n      margin-bottom: 8px;\n    }\n\n'
    html += '    .toc-panel {\n      position: fixed;\n      top: 0;\n      left: 0;\n      width: var(--toc-width);\n      height: 100vh;\n      background: var(--surface);\n      border-right: 1px solid var(--border);\n      z-index: 200;\n      transform: translateX(-100%);\n      transition: transform 0.3s ease;\n      display: flex;\n      flex-direction: column;\n      box-shadow: 2px 0 12px rgba(0,0,0,0.08);\n    }\n\n'
    html += '    .toc-panel.open {\n      transform: translateX(0);\n    }\n\n'
    html += '    .toc-header {\n      display: flex;\n      justify-content: space-between;\n      align-items: center;\n      padding: 16px 20px;\n      border-bottom: 1px solid var(--border);\n      height: 52px;\n    }\n\n'
    html += '    .toc-header h3 {\n      font-size: 0.9rem;\n      font-weight: 600;\n      color: var(--ink);\n    }\n\n'
    html += '    .toc-close {\n      background: none;\n      border: none;\n      color: var(--ink-2);\n      cursor: pointer;\n      font-size: 18px;\n      padding: 4px;\n    }\n\n'
    html += '    .toc-nav {\n      flex: 1;\n      overflow-y: auto;\n      padding: 16px 0;\n    }\n\n'
    html += '    .toc-chapter {\n      display: flex;\n      justify-content: space-between;\n      align-items: center;\n      padding: 10px 20px;\n      text-decoration: none;\n      color: var(--ink);\n      font-size: 0.9rem;\n      font-weight: 500;\n      border-left: 3px solid transparent;\n      transition: background 0.15s, border-color 0.15s;\n    }\n\n'
    html += '    .toc-chapter:hover {\n      background: rgba(163,74,46,0.06);\n      border-left-color: var(--accent);\n    }\n\n'
    html += '    .toc-ann-count {\n      background: var(--accent);\n      color: white;\n      font-size: 0.7rem;\n      padding: 2px 8px;\n      border-radius: 10px;\n      min-width: 22px;\n      text-align: center;\n    }\n\n'
    html += '    .toc-arrow {\n      font-size: 0.6rem;\n      color: var(--ink-2);\n      transition: transform 0.2s ease;\n      margin-left: auto;\n    }\n\n'
    html += '    .toc-arrow.open {\n      transform: rotate(90deg);\n    }\n\n'
    html += '    .toc-subs {\n      padding: 4px 0;\n      border-left: 2px solid var(--border);\n      margin-left: 20px;\n    }\n\n'
    html += '    .toc-sub {\n      padding-left: 32px;\n      font-weight: 400;\n    }\n\n'
    html += '    .toc-sub-sub {\n      padding-left: 48px;\n      font-size: 0.75rem;\n    }\n\n'
    html += '    .toc-overlay {\n      position: fixed;\n      inset: 0;\n      background: rgba(0,0,0,0.25);\n      z-index: 199;\n      opacity: 0;\n      pointer-events: none;\n      transition: opacity 0.3s ease;\n    }\n\n'
    html += '    .toc-overlay.show {\n      opacity: 1;\n      pointer-events: auto;\n    }\n\n'
    html += '    .bottom-bar {\n      position: fixed;\n      bottom: 0;\n      left: 0;\n      right: 0;\n      height: 36px;\n      display: flex;\n      align-items: center;\n      justify-content: space-between;\n      padding: 0 24px;\n      background: rgba(250, 246, 238, 0.92);\n      backdrop-filter: blur(20px);\n      -webkit-backdrop-filter: blur(20px);\n      border-top: 1px solid var(--border);\n      font-size: 0.75rem;\n      color: var(--ink-2);\n      z-index: 100;\n    }\n\n'
    html += '    .footer {\n      text-align: center;\n      padding: 40px 20px;\n      margin-top: 60px;\n      border-top: 1px solid var(--border);\n      color: var(--ink-2);\n      font-size: 0.8rem;\n    }\n'
    html += '  </style>\n'
    html += '</head>\n<body>\n'
    html += '  <div class="progress-bar"><div class="progress-fill" id="progressFill"></div></div>\n\n'
    html += '  <div class="toc-overlay" id="tocOverlay" onclick="toggleTOC()"></div>\n\n'
    html += '  <div class="toc-panel" id="tocPanel">\n'
    html += '    <div class="toc-header">\n'
    html += '      <h3>Table of Contents</h3>\n'
    html += '      <button class="toc-close" onclick="toggleTOC()">✕</button>\n'
    html += '    </div>\n'
    html += '    <nav class="toc-nav">\n'

    for c_idx, c in enumerate(chapters):
        anns = chapter_annotations.get(c["file"], [])
        has_subs = len(c.get("subheadings", [])) > 0
        file_base = c["file"].replace(".xhtml", "")

        html += f'      <div class="toc-chapter-wrap" data-chapter="{c_idx}">\n'
        html += f'        <a href="{file_base}_reader.html" class="toc-chapter" onclick="navigateToChapter(\'{file_base}_reader.html\')">'
        html += f'<span>{c["title"]}</span>'
        if anns:
            html += f'<span class="toc-ann-count">{len(anns)}</span>'
        if has_subs:
            html += f'<span class="toc-arrow" id="arrow-{c_idx}" onclick="toggleChapter(event, {c_idx})">▶</span>'
        html += '</a>\n'

        if has_subs:
            html += f'        <div class="toc-subs" id="subs-{c_idx}" style="display:none">\n'
            for sub in c.get("subheadings", []):
                cls = "toc-sub" if sub["level"] == 2 else "toc-sub-sub"
                html += f'          <span class="toc-heading {cls}">{sub["text"]}</span>\n'
            html += f'        </div>\n'
        html += f'      </div>\n'

    html += '    </nav>\n'
    html += '  </div>\n\n'
    html += '  <nav class="top-bar">\n'
    html += '    <button onclick="toggleTOC()" title="Table of Contents">\n'
    html += '      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 6h16M4 12h16M4 18h16"/></svg>\n'
    html += '    </button>\n'
    html += f'    <span class="top-bar-title">{chapter_title}</span>\n'
    html += '    <button onclick="toggleTheme()" title="Toggle theme">\n'
    html += '      <svg id="theme-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="5"/><path d="M12 1v2m0 18v2M4.22 4.22l1.42 1.42m12.72 12.72l1.42 1.42M1 12h2m18 0h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/></svg>\n'
    html += '    </button>\n'
    html += '  </nav>\n\n'
    html += '  <main class="reader-content">\n'
    html += '    <div class="chapter-title">\n'
    html += f'      <h1>{chapter_title}</h1>\n'
    html += f'      <span class="ann-badge">📝 {ann_count} annotations</span>\n'
    html += '    </div>\n\n'
    html += content_html + '\n'
    html += '  </main>\n\n'
    html += '  <footer class="bottom-bar">\n'
    html += f'    <span id="pageInfo">Chapter {chapter_idx + 1}</span>\n'
    html += '    <span id="progressPercent">0%</span>\n'
    html += '  </footer>\n\n'
    html += '  <footer class="footer">\n'
    html += f'    Exported from MoonReader • Generated {datetime.now().strftime("%Y-%m-%d %H:%M")}\n'
    html += '  </footer>\n\n'
    html += '  <script>\n'
    html += '    window.addEventListener(\'scroll\', () => {\n'
    html += '      const scrollTop = window.scrollY;\n'
    html += '      const docHeight = document.documentElement.scrollHeight - window.innerHeight;\n'
    html += '      const progress = docHeight > 0 ? (scrollTop / docHeight) * 100 : 0;\n'
    html += '      document.getElementById(\'progressFill\').style.width = progress + \'%\';\n'
    html += '      document.getElementById(\'progressPercent\').textContent = Math.round(progress) + \'%\';\n'
    html += '    });\n\n'
    html += '    function toggleTOC() {\n'
    html += '      const panel = document.getElementById(\'tocPanel\');\n'
    html += '      const overlay = document.getElementById(\'tocOverlay\');\n'
    html += '      panel.classList.toggle(\'open\');\n'
    html += '      overlay.classList.toggle(\'show\');\n'
    html += '    }\n\n'
    html += '    function toggleChapter(event, idx) {\n'
    html += '      event.preventDefault();\n'
    html += '      event.stopPropagation();\n'
    html += '      const arrow = document.getElementById(\'arrow-\' + idx);\n'
    html += '      const subs = document.getElementById(\'subs-\' + idx);\n'
    html += '      if (arrow && subs) {\n'
    html += '        const isOpen = subs.style.display !== \'none\';\n'
    html += '        subs.style.display = isOpen ? \'none\' : \'block\';\n'
    html += '        arrow.classList.toggle(\'open\', !isOpen);\n'
    html += '      }\n'
    html += '    }\n\n'
    html += '    function navigateToChapter(url) {\n'
    html += '      window.location.href = url;\n'
    html += '    }\n\n'
    html += '    function toggleTheme() {\n'
    html += '      const root = document.documentElement;\n'
    html += '      const isDark = root.getAttribute(\'data-theme\') === \'dark\';\n'
    html += '      if (isDark) {\n'
    html += '        root.removeAttribute(\'data-theme\');\n'
    html += '        document.getElementById(\'theme-icon\').innerHTML = \'<circle cx="12" cy="12" r="5"/><path d="M12 1v2m0 18v2M4.22 4.22l1.42 1.42m12.72 12.72l1.42 1.42M1 12h2m18 0h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/>\';\n'
    html += '      } else {\n'
    html += '        root.setAttribute(\'data-theme\', \'dark\');\n'
    html += '        document.getElementById(\'theme-icon\').innerHTML = \'<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>\';\n'
    html += '      }\n'
    html += '    }\n'
    html += '  </script>\n'
    html += '  <script src="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/prism.min.js"></script>\n'
    html += '  <script src="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/plugins/autoloader/prism-autoloader.min.js"></script>\n'
    html += '  <script src="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/plugins/line-numbers/prism-line-numbers.min.js"></script>\n'
    html += '</body>\n</html>'

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    return matched


def main():
    parser = argparse.ArgumentParser(description="MoonReader annotations + EPUB → Apple Books-style reader with TOC")
    parser.add_argument("mrexpt", help="Path to .mrexpt file")
    parser.add_argument("epub", help="Path to EPUB file or extracted directory")
    parser.add_argument("--output-dir", "-o", help="Output directory")
    args = parser.parse_args()

    mrexpt_path = Path(args.mrexpt)
    epub_path = Path(args.epub)
    output_dir = Path(args.output_dir) if args.output_dir else mrexpt_path.parent / "annotated"
    output_dir.mkdir(parents=True, exist_ok=True)

    validate_inputs(mrexpt_path, epub_path if epub_path.is_file() else None)

    if epub_path.is_file():
        epub_dir = output_dir / "epub_extracted"
        if not epub_dir.exists():
            print(f"Extracting EPUB...")
            with zipfile.ZipFile(epub_path, 'r') as z:
                z.extractall(epub_dir)
    else:
        epub_dir = epub_path

    if epub_dir.is_dir():
        oebps = epub_dir / "OEBPS"
        if not oebps.exists(): oebps = epub_dir / "EPUB"
        if not oebps.exists(): oebps = epub_dir
        for folder in ["Images", "Styles"]:
            src = oebps / folder
            dst = output_dir / folder
            if src.exists() and not dst.exists():
                import shutil
                try:
                    shutil.copytree(src, dst)
                    print(f"Copied {folder}/")
                except PermissionError:
                    print(f"WARNING: Permission denied copying {folder}/")
            elif not src.exists():
                print(f"Note: EPUB has no {folder}/ directory — skipping")

    print(f"Parsing {mrexpt_path}...")
    annotations = parse_mrexpt(mrexpt_path)
    print(f"Found {len(annotations)} annotations")

    print(f"Extracting chapters...")
    chapters, images_dir, styles_dir = extract_chapters(epub_dir)
    print(f"Found {len(chapters)} chapters")

    if not chapters:
        print("No chapters found!", file=sys.stderr)
        sys.exit(1)

    # Sort chapters by book order (from nav.xhtml)
    nav_path = epub_dir / "OEBPS" / "nav.xhtml"
    if not nav_path.exists(): nav_path = epub_dir / "EPUB" / "nav.xhtml"
    if not nav_path.exists(): nav_path = epub_dir / "nav.xhtml"
    chapter_order = {}
    if nav_path.exists():
        try:
            with open(nav_path, "r", encoding="utf-8") as f:
                nav_content = f.read()
            from bs4 import BeautifulSoup as BS
            nav_soup = BS(nav_content, "html.parser")
            main_ol = nav_soup.find("ol")
            if main_ol:
                for idx, li in enumerate(main_ol.find_all("li", recursive=False)):
                    a = li.find("a")
                    if a and a.get("href"):
                        href = a["href"]
                        filename = href.split("/")[-1]
                        chapter_order[filename] = idx
        except Exception:
            pass

    def chapter_sort_key(ch):
        return (chapter_order.get(ch["file"], 999), ch["file"])
    chapters.sort(key=chapter_sort_key)

    # Match annotations to chapters
    print(f"Matching annotations to chapters...")
    chapter_annotations = {ch["file"]: [] for ch in chapters}
    unassigned = []

    matchable = [a for a in annotations if len(a.get("text", "").strip()) >= 5]
    if len(matchable) < len(annotations):
        print(f"  Skipped {len(annotations) - len(matchable)} too-short annotations (<5 chars)")

    for ann in matchable:
        ann_text = ann.get("text", "").strip()

        best_ch, best_ratio = None, 0
        for ch in chapters:
            for para in ch["paragraphs"]:
                ratio = find_text_in_element(ann_text, para)
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_ch = ch
                if ratio >= 0.9: break
            if best_ratio >= 0.9: break

        if best_ch and best_ratio >= 0.7:
            chapter_annotations[best_ch["file"]].append(ann)
        else:
            unassigned.append(ann)

    total_accounted = sum(len(v) for v in chapter_annotations.values()) + len(unassigned)
    assert total_accounted == len(matchable), \
        f"Annotation count mismatch: {total_accounted} accounted vs {len(matchable)} matchable"

    print(f"\nAnnotation assignment:")
    for ch in chapters:
        count = len(chapter_annotations[ch["file"]])
        if count > 0: print(f"  {ch['file']}: {count} annotations")
    print(f"  Unassigned: {len(unassigned)}")

    # Generate reader HTML with TOC
    print(f"\nGenerating reader HTML with TOC...")
    errors = []
    for ch_idx, ch in enumerate(chapters):
        anns = chapter_annotations[ch["file"]]
        if not anns: continue

        output_path = output_dir / f"{ch['file'].replace('.xhtml', '')}_reader.html"
        print(f"  Processing {ch['file']} ({len(anns)} annotations)...")
        try:
            matched = generate_reader_html(ch, anns, output_path, chapters, chapter_annotations, ch_idx)
            print(f"    → {output_path.name} ({matched}/{len(anns)} matched)")
        except Exception as e:
            print(f"    ✗ FAILED: {ch['file']}: {e}")
            errors.append((ch["file"], str(e)))
            continue

    if errors:
        print(f"\n{len(errors)} chapter(s) failed:")
        for fname, err in errors:
            print(f"  - {fname}: {err}")
        print("Other chapters generated successfully.")

    # Generate index page
    index_path = output_dir / "index.html"
    print(f"\nIndex: {index_path}")

    index_html = '<!DOCTYPE html>\n<html lang="en">\n<head>\n'
    index_html += '  <meta charset="UTF-8">\n'
    index_html += '  <title>Reader Index</title>\n'
    index_html += '  <style>\n'
    index_html += "    @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600&family=Newsreader:ital,opsz,wght@0,6..72,200..800;1,6..72,200..800&family=EB+Garamond:ital,wght@0,400..800;1,400..800&display=swap');\n"
    index_html += "    body { font-family: 'Newsreader', 'EB Garamond', 'Baskerville', 'Garamond', Georgia, serif; background: #FAF6EE; color: #2D2522; padding: 40px 20px; max-width: 800px; margin: 0 auto; }\n"
    index_html += "    h1 { text-align: center; margin-bottom: 40px; }\n"
    index_html += "    .chapter-list { display: flex; flex-direction: column; gap: 12px; }\n"
    index_html += "    .chapter-link { display: flex; justify-content: space-between; align-items: center; background: #fff; padding: 16px 20px; border-radius: 8px; text-decoration: none; color: inherit; border: 1px solid rgba(163,74,46,0.1); transition: box-shadow 0.2s; }\n"
    index_html += "    .chapter-link:hover { box-shadow: 0 4px 12px rgba(0,0,0,0.08); }\n"
    index_html += "    .ann-count { background: #A34A2E; color: white; padding: 4px 10px; border-radius: 12px; font-size: 0.8rem; }\n"
    index_html += '  </style>\n'
    index_html += '</head>\n<body>\n'
    index_html += '  <div class="chapter-list">\n'

    for ch in chapters:
        anns = chapter_annotations[ch["file"]]
        if anns:
            index_html += f'    <a href="{ch["file"].replace(".xhtml","")}_reader.html" class="chapter-link"><span>{ch["title"]}</span><span class="ann-count">{len(anns)} annotations</span></a>\n'

    index_html += '  </div>\n'
    index_html += '</body>\n</html>'

    with open(index_path, "w", encoding="utf-8") as f:
        f.write(index_html)

    print(f"\nDone! Open {index_path} in a browser to read.")


if __name__ == "__main__":
    main()
