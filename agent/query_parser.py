# phase8_agent/query_parser.py
"""
Parse .cypher files in phase5_cypher/ and extract sections into a structured registry.

Assumptions:
 - Sections are separated by comment blocks starting with '/*' and ending with '*/'
 - Each section's comment contains a 1- or 2-line header and an 'Engineer question:' line
 - The Cypher for the section follows the comment block until the next comment or EOF
"""

import re
import pathlib
import json
from typing import List, Dict, Optional

CY_PY_DIR = pathlib.Path(__file__).resolve().parents[1] / "phase5_cypher"
META_DIR = CY_PY_DIR / "_meta"
META_DIR.mkdir(parents=True, exist_ok=True)


def _normalize_text(s: str) -> str:
    return re.sub(r'\s+', ' ', s.strip())


def parse_cypher_file(path: pathlib.Path) -> List[Dict]:
    txt = path.read_text(encoding="utf-8")
    # Split: findings = list of tuples (comment_block, cypher_text)
    # We'll capture comment blocks and following cypher chunk
    pattern = re.compile(r'(/\*.*?\*/)\s*([^/]*?)(?=(/\*|$))', re.DOTALL)
    matches = list(pattern.finditer(txt))

    entries = []
    for idx, m in enumerate(matches, start=1):
        comment = m.group(1)
        cypher = m.group(2).strip()
        # Extract a short title and the Engineer question line
        # Look for 'Engineer question:' within the comment
        eng_q = None
        title = None
        notes = []

        # Normalize comment lines
        lines = [l.strip(' *') for l in comment.splitlines()]
        for line in lines:
            if not line:
                continue
            low = line.lower()
            if 'engineer question' in low:
                # grab text after colon
                parts = line.split(':', 1)
                eng_q = parts[1].strip() if len(parts) > 1 else None
            elif re.match(r'^\d+\.\s', line) or 'pipe runs' in line.lower() or ('arrow' in line.lower() and len(line) < 120):
                # heuristics for title line
                if not title and len(line) < 200:
                    title = _normalize_text(line)
            else:
                notes.append(line)

        entry = {
            "id": f"{path.parent.name}.{idx}",
            "file": str(path),
            "section_number": idx,
            "title": title or f"section_{idx}",
            "engineer_question": eng_q or "",
            "notes": "\n".join(notes).strip(),
            "cypher": cypher
        }
        entries.append(entry)
    return entries


def build_registry(root: pathlib.Path = CY_PY_DIR) -> List[Dict]:
    registry = []
    for p in sorted(root.rglob("*.cypher")):
        registry.extend(parse_cypher_file(p))
    return registry


def write_registry(registry: List[Dict], out: pathlib.Path = META_DIR / "queries.json"):
    out.write_text(json.dumps(registry, indent=2), encoding="utf-8")
    print(f"Wrote registry: {out}")


if __name__ == "__main__":
    reg = build_registry()
    write_registry(reg)
