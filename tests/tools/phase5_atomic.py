"""
Phase-5 Robust Semantic Splitter
Production-safe intent extraction
"""

from pathlib import Path
import re
import shutil


BASE_DIR = Path(__file__).resolve().parents[1] / "phase5_cypher"
CYPHER_EXT = ".cypher"

SECTION_PATTERN = re.compile(
    r"(/\*[\s\S]*?\*/)\s*([\s\S]*?;)",
    re.DOTALL,
)

STOPWORDS = {
    "what", "is", "are", "the", "a", "an", "of",
    "on", "this", "that", "to", "for", "each",
    "shown", "present"
}


def clean_title_line(line: str) -> str:
    line = line.strip().lstrip("*").strip()

    # remove numbering like "1."
    line = re.sub(r"^\d+\.\s*", "", line)

    # remove parentheses
    line = re.sub(r"\(.*?\)", "", line)

    # remove separator lines
    if set(line) <= {"-", "="}:
        return ""

    return line.strip()


def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", "", text)
    words = [w for w in text.split() if w not in STOPWORDS]
    if not words:
        return ""
    return "_".join(words[:6])


def extract_intent(comment_block: str, fallback: str) -> str:
    for raw_line in comment_block.splitlines():
        cleaned = clean_title_line(raw_line)
        if cleaned:
            slug = slugify(cleaned)
            if slug:
                return slug
    return fallback


def split_file(path: Path) -> None:
    print(f"\n[INFO] Processing: {path}")

    text = path.read_text(encoding="utf-8")
    matches = list(SECTION_PATTERN.finditer(text))

    if len(matches) <= 1:
        print("  → Already atomic. Skipping.")
        return

    backup_path = path.with_suffix(".cypher.bak")
    shutil.copy2(path, backup_path)

    header = text.split("/*", 1)[0].strip()
    numeric_prefix = path.stem.split("_")[0]

    used_names = set()

    for idx, match in enumerate(matches, start=1):
        section_comment = match.group(1).strip()
        statement = match.group(2).strip().rstrip(";")

        fallback = f"query_{idx}"
        intent_slug = extract_intent(section_comment, fallback)

        filename_base = f"{numeric_prefix}_{intent_slug}"

        # collision protection
        counter = 1
        while filename_base in used_names:
            filename_base = f"{numeric_prefix}_{intent_slug}_{counter}"
            counter += 1

        used_names.add(filename_base)

        new_filename = filename_base + CYPHER_EXT
        new_path = path.parent / new_filename

        content_parts = []
        if header:
            content_parts.append(header)
            content_parts.append("\n")

        content_parts.append(section_comment)
        content_parts.append("\n")
        content_parts.append(statement)

        new_path.write_text(
            "\n\n".join(content_parts).strip() + "\n",
            encoding="utf-8",
        )

        print(f"     ✓ Created: {new_filename}")

    path.unlink()
    print("  → Original removed (backup preserved).")


def main() -> None:
    print("========== Phase-5 Robust Semantic Splitter ==========")

    for category_dir in sorted(
        p for p in BASE_DIR.iterdir()
        if p.is_dir() and p.name != "_meta"
    ):
        for cypher_file in sorted(category_dir.glob(f"*{CYPHER_EXT}")):
            split_file(cypher_file)

    print("\n[OK] Semantic split complete.")


if __name__ == "__main__":
    main()