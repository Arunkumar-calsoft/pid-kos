"""Diagnose ambiguity — show keyword discriminators for all tied intents."""
import json
from pathlib import Path

reg = json.loads(Path("engine/phase5_cypher/_meta/queries.json").read_text())
queries = reg["queries"]

TARGET_INTENTS = [
    "instrument_attachment",
    "valve_placement",
    "connectivity_topology",
    "cross_domain",
    "annotation_requests",
    "flow_coverage",
    "drawing_consistency",
    "engineering_inventory",
    "line_attributes",
    "flow_direction",
]

for intent in TARGET_INTENTS:
    entries = [(k, v) for k, v in queries.items() if v["intent"] == intent and v.get("verified")]
    if not entries:
        continue
    print(f"\n=== {intent} ({len(entries)} entries) ===")
    for k, v in entries:
        req = v.get("required_keywords", [])
        boost = v.get("boost_keywords", [])
        excl = v.get("exclude_keywords", [])
        op = v.get("operation", "")
        short_id = k.split("_", 3)[-1] if k.count("_") >= 3 else k
        print(f"  [{op:5s}] {short_id}")
        if req:
            print(f"          required: {req}")
        if boost:
            print(f"          boost:    {boost}")
        if excl:
            print(f"          exclude:  {excl}")
