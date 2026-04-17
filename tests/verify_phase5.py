# verify_phase5.py
import os
import re
from typing import List, Dict, Any, Tuple, Set
from ingestion.load_to_neo4j import Neo4jLoader
from neo4j.exceptions import Neo4jError

PHASE5_DIR = "phase5_cypher"
VERBOSE = False
ROW_SAMPLE = 3

# -----------------------
# Logging
# -----------------------
def info(msg: str):
    if VERBOSE:
        print(f"[INFO] {msg}")

def warn(msg: str):
    print(f"[WARN] {msg}")

def error(msg: str):
    print(f"[ERROR] {msg}")

def header(title: str):
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)

# -----------------------
# Read-only enforcement
# -----------------------
_FORBIDDEN = re.compile(
    r"\b(create|merge|set|delete|remove|drop|foreach|load\s+csv)\b",
    flags=re.IGNORECASE,
)

def is_readonly(stmt: str) -> bool:
    return not bool(_FORBIDDEN.search(stmt))

# -----------------------
# Parameter detection (CRITICAL)
# -----------------------
_PARAM_RE = re.compile(r"\$\w+")

def is_parameterized(stmt: str) -> bool:
    """
    Phase-5 verifier rule:
    Parameterized queries are INTERACTIVE and must never be executed.
    """
    return bool(_PARAM_RE.search(stmt))

# -----------------------
# Cypher parsing (correct + conservative)
# -----------------------
NODE_LABEL_RE = re.compile(r"\(\s*\w*\s*:\s*([A-Za-z_][A-Za-z0-9_]*)")
REL_TYPE_RE  = re.compile(r"\[\s*:\s*([A-Za-z_][A-Za-z0-9_]*)")
PROP_RE      = re.compile(r"\b\w+\.([A-Za-z_][A-Za-z0-9_]*)\b")

# -----------------------
# DB schema
# -----------------------
def fetch_schema(session) -> Tuple[Set[str], Set[str], Set[str]]:
    labels = {r["label"] for r in session.run("CALL db.labels()")}
    rels   = {r["relationshipType"] for r in session.run("CALL db.relationshipTypes()")}
    props  = {r["propertyKey"] for r in session.run("CALL db.propertyKeys()")}
    return labels, rels, props

# -----------------------
# File helpers
# -----------------------
def collect_files(base: str) -> List[str]:
    out = []
    for root, _, files in os.walk(base):
        for f in files:
            if f.endswith(".cypher"):
                out.append(os.path.join(root, f))
    return sorted(out)

def split_statements(text: str) -> List[str]:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = re.sub(r"(?m)^\s*(//|--).*?$", "", text)
    return [s.strip() for s in text.split(";") if s.strip()]

# -----------------------
# Execution
# -----------------------
def run(session, stmt: str) -> List[Dict[str, Any]]:
    result = session.run(stmt)
    rows = result.data()
    if VERBOSE and rows:
        info(f"Sample rows: {rows[:ROW_SAMPLE]}")
    return rows

# -----------------------
# Main
# -----------------------
def verify_phase5():
    header("PHASE 5 — READ-ONLY GROUND-TRUTH VERIFIER")

    files = collect_files(PHASE5_DIR)
    print(f"Discovered {len(files)} Phase-5 cypher files")

    loader = Neo4jLoader()

    executed = skipped = errors = total_rows = 0

    with loader.driver.session(database=loader.database) as session:
        db_labels, db_rels, db_props = fetch_schema(session)

        for path in files:
            print(f"\n-- Checking: {os.path.relpath(path)}")

            with open(path, "r", encoding="utf-8") as fh:
                statements = split_statements(fh.read())

            print(f"  statements: {len(statements)}")

            for i, stmt in enumerate(statements, 1):
                src = f"{os.path.basename(path)} [stmt {i}]"

                # 1️⃣ Hard safety: write protection
                if not is_readonly(stmt):
                    error(f"  BLOCKED (write op): {src}")
                    errors += 1
                    continue

                # 2️⃣ Architectural rule: skip interactive queries
                if is_parameterized(stmt):
                    warn(f"  Skipped {src}: parameterized (interactive) query")
                    skipped += 1
                    continue

                # 3️⃣ Schema validation (ground truth only)
                labels = set(NODE_LABEL_RE.findall(stmt))
                rels   = set(REL_TYPE_RE.findall(stmt))
                props  = set(PROP_RE.findall(stmt))

                missing_labels = labels - db_labels
                missing_rels   = rels   - db_rels
                missing_props  = props  - db_props

                if missing_labels or missing_rels or missing_props:
                    warn(
                        f"  Skipped {src}: "
                        f"{'labels ' + str(sorted(missing_labels)) if missing_labels else ''} "
                        f"{'rels ' + str(sorted(missing_rels)) if missing_rels else ''} "
                        f"{'props ' + str(sorted(missing_props)) if missing_props else ''}"
                    )
                    skipped += 1
                    continue

                # 4️⃣ Execute verified ground-truth query
                try:
                    rows = run(session, stmt)
                    executed += 1
                    total_rows += len(rows)
                except Neo4jError as e:
                    error(f"  Failed {src}: {e}")
                    errors += 1

    header("PHASE 5 — VERIFICATION SUMMARY")
    print(f"Executed statements : {executed}")
    print(f"Skipped statements  : {skipped}")
    print(f"Total rows returned : {total_rows}")
    print(f"Errors              : {errors}")

if __name__ == "__main__":
    verify_phase5()
