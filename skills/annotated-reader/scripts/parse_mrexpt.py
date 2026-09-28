#!/usr/bin/env python3
"""
Parse MoonReader .mrexpt files into a list of annotation dicts.

Usage:
    python parse_mrexpt.py <file.mrexpt> [output.json]

Outputs JSON array of annotation objects to stdout or file.
"""

import json
import sys
from datetime import datetime
from pathlib import Path


def parse_mrexpt(filepath):
    """Parse a .mrexpt file into a list of annotation dicts."""
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    lines = content.split("\n")
    annotations = []
    current = {}
    in_entry = False
    entry_line_count = 0

    # Skip first 3 metadata lines (version, indent, trim)
    for i in range(3, len(lines)):
        line = lines[i].strip()
        if line == "#":
            if current:
                annotations.append(current)
            current = {}
            in_entry = True
            entry_line_count = 0
            continue

        if in_entry:
            entry_line_count += 1
            if entry_line_count == 1:
                current["page"] = line
            elif entry_line_count == 2:
                current["title"] = line
            elif entry_line_count == 3:
                current["path1"] = line
            elif entry_line_count == 4:
                current["path2"] = line
            elif entry_line_count == 5:
                current["chapter"] = line
            elif entry_line_count == 6:
                current["flag1"] = line
            elif entry_line_count == 7:
                current["pos_start"] = line
            elif entry_line_count == 8:
                current["pos_end"] = line
            elif entry_line_count == 9:
                try:
                    current["color"] = int(line)
                except ValueError:
                    current["color"] = -65536
            elif entry_line_count == 10:
                current["timestamp"] = line
                try:
                    ts = int(line)
                    current["date"] = datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d %H:%M")
                except (ValueError, OSError):
                    current["date"] = line
            elif entry_line_count == 13:
                current["text"] = line
            elif entry_line_count == 14:
                current["is_note"] = line
            elif entry_line_count == 16:
                current["flag4"] = line
                in_entry = False

    if current:
        annotations.append(current)

    # Clean up BR tags
    for a in annotations:
        text = a.get("text", "")
        text = text.replace("<BR><BR>", "\n\n")
        text = text.replace("<BR>", " ")
        a["text"] = text

    return annotations


def main():
    if len(sys.argv) < 2:
        print("Usage: python parse_mrexpt.py <file.mrexpt> [output.json]", file=sys.stderr)
        sys.exit(1)

    filepath = Path(sys.argv[1])
    if not filepath.exists():
        print(f"Error: {filepath} not found", file=sys.stderr)
        sys.exit(1)

    annotations = parse_mrexpt(filepath)

    if len(sys.argv) >= 3:
        output_path = Path(sys.argv[2])
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(annotations, f, indent=2, ensure_ascii=False)
        print(f"Saved {len(annotations)} annotations to {output_path}")
    else:
        print(json.dumps(annotations, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
