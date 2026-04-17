# agent/simple_explainer.py
"""
Simple Explainer — deterministic fallback for NLExplainer.

Used when:
  - LLM client is not configured (GROQ_API_KEY not set)
  - LLM call fails or returns empty response
  - Running in offline / air-gapped mode

Produces clean, engineer-facing plain English answers from query results.
No internal metadata exposed: no intent types, query IDs, category names,
trace objects, or keywords.

Pattern per result shape:
  count query  → "There are N <things> on this drawing."
  list query   → "Found N <things>: TAG-1, TAG-2, ..."
  empty        → "No <things> were found matching your question."
"""
from __future__ import annotations

import re
from typing import Dict, List, Any, Optional
from agent.query_registry import QueryEntry
from agent.property_translations import PROP_TRANSLATIONS, HIDDEN_PROPS, VALUE_TRANSLATIONS


# Note: _PROP_LABELS is now imported as PROP_TRANSLATIONS from property_translations.py
# _HIDDEN_PROPS is now imported as HIDDEN_PROPS from property_translations.py


class SimpleExplainer:

    def explain(
        self,
        *,
        question:    str,
        query_entry: QueryEntry,
        intent:      Dict[str, Any],
        records:     List[Dict[str, Any]],
        traces:      List[Dict[str, Any]],
    ) -> str:
        if not records:
            return self._empty_answer(question, query_entry)

        # Detect answer shape from the records themselves
        if self._is_count_result(records):
            return self._count_answer(records, query_entry)

        if self._is_aggregate_result(records):
            return self._aggregate_answer(records, query_entry)

        return self._list_answer(records, query_entry)

    # ------------------------------------------------------------------
    # Shape detection
    # ------------------------------------------------------------------

    def _is_count_result(self, records: List[Dict[str, Any]]) -> bool:
        """Single row with a 'total' or 'count' key and nothing else meaningful."""
        if len(records) == 1:
            r = records[0]
            return set(r.keys()) <= {"total", "count", "type", "label"}
        return False

    def _is_aggregate_result(self, records: List[Dict[str, Any]]) -> bool:
        """Multiple rows each with a 'total' or 'count' key → breakdown table."""
        if len(records) <= 1:
            return False
        return all("total" in r or "count" in r for r in records)

    # ------------------------------------------------------------------
    # Answer templates
    # ------------------------------------------------------------------

    def _empty_answer(self, question: str, query_entry: QueryEntry) -> str:
        q = question.lower()
        if "upstream" in q:
            return (
                "No upstream equipment found. "
                "This equipment may be at the start of a flow path, "
                "or its connected pipe lines do not have a confirmed flow direction."
            )
        if "downstream" in q:
            return (
                "No downstream equipment found. "
                "This equipment may be a terminal point (for example a vessel or tank), "
                "or its connected pipe lines do not have a confirmed flow direction."
            )
        subject = _subject_from_title(query_entry.get("title", ""))
        plural  = subject if subject in ("equipment", "instrumentation") else f"{subject}s"
        return f"No {plural} were found matching your question."

    def _count_answer(
        self, records: List[Dict[str, Any]], query_entry: QueryEntry
    ) -> str:
        r = records[0]
        n = r.get("total") or r.get("count") or 0
        subject = _subject_from_title(query_entry.get("title", ""))
        qualifier = _qualifier_from_title(query_entry.get("title", ""))
        plural = "" if n == 1 else "s"
        return f"There {'is' if n == 1 else 'are'} {n} {subject}{plural}{qualifier} on this drawing."

    def _aggregate_answer(
        self, records: List[Dict[str, Any]], query_entry: QueryEntry
    ) -> str:
        """Multi-row count breakdown, e.g. type → total."""
        subject = _subject_from_title(query_entry.get("title", ""))
        total   = sum(r.get("total", r.get("count", 0)) for r in records)

        # Find the grouping key (first non-total key)
        group_key: Optional[str] = None
        for r in records[:1]:
            for k in r:
                if k not in ("total", "count"):
                    group_key = k
                    break

        # "equipment" is uncountable — don't pluralise it
        subject_plural = subject if subject in ("equipment", "instrumentation") else f"{subject}s"
        lines = [f"There are {total} {subject_plural} in total on this drawing:"]
        for r in records:
            n     = r.get("total", r.get("count", 0))
            label = r.get(group_key, "") if group_key else ""
            if label:
                lines.append(f"  • {n}× {label}")
            else:
                lines.append(f"  • {n}")
        return "\n".join(lines)

    def _list_answer(
        self, records: List[Dict[str, Any]], query_entry: QueryEntry
    ) -> str:
        subject = _subject_from_title(query_entry.get("title", ""))
        n       = len(records)
        plural  = "s" if n != 1 else ""

        # Find the best "name" field: tag, label, equipment_id, valve_tag, node_id
        name_key = _find_name_key(records[0])

        if name_key:
            # Inline list of tags/labels up to 10, then "and N more"
            names = [str(r[name_key]) for r in records if r.get(name_key)]
            shown, rest = names[:10], names[10:]
            tag_list = ", ".join(shown)
            suffix   = f", and {len(rest)} more" if rest else ""
            return f"Found {n} {subject}{plural}: {tag_list}{suffix}."
        else:
            # Fallback: clean key-value pairs per record
            lines = [f"Found {n} {subject}{plural}:"]
            for r in records[:10]:
                clean = {
                    PROP_TRANSLATIONS.get(k, k):
                        VALUE_TRANSLATIONS.get(k, {}).get(str(v).upper(), v)
                        if k in VALUE_TRANSLATIONS else v
                    for k, v in r.items()
                    if k not in HIDDEN_PROPS and v is not None
                }
                lines.append("  • " + ", ".join(f"{k}: {v}" for k, v in clean.items()))
            if len(records) > 10:
                lines.append(f"  … and {len(records) - 10} more")
            return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _subject_from_title(title: str) -> str:
    """
    Extract a plain-English subject word from a registry title.
    e.g. "01 valve inventory" → "valve"
         "Valves connected pumps" → "valve"
         "Schema-generated: engineering_inventory" → "item"
    """
    title_lower = re.sub(r"^\d+\s*", "", title).lower().strip()

    for word in ("valve", "pump", "tank", "instrument", "annotation",
                 "segment", "line", "equipment", "node", "arrow"):
        if word in title_lower:
            return word

    # Schema-generated titles contain the intent type
    if "inventory" in title_lower or "equipment" in title_lower:
        return "equipment"
    if "flow" in title_lower or "direction" in title_lower:
        return "flow indicator"
    if "consistency" in title_lower or "quality" in title_lower:
        return "issue"
    if "external" in title_lower or "interface" in title_lower:
        return "interface"

    return "item"


def _qualifier_from_title(title: str) -> str:
    """
    Add a contextual qualifier for specificity.
    e.g. "valves connected pumps" → " connected to pumps"
    """
    title_lower = title.lower()
    if "pump" in title_lower and "valve" in title_lower:
        return " connected to pumps"
    if "pipe" in title_lower or "segment" in title_lower:
        return " on pipe segments"
    if "not connected" in title_lower or "floating" in title_lower:
        return " without pipe connections"
    return ""


def _find_name_key(record: Dict[str, Any]) -> Optional[str]:
    """Return the most useful identifier key from a record."""
    for key in ("tag", "valve_tag", "equipment_id", "label",
                "valve_node", "connected_node", "segment", "node"):
        if key in record and record[key] is not None:
            return key
    return None