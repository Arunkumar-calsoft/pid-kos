# agent/review_cli.py
"""
Review CLI — Enrichment Queue Review Interface

Lets a human engineer review LLM-generated Cypher candidates from
enrichment_queue.json and approve or reject each one.

Approved entries are written directly to queries.json (registry).
Rejected entries are marked and left in the queue log.

Usage:
    python -m agent.review_cli
    python -m agent.review_cli --queue-path /custom/path/enrichment_queue.json
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional

_QUEUE_PATH    = Path(__file__).resolve().parents[1] / "logs" / "enrichment_queue.json"
_REGISTRY_PATH = Path(__file__).resolve().parents[1] / "engine" / "phase5_cypher" / "_meta" / "queries.json"


# ---------------------------------------------------------------------------
# Queue reader / writer
# ---------------------------------------------------------------------------

def load_queue(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def save_queue(entries: List[Dict[str, Any]], path: Path) -> None:
    path.write_text(json.dumps(entries, indent=2), encoding="utf-8")


def pending(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [e for e in entries if e.get("status") == "pending_review"]


# ---------------------------------------------------------------------------
# Registry writer
# ---------------------------------------------------------------------------

def append_to_registry(
    entry:         Dict[str, Any],
    registry_path: Path,
    cypher_dir:    Path,
) -> str:
    """
    Writes the approved Cypher to a .cypher file and adds the QueryEntry
    to queries.json. Returns the new query id.
    """
    raw = json.loads(registry_path.read_text(encoding="utf-8"))
    meta         = raw["registry"]
    queries_blob = raw["queries"]

    # Generate new id
    existing_ids  = list(queries_blob.keys())
    numeric_ids   = [
        int(m.group())
        for qid in existing_ids
        if (m := re.search(r"\d+", qid)) is not None
    ]
    next_num      = max(numeric_ids, default=0) + 1
    new_id        = f"q_enriched_{next_num:03d}"

    # Write .cypher file
    cypher_file   = f"enriched/{new_id}.cypher"
    cypher_path   = cypher_dir / cypher_file
    cypher_path.parent.mkdir(parents=True, exist_ok=True)
    cypher_path.write_text(entry["generated_cypher"], encoding="utf-8")

    # Build QueryEntry
    intent_type = entry.get("intent_type") or "unknown_intent"
    new_entry: Dict[str, Any] = {
        "id":                new_id,
        "title":             entry["question"][:80],
        "intent":            intent_type,
        "category":          "enriched",
        "cypher_file":       cypher_file,
        "verified":          True,
        "target_entity":     "",
        "operation":         "list",
        "scope":             "global",
        "output_type":       "table",
        "required_keywords": [],
        "boost_keywords":    [],
        "exclude_keywords":  [],
        "engineer_question": entry["question"],
        "enriched_at":       datetime.now(timezone.utc).isoformat(),
    }

    queries_blob[new_id] = new_entry
    meta["query_count"]  = sum(
        1 for q in queries_blob.values() if q.get("verified")
    )

    registry_path.write_text(json.dumps(raw, indent=2), encoding="utf-8")
    return new_id


# ---------------------------------------------------------------------------
# Review session
# ---------------------------------------------------------------------------

def run_review(
    queue_path:    Path,
    registry_path: Path,
    cypher_dir:    Path,
) -> None:
    entries = load_queue(queue_path)
    queue   = pending(entries)

    if not queue:
        print("No pending candidates in the enrichment queue.")
        return

    print(f"\n{'='*60}")
    print(f"  Enrichment Queue Review — {len(queue)} pending")
    print(f"{'='*60}\n")

    approved = rejected = skipped = 0

    for idx, candidate in enumerate(queue, start=1):
        print(f"[{idx}/{len(queue)}] Question: {candidate['question']}")
        print(f"        Intent  : {candidate.get('intent_type', '—')}")
        print(f"        Outcome : {candidate.get('failure_outcome', '—')}")
        print(f"        Slots   : {candidate.get('slots', {})}")
        print()
        print("  Generated Cypher:")
        for line in candidate["generated_cypher"].splitlines():
            print(f"    {line}")

        if candidate.get("sample_records"):
            print()
            print("  Sample results (up to 3):")
            for row in candidate["sample_records"]:
                print(f"    {row}")

        print()
        action = input(
            "  Action — [a]pprove / [r]eject / [s]kip / [q]uit: "
        ).strip().lower()

        if action == "q":
            print("\nSession ended early.")
            break

        # Find this entry in the full list and update its status
        original = next(
            e for e in entries
            if e["question"] == candidate["question"]
            and e["ts"] == candidate["ts"]
        )

        if action == "a":
            try:
                new_id = append_to_registry(candidate, registry_path, cypher_dir)
                original["status"]      = "approved"
                original["registry_id"] = new_id
                original["reviewed_at"] = datetime.now(timezone.utc).isoformat()
                approved += 1
                print(f"  ✓ Approved → added to registry as {new_id}\n")
            except Exception as exc:
                print(f"  ✗ Failed to write registry entry: {exc}\n")

        elif action == "r":
            reason = input("  Rejection reason (optional): ").strip()
            original["status"]          = "rejected"
            original["rejection_reason"] = reason
            original["reviewed_at"]     = datetime.now(timezone.utc).isoformat()
            rejected += 1
            print(f"  ✗ Rejected.\n")

        else:
            skipped += 1
            print(f"  — Skipped.\n")

        print("-" * 60)

    save_queue(entries, queue_path)

    print(f"\nReview complete.")
    print(f"  Approved : {approved}")
    print(f"  Rejected : {rejected}")
    print(f"  Skipped  : {skipped}")
    print(f"\nQueue saved → {queue_path}")
    if approved:
        print(f"Registry updated → {registry_path}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Review LLM-generated Cypher candidates for registry approval"
    )
    parser.add_argument("--queue-path",    type=Path, default=_QUEUE_PATH)
    parser.add_argument("--registry-path", type=Path, default=_REGISTRY_PATH)
    args = parser.parse_args()

    cypher_dir = args.registry_path.parent.parent

    if not args.queue_path.exists():
        print(f"[ERROR] Queue file not found: {args.queue_path}")
        print("Run registry_enricher.py first to populate the queue.")
        return

    if not args.registry_path.exists():
        print(f"[ERROR] Registry not found: {args.registry_path}")
        return

    run_review(
        queue_path    = args.queue_path,
        registry_path = args.registry_path,
        cypher_dir    = cypher_dir,
    )


if __name__ == "__main__":
    main()