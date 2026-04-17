# engine/phase2_flow/arrow_debug.py
#
# Debug utilities for Phase 2 arrow binding inspection.
#
# Changes from pid_kos version:
#   - evidence_path default: 'data/phase2_evidence.json' → 'logs/phase2_evidence.json'

import json
import os
from collections import defaultdict

_DEFAULT_EVIDENCE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "logs", "phase2_evidence.json",
)


def print_arrow_bindings(arrow_id, start_node, end_node, confidence=None, extra_info=None):
    """Debug print for a single arrow binding."""
    print(f"[Arrow Binding] Arrow ID: {arrow_id}")
    print(f"  Start Node : {start_node}")
    print(f"  End Node   : {end_node}")
    if confidence is not None:
        print(f"  Confidence : {confidence}")
    if extra_info:
        for key, value in extra_info.items():
            print(f"  {key}: {value}")
    print("-" * 40)


def print_all_arrow_bindings(bindings_list):
    """Debug print for a list of arrow binding dicts."""
    print(f"[Total Arrow Bindings: {len(bindings_list)}]")
    for binding in bindings_list:
        print_arrow_bindings(
            arrow_id=binding.get("arrow_id"),
            start_node=binding.get("start_node"),
            end_node=binding.get("end_node"),
            confidence=binding.get("confidence"),
            extra_info=binding.get("extra_info"),
        )


def debug_arrow_evidence(evidence_path=None, top_n=10):
    """
    Load Phase 2 evidence JSON and print top_n items with details.
    """
    if evidence_path is None:
        evidence_path = _DEFAULT_EVIDENCE

    try:
        with open(evidence_path, "r") as f:
            evidence = json.load(f)
    except FileNotFoundError:
        print(f"[ERROR] Evidence file not found: {evidence_path}")
        return

    print(f"[INFO] Loaded {len(evidence)} evidence items from {evidence_path}")
    for i, item in enumerate(evidence[:top_n]):
        print(
            f"[DEBUG] {i+1}: Arrow '{item['arrow_id']}' → Segment '{item['pipe_segment_id']}' | "
            f"dx={item['dx']}, dy={item['dy']}, "
            f"direction_hint={item['direction_hint']}, "
            f"cosine={item.get('cosine_alignment')}, "
            f"confidence={item.get('confidence')}"
        )

    if len(evidence) > top_n:
        print(f"[INFO] ...and {len(evidence) - top_n} more items")


def summarize_bindings(evidence_path=None):
    """Print arrow count per LogicalPipeSegment."""
    if evidence_path is None:
        evidence_path = _DEFAULT_EVIDENCE

    try:
        with open(evidence_path, "r") as f:
            evidence = json.load(f)
    except FileNotFoundError:
        print(f"[ERROR] Evidence file not found: {evidence_path}")
        return

    seg_counts = defaultdict(int)
    for item in evidence:
        seg_counts[item["pipe_segment_id"]] += 1

    print("[INFO] Arrow bindings per LogicalPipeSegment:")
    for seg, count in sorted(seg_counts.items(), key=lambda x: -x[1]):
        print(f"  '{seg}': {count} arrow(s)")