from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import server

DEMO_QUERIES = PROJECT_ROOT / "docs" / "DEMO_QUERIES.md"
LOG_DIR = PROJECT_ROOT / "logs"

QUERY_LINE_RE = re.compile(r"^\|\s*(\d+)\s*\|\s*(.*?)\s*\|$")
VISUAL_VERB_RE = re.compile(r"\b(show|which|where|list|find|highlight)\b", re.IGNORECASE)


def _load_demo_queries(path: Path) -> List[Tuple[int, str]]:
    rows: List[Tuple[int, str]] = []
    seen: Set[int] = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        m = QUERY_LINE_RE.match(raw.strip())
        if not m:
            continue
        qid = int(m.group(1))
        q = m.group(2).strip()
        if not q or qid in seen:
            continue
        rows.append((qid, q))
        seen.add(qid)
    rows.sort(key=lambda x: x[0])
    return rows


def _expected_intent(qid: int) -> Optional[Set[str]]:
    # Strict sections in docs/DEMO_QUERIES.md where intent is unambiguous.
    if 1 <= qid <= 15:
        return {"engineering_inventory"}
    if 16 <= qid <= 24:
        return {"valve_placement"}
    if 25 <= qid <= 31:
        return {"instrument_attachment"}
    if 52 <= qid <= 62:
        return {"line_attributes"}
    if 101 <= qid <= 106:
        return {"external_interfaces"}
    if 107 <= qid <= 114:
        return {"redundancy_patterns"}
    if 115 <= qid <= 120:
        return {"segment_junction_topology"}
    if 121 <= qid <= 128:
        return {"annotation_requests"}
    if 129 <= qid <= 141:
        return {"cross_domain"}
    return None


def _audit_one(
    qid: int,
    query: str,
    pid_id: str,
    node_universe: Set[str],
) -> Dict:
    out: Dict = {
        "id": qid,
        "query": query,
        "intent": None,
        "records_count": 0,
        "highlight_mode": None,
        "highlight_node_ids": 0,
        "highlight_drawable_ids": 0,
        "highlight_pipes": 0,
        "issues": [],
        "error": None,
    }
    try:
        result = server._agent.answer(query, pid_id=pid_id)
        intent = str((result.get("intent") or {}).get("intent_type") or "")
        records = result.get("records") or []
        slots = (result.get("intent") or {}).get("slots") or {}
        anchor = str(slots.get("tag") or "").strip()

        highlight = server._highlight(records, intent, pid_id, anchor, query)
        context = server._build_node_details(records, intent, query, pid_id, anchor)

        out["intent"] = intent
        out["records_count"] = len(records)
        out["highlight_mode"] = highlight.get("mode")

        expected = _expected_intent(qid)
        if expected and intent not in expected:
            out["issues"].append(
                f"intent_mismatch(expected={sorted(expected)},actual={intent})"
            )

        mode = highlight.get("mode")
        if records and mode == "none":
            out["issues"].append("nonempty_records_but_no_highlight")

        if mode == "ids":
            node_ids = [str(x) for x in (highlight.get("node_ids") or []) if str(x)]
            drawable_ids = [nid for nid in node_ids if nid in node_universe]
            out["highlight_node_ids"] = len(node_ids)
            out["highlight_drawable_ids"] = len(drawable_ids)

            if node_ids and not drawable_ids:
                out["issues"].append("ids_highlight_not_drawable")

            by_id = set((context.get("by_id") or {}).keys())
            if drawable_ids and not (set(drawable_ids) & by_id):
                out["issues"].append("ids_without_context_details")

        elif mode == "pipes":
            traces = highlight.get("pipe_traces") or []
            out["highlight_pipes"] = len(traces)
            if not traces:
                out["issues"].append("pipes_mode_without_traces")
            else:
                valid_len = any(len(t.get("trace_nodes") or []) >= 2 for t in traces)
                if not valid_len:
                    out["issues"].append("pipe_traces_too_short")

                any_drawable = False
                for t in traces:
                    for nid in (t.get("trace_nodes") or []):
                        if str(nid) in node_universe:
                            any_drawable = True
                            break
                    if any_drawable:
                        break
                if not any_drawable:
                    out["issues"].append("pipe_traces_not_mappable_to_canvas")

        elif mode == "labels":
            labels = highlight.get("labels") or []
            if records and not labels:
                out["issues"].append("labels_mode_without_labels")

        if VISUAL_VERB_RE.search(query) and records and mode == "none":
            out["issues"].append("visual_query_without_highlight")

    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
        out["issues"].append("query_execution_error")

    return out


def run(pid_id: str, max_queries: int = 0) -> Dict:
    queries = _load_demo_queries(DEMO_QUERIES)
    if max_queries > 0:
        queries = queries[:max_queries]

    node_universe = {
        str(n[0]).strip()
        for n in (server._parse_nodes(pid_id).get("nodes") or [])
        if isinstance(n, list) and n and isinstance(n[0], str) and str(n[0]).strip()
    }

    results: List[Dict] = []
    issue_counter: Counter = Counter()
    intent_counter: Counter = Counter()

    for qid, query in queries:
        item = _audit_one(qid, query, pid_id, node_universe)
        results.append(item)
        if item.get("intent"):
            intent_counter[item["intent"]] += 1
        for issue in item.get("issues") or []:
            issue_counter[issue] += 1

    with_issues = [r for r in results if r.get("issues")]
    error_rows = [r for r in results if r.get("error")]
    by_mode: Dict[str, int] = defaultdict(int)
    for r in results:
        by_mode[str(r.get("highlight_mode") or "none")] += 1

    return {
        "pid_id": pid_id,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "totals": {
            "queries": len(results),
            "with_issues": len(with_issues),
            "with_errors": len(error_rows),
            "issue_rate_pct": round((len(with_issues) / len(results) * 100.0), 2) if results else 0.0,
        },
        "highlight_modes": dict(sorted(by_mode.items(), key=lambda kv: kv[0])),
        "issue_counts": dict(issue_counter.most_common()),
        "intent_counts": dict(intent_counter.most_common()),
        "problem_rows": with_issues,
        "rows": results,
    }


def _write_report(report: Dict) -> Tuple[Path, Path]:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = LOG_DIR / f"trace_consistency_audit_{stamp}.json"
    txt_path = LOG_DIR / f"trace_consistency_audit_{stamp}.txt"

    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    top = report.get("problem_rows", [])[:30]
    lines = [
        f"PID: {report['pid_id']}",
        f"Timestamp: {report['timestamp']}",
        f"Queries: {report['totals']['queries']}",
        f"With issues: {report['totals']['with_issues']} ({report['totals']['issue_rate_pct']}%)",
        f"With errors: {report['totals']['with_errors']}",
        "",
        "Issue counts:",
    ]
    for k, v in report.get("issue_counts", {}).items():
        lines.append(f"  - {k}: {v}")
    lines += ["", "Top problematic queries:"]
    for row in top:
        lines.append(
            f"  - #{row['id']} | intent={row['intent']} | mode={row['highlight_mode']} | issues={row['issues']} | q={row['query']}"
        )

    txt_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, txt_path


def main() -> None:
    ap = argparse.ArgumentParser(description="Audit query/trace/highlight consistency against demo queries")
    ap.add_argument("--pid", default="PID_0", help="PID ID to evaluate (default: PID_0)")
    ap.add_argument("--max", type=int, default=0, help="Limit number of queries (0 = all)")
    args = ap.parse_args()

    report = run(args.pid, args.max)
    json_path, txt_path = _write_report(report)

    print(f"[AUDIT] PID={args.pid}")
    print(f"[AUDIT] Queries={report['totals']['queries']}  Issues={report['totals']['with_issues']}  Errors={report['totals']['with_errors']}")
    print(f"[AUDIT] JSON: {json_path}")
    print(f"[AUDIT] TXT : {txt_path}")

    # Print a short actionable preview in terminal output.
    for row in report.get("problem_rows", [])[:12]:
        print(
            f"[ISSUE] #{row['id']} intent={row['intent']} mode={row['highlight_mode']} "
            f"issues={','.join(row['issues'])} q={row['query']}"
        )


if __name__ == "__main__":
    main()
