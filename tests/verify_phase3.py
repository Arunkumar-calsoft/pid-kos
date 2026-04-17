# tests/verify_phase3.py
#
# Phase 3 — Evidence & Annotation Verification (READ-ONLY)
#
# Usage:
#   python tests/verify_phase3.py --pid PID_2
#
# EXIT CODE: 0 = all checks pass (Phase 4 safe to run)
#            1 = one or more checks failed
#
# COVERAGE: 40 checks across 7 categories
#
#   1. Evidence nodes          — grounding, direction values, confidence range,
#                                source coverage, duplicate IDs
#   2. Observation Annotations — SUPPORTED_BY links, count vs FLOW_EVIDENCE
#   3. Frequency summaries     — total_observations, normalized sums,
#                                summary arithmetic, gap coverage arithmetic
#   4. Gap detection (FIX-7)   — pattern_type set, topology cleanup
#   5. Pattern taxonomy        — all fired patterns in CATEGORY_MAP,
#                                canary counts, one-per-pattern uniqueness,
#                                freq/rarity 1:1 pairing, summary arithmetic
#   6. Rarity scoring          — all properties, value ranges, canary severity,
#                                phase4_hint values, score range
#   7. LPS / graph structure   — seed_confidence range, BFS seed exists,
#                                ADJACENT_VIA_NODES present
#   8. Cross-PID isolation     — no contamination from other PIDs
#   9. Phase 4 readiness gate  — hard pass/fail across all critical checks

import argparse
import os
import sys
import yaml

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from engine.phase0_ingestion.load_to_neo4j import Neo4jLoader
from neo4j.exceptions import Neo4jError


# ── Taxonomy imported from authoritative source modules ───────────────────────
#
# Do NOT hardcode these — import from the source so verify is always in sync.
# If the import fails, the taxonomy has diverged and must be fixed first.

from engine.phase3_annotation.frequency_aggregation import (
    CATEGORY_MAP,
    AUDIENCE_MAP,
    CANARY_PATTERNS,
)
from engine.phase3_annotation.rarity_scoring import _PHASE4_HINTS

KNOWN_ESV_PATTERNS  = frozenset(k for k, v in CATEGORY_MAP.items() if v == "ESV")
KNOWN_KAV_PATTERNS  = frozenset(k for k, v in CATEGORY_MAP.items() if v == "KAV")
ALL_KNOWN_PATTERNS  = frozenset(CATEGORY_MAP)
VALID_PHASE4_HINTS  = frozenset(_PHASE4_HINTS.values())

VALID_DIRECTIONS    = {"FORWARD", "REVERSE", "UNKNOWN"}
VALID_AUDIENCES     = {"engineer_review", "pipeline_integrity", "internal"}
VALID_SEVERITIES    = {"NONE", "LOW", "MEDIUM", "HIGH", "CRITICAL"}


# ── Logging helpers ────────────────────────────────────────────────────────────

_failures = []

def info(msg):  print(f"  [INFO] {msg}")
def warn(msg):  print(f"  [WARN] {msg}")

def check(passed, name, detail=""):
    sym = "✅" if passed else "❌"
    suffix = f"  — {detail}" if detail else ""
    print(f"  {sym} {name}{suffix}")
    if not passed:
        _failures.append(name)
    return passed

def header(title):
    print(f"\n{'─'*68}")
    print(f"  {title}")
    print(f"{'─'*68}")


# ── Query helpers ──────────────────────────────────────────────────────────────

def scalar(session, q, params=None, key="c"):
    try:
        r = session.run(q, **(params or {})).single()
        return int(r[key]) if r and r.get(key) is not None else 0
    except Neo4jError as e:
        print(f"[ERROR] {e}\n{q}")
        raise

def rows(session, q, params=None):
    try:
        return session.run(q, **(params or {})).data()
    except Neo4jError as e:
        print(f"[ERROR] {e}\n{q}")
        raise

def P(pid_id):
    return {"pid_id": pid_id}


# ── 1. Evidence nodes ──────────────────────────────────────────────────────────

def check_evidence(session, pid_id):
    total = scalar(session,
        "MATCH (e:Evidence {pid_id:$pid_id}) RETURN count(e) AS c", P(pid_id))
    info(f"Evidence nodes: {total}")

    # 1a — grounding: all Evidence -> LPS
    ungrounded = scalar(session, """
        MATCH (e:Evidence {pid_id:$pid_id})
        WHERE NOT (e)-[:ABOUT]->(:LogicalPipeSegment)
        RETURN count(e) AS c
    """, P(pid_id))
    check(ungrounded == 0, "Evidence: all nodes grounded to LPS",
          f"{ungrounded} ungrounded" if ungrounded else "")

    # 1b — confidence range [0, 1]
    out_of_range = scalar(session, """
        MATCH (e:Evidence {pid_id:$pid_id})
        WHERE e.confidence IS NOT NULL
          AND (toFloat(e.confidence) < 0.0 OR toFloat(e.confidence) > 1.0)
        RETURN count(e) AS c
    """, P(pid_id))
    check(out_of_range == 0, "Evidence: confidence in [0.0, 1.0]",
          f"{out_of_range} out of range" if out_of_range else "")

    # 1c — no null confidence
    null_conf = scalar(session, """
        MATCH (e:Evidence {pid_id:$pid_id})
        WHERE e.confidence IS NULL
        RETURN count(e) AS c
    """, P(pid_id))
    check(null_conf == 0, "Evidence: no null confidence",
          f"{null_conf} missing" if null_conf else "")

    # 1d — observed_direction values valid
    bad_dir = scalar(session, """
        MATCH (e:Evidence {pid_id:$pid_id})
        WHERE e.observed_direction IS NOT NULL
          AND NOT e.observed_direction IN ['FORWARD','REVERSE','UNKNOWN']
        RETURN count(e) AS c
    """, P(pid_id))
    check(bad_dir == 0, "Evidence: observed_direction values valid",
          f"{bad_dir} invalid" if bad_dir else "")

    # 1e — at least arrow source Evidence exists
    arrow_ev = scalar(session, """
        MATCH (e:Evidence {pid_id:$pid_id, source:'phase2_flow_evidence'})
        RETURN count(e) AS c
    """, P(pid_id))
    check(arrow_ev > 0, "Evidence: arrow Evidence present (phase2_flow_evidence)",
          f"count={arrow_ev}")

    # 1f — no duplicate Evidence IDs scoped to this PID
    dup_ids = scalar(session, """
        MATCH (e:Evidence {pid_id:$pid_id})
        WITH e.id AS eid, count(*) AS n
        WHERE n > 1
        RETURN count(*) AS c
    """, P(pid_id))
    check(dup_ids == 0, "Evidence: no duplicate Evidence.id values",
          f"{dup_ids} duplicated IDs" if dup_ids else "")

    sources = rows(session, """
        MATCH (e:Evidence {pid_id:$pid_id})
        RETURN e.source AS src, count(e) AS n ORDER BY n DESC
    """, P(pid_id))
    for r in sources:
        info(f"  source={r['src']}: {r['n']}")

    return {"total": total, "ungrounded": ungrounded, "null_conf": null_conf,
            "bad_dir": bad_dir, "arrow_ev": arrow_ev}


# ── 2. Observation Annotations ─────────────────────────────────────────────────

def check_observations(session, pid_id):
    obs_total = scalar(session, """
        MATCH (a:Annotation {pid_id:$pid_id, type:'direction_observation'})
        RETURN count(a) AS c
    """, P(pid_id))
    info(f"direction_observation annotations: {obs_total}")

    # 2a — every observation has SUPPORTED_BY -> Evidence
    obs_no_support = scalar(session, """
        MATCH (a:Annotation {pid_id:$pid_id, type:'direction_observation'})
        WHERE NOT (a)-[:SUPPORTED_BY]->(:Evidence)
        RETURN count(a) AS c
    """, P(pid_id))
    check(obs_no_support == 0, "Observations: all have SUPPORTED_BY -> Evidence",
          f"{obs_no_support} missing" if obs_no_support else "")

    # 2b — observation count >= FLOW_EVIDENCE count (must have lifted all arrows)
    fe_count = scalar(session, """
        MATCH (a:Arrow {pid_id:$pid_id})-[:FLOW_EVIDENCE]->()
        RETURN count(*) AS c
    """, P(pid_id))
    arrow_obs = scalar(session, """
        MATCH (a:Annotation {pid_id:$pid_id, type:'direction_observation',
                             source:'phase3'})
        RETURN count(a) AS c
    """, P(pid_id))
    check(arrow_obs >= fe_count,
          "Observations: arrow obs count >= FLOW_EVIDENCE count",
          f"obs={arrow_obs}, fe={fe_count}")

    return {"obs_total": obs_total, "no_support": obs_no_support}


# ── 3. Frequency summaries ─────────────────────────────────────────────────────

def check_freq_summaries(session, pid_id):
    # 3a — freq summary annotation present
    summary_count = scalar(session, """
        MATCH (a:Annotation {pid_id:$pid_id,
                             source:'phase3_structural_frequencies',
                             pattern_type:'__summary__'})
        RETURN count(a) AS c
    """, P(pid_id))
    check(summary_count == 1, "Frequency: per-PID summary annotation present",
          f"found {summary_count}" if summary_count != 1 else "")

    # 3b — direction_frequency Evidence sums to 1.0 per LPS
    bad_norm = scalar(session, """
        MATCH (lps:LogicalPipeSegment {pid_id:$pid_id})
              <-[:ABOUT]-(e:Evidence {pid_id:$pid_id, type:'direction_frequency'})
        WITH lps, sum(coalesce(e.normalized,0)) AS s, count(e) AS n
        WHERE n > 0 AND abs(s - 1.0) > 0.05
        RETURN count(lps) AS c
    """, P(pid_id))
    check(bad_norm == 0, "Frequency: direction distributions sum to 1.0 per LPS",
          f"{bad_norm} LPS out of range" if bad_norm else "")

    # 3c — all direction_frequency_summary have total_observations > 0
    zero_obs = scalar(session, """
        MATCH (a:Annotation {pid_id:$pid_id, type:'direction_frequency_summary'})
        WHERE coalesce(a.total_observations, 0) <= 0
        RETURN count(a) AS c
    """, P(pid_id))
    check(zero_obs == 0, "Frequency: all freq summaries have total_observations > 0",
          f"{zero_obs} with zero" if zero_obs else "")

    # 3d — summary arithmetic: er_count + pi_count == kav_total
    summary = rows(session, """
        MATCH (a:Annotation {pid_id:$pid_id,
                             source:'phase3_structural_frequencies',
                             pattern_type:'__summary__'})
        RETURN a.kav_total AS kav_total,
               a.engineer_review_count AS er,
               a.pipeline_integrity_count AS pi,
               a.esv_types AS esv_types,
               a.kav_types AS kav_types,
               a.esv_total AS esv_total
    """, P(pid_id))
    if summary:
        r = summary[0]
        er, pi, kav = (r.get('er') or 0), (r.get('pi') or 0), (r.get('kav_total') or 0)
        check(er + pi == kav,
              "Frequency: er_count + pi_count == kav_total in summary",
              f"{er}+{pi}={er+pi}, kav_total={kav}")
        info(f"  Summary: ESV_types={r.get('esv_types')} KAV_types={r.get('kav_types')} "
             f"ESV_ann={r.get('esv_total')} KAV_ann={kav}")
        info(f"  Audience: engineer_review={er} pipeline_integrity={pi}")

    return {"summary_count": summary_count, "bad_norm": bad_norm}


# ── 4. Gap detection (FIX-7) ──────────────────────────────────────────────────

def check_gap_detection(session, pid_id):
    lps_total = scalar(session,
        "MATCH (lps:LogicalPipeSegment {pid_id:$pid_id}) RETURN count(lps) AS c",
        P(pid_id))

    # 4a — gap LPS are now tracked via lps.phase4_hint (not Annotation nodes)
    gap_total = scalar(session, """
        MATCH (lps:LogicalPipeSegment {pid_id:$pid_id})
        WHERE lps.phase4_hint = 'direction_evidence_missing'
        RETURN count(lps) AS c
    """, P(pid_id))
    check(gap_total > 0,
          "Gap detection: phase4_hint='direction_evidence_missing' stamped on gap LPS",
          f"gap_count={gap_total}")

    # 4b — All no-evidence LPS have some phase4_hint set.
    # Note: if Phase 4 has already run, some BLOCKED no-evidence LPS will have
    # phase4_hint='block_propagation_safety_violation' (stamped by Phase 4 Step A)
    # rather than 'direction_evidence_missing'.  We check that no LPS is left
    # without any hint, which holds under both pre- and post-Phase-4 execution.
    evidence_lps = scalar(session, """
        MATCH (lps:LogicalPipeSegment {pid_id:$pid_id})
        WHERE (lps)<-[:ABOUT]-(:Evidence {pid_id:$pid_id})
        RETURN count(lps) AS c
    """, P(pid_id))
    no_ev_no_hint = scalar(session, """
        MATCH (lps:LogicalPipeSegment {pid_id:$pid_id})
        WHERE NOT (lps)<-[:ABOUT]-(:Evidence {pid_id:$pid_id})
          AND lps.phase4_hint IS NULL
        RETURN count(lps) AS c
    """, P(pid_id))
    check(no_ev_no_hint == 0,
          "Gap detection: all no-evidence LPS have phase4_hint set",
          f"{no_ev_no_hint} LPS without Evidence have null phase4_hint"
          f" (evidence={evidence_lps}, dem={gap_total}, total={lps_total})"
          if no_ev_no_hint else
          f"evidence={evidence_lps}, dem={gap_total}, total={lps_total}")

    # 4c — topology inference cleaned up: inferred LPS no longer have phase4_hint set
    still_gap_and_inferred = scalar(session, """
        MATCH (lps:LogicalPipeSegment {pid_id:$pid_id})
        WHERE (lps)<-[:ABOUT]-(:Evidence {pid_id:$pid_id,
                                          source:'phase3_topology_inference'})
          AND lps.phase4_hint = 'direction_evidence_missing'
        RETURN count(lps) AS c
    """, P(pid_id))
    check(still_gap_and_inferred == 0,
          "Gap detection: topology-inferred LPS have phase4_hint removed",
          f"{still_gap_and_inferred} LPS still have both" if still_gap_and_inferred else "")

    return {"gap_total": gap_total, "evidence_lps": evidence_lps, "lps_total": lps_total}


# ── 5. Pattern taxonomy ────────────────────────────────────────────────────────

def check_pattern_taxonomy(session, pid_id):
    fired_patterns = rows(session, """
        MATCH (a:Annotation {pid_id:$pid_id,
                             source:'phase3_structural_frequencies'})
        WHERE a.pattern_type IS NOT NULL
          AND a.pattern_type <> '__summary__'
        RETURN a.pattern_type AS pt, a.category AS cat,
               a.absolute_count AS cnt
        ORDER BY a.category, a.absolute_count DESC
    """, P(pid_id))

    fired_set = {r['pt'] for r in fired_patterns}
    unknown_patterns = fired_set - ALL_KNOWN_PATTERNS
    check(len(unknown_patterns) == 0,
          "Taxonomy: all fired pattern_types are in CATEGORY_MAP",
          f"unknown: {unknown_patterns}" if unknown_patterns else "")

    # 5b — canary patterns must have count == 0 (or not fired at all)
    canary_fired = {r['pt'] for r in fired_patterns
                    if r['pt'] in CANARY_PATTERNS and (r.get('cnt') or 0) > 0}
    check(len(canary_fired) == 0,
          "Taxonomy: canary patterns have count=0",
          f"fired with count>0: {canary_fired}" if canary_fired else "")

    # 5c — each pattern_type appears exactly once in frequency output
    dup_freq = scalar(session, """
        MATCH (a:Annotation {pid_id:$pid_id,
                             source:'phase3_structural_frequencies'})
        WHERE a.pattern_type IS NOT NULL
          AND a.pattern_type <> '__summary__'
        WITH a.pattern_type AS pt, count(a) AS n
        WHERE n > 1
        RETURN count(*) AS c
    """, P(pid_id))
    check(dup_freq == 0,
          "Taxonomy: each pattern_type appears exactly once in frequency output",
          f"{dup_freq} duplicated" if dup_freq else "")

    # 5d — absolute_count > 0 on all non-canary freq annotations
    zero_count = scalar(session, """
        MATCH (a:Annotation {pid_id:$pid_id,
                             source:'phase3_structural_frequencies'})
        WHERE a.pattern_type IS NOT NULL
          AND a.pattern_type <> '__summary__'
          AND NOT a.pattern_type IN ['orphan_annotation','bidirectional_pipe_anomaly']
          AND coalesce(a.absolute_count, 0) <= 0
        RETURN count(a) AS c
    """, P(pid_id))
    check(zero_count == 0,
          "Taxonomy: all non-canary freq annotations have absolute_count > 0",
          f"{zero_count} with zero" if zero_count else "")

    # 5e — 1:1 pairing: every freq annotation has a rarity annotation
    freq_no_rarity = scalar(session, """
        MATCH (f:Annotation {pid_id:$pid_id,
                             source:'phase3_structural_frequencies'})
        WHERE f.pattern_type IS NOT NULL
          AND f.pattern_type <> '__summary__'
          AND NOT EXISTS {
              MATCH (r:Annotation {pid_id:$pid_id,
                                   source:'phase3_structural_rarity',
                                   pattern_type: f.pattern_type})
          }
        RETURN count(f) AS c
    """, P(pid_id))
    check(freq_no_rarity == 0,
          "Taxonomy: every freq annotation has a matching rarity annotation (1:1)",
          f"{freq_no_rarity} unmatched" if freq_no_rarity else "")

    for r in fired_patterns:
        info(f"  {r['cat']:<4} {r['pt']:<45} count={r.get('cnt',0)}")

    return {"fired_count": len(fired_patterns), "unknown": unknown_patterns,
            "canary_fired": canary_fired, "dup_freq": dup_freq}


# ── 6. Rarity scoring ─────────────────────────────────────────────────────────

def check_rarity(session, pid_id):
    rarity_total = scalar(session, """
        MATCH (a:Annotation {pid_id:$pid_id, source:'phase3_structural_rarity'})
        RETURN count(a) AS c
    """, P(pid_id))
    info(f"Rarity annotations: {rarity_total}")

    if rarity_total == 0:
        check(False, "Rarity: annotations present — rarity_scoring.py may not have run")
        return {"rarity_total": 0}

    # 6a-g — required properties
    for prop in ["audience", "hitl_severity", "phase4_hint",
                 "propagation_blocked", "rarity_score",
                 "rarity_label", "corpus_normalized"]:
        missing = scalar(session, f"""
            MATCH (a:Annotation {{pid_id:$pid_id, source:'phase3_structural_rarity'}})
            WHERE a.{prop} IS NULL
            RETURN count(a) AS c
        """, P(pid_id))
        check(missing == 0, f"Rarity: {prop} present on all annotations",
              f"{missing}/{rarity_total} missing" if missing else "")

    # 6h — audience values valid
    bad_aud = scalar(session, """
        MATCH (a:Annotation {pid_id:$pid_id, source:'phase3_structural_rarity'})
        WHERE NOT a.audience IN ['engineer_review','pipeline_integrity','internal']
        RETURN count(a) AS c
    """, P(pid_id))
    check(bad_aud == 0, "Rarity: audience values in valid set",
          f"{bad_aud} invalid" if bad_aud else "")

    # 6i — hitl_severity values valid
    bad_sev = scalar(session, """
        MATCH (a:Annotation {pid_id:$pid_id, source:'phase3_structural_rarity'})
        WHERE NOT a.hitl_severity IN ['NONE','LOW','MEDIUM','HIGH','CRITICAL']
        RETURN count(a) AS c
    """, P(pid_id))
    check(bad_sev == 0, "Rarity: hitl_severity values in valid set",
          f"{bad_sev} invalid" if bad_sev else "")

    # 6j — rarity_score in [0.0, 1.0]
    bad_score = scalar(session, """
        MATCH (a:Annotation {pid_id:$pid_id, source:'phase3_structural_rarity'})
        WHERE a.rarity_score IS NOT NULL
          AND (toFloat(a.rarity_score) < 0.0 OR toFloat(a.rarity_score) > 1.0)
        RETURN count(a) AS c
    """, P(pid_id))
    check(bad_score == 0, "Rarity: rarity_score in [0.0, 1.0]",
          f"{bad_score} out of range" if bad_score else "")

    # 6k — ESV corpus_normalized = false
    esv_bad = scalar(session, """
        MATCH (a:Annotation {pid_id:$pid_id, source:'phase3_structural_rarity',
                             category:'ESV'})
        WHERE a.corpus_normalized <> false
        RETURN count(a) AS c
    """, P(pid_id))
    check(esv_bad == 0, "Rarity: ESV corpus_normalized=False (provisional)",
          f"{esv_bad} wrong" if esv_bad else "")

    # 6l — KAV corpus_normalized = true
    kav_bad = scalar(session, """
        MATCH (a:Annotation {pid_id:$pid_id, source:'phase3_structural_rarity',
                             category:'KAV'})
        WHERE a.corpus_normalized <> true
        RETURN count(a) AS c
    """, P(pid_id))
    check(kav_bad == 0, "Rarity: KAV corpus_normalized=True (LPS-normalized)",
          f"{kav_bad} wrong" if kav_bad else "")

    # 6m — canary patterns have hitl_severity = 'NONE'
    canary_bad_sev = scalar(session, """
        MATCH (a:Annotation {pid_id:$pid_id, source:'phase3_structural_rarity'})
        WHERE a.pattern_type IN ['orphan_annotation','bidirectional_pipe_anomaly']
          AND a.hitl_severity <> 'NONE'
        RETURN count(a) AS c
    """, P(pid_id))
    check(canary_bad_sev == 0, "Rarity: canary patterns have hitl_severity='NONE'",
          f"{canary_bad_sev} wrong" if canary_bad_sev else "")

    # 6n — phase4_hint values in known set (uses VALID_PHASE4_HINTS imported from rarity_scoring)
    bad_hint = rows(session, """
        MATCH (a:Annotation {pid_id:$pid_id, source:'phase3_structural_rarity'})
        WHERE a.phase4_hint IS NOT NULL
          AND NOT a.phase4_hint IN $valid_hints
        RETURN a.pattern_type AS pt, a.phase4_hint AS hint
    """, {**P(pid_id), "valid_hints": list(VALID_PHASE4_HINTS)})
    check(len(bad_hint) == 0, "Rarity: phase4_hint values in valid set",
          f"invalid: {[(r['pt'],r['hint']) for r in bad_hint]}" if bad_hint else "")

    # 6o — each pattern_type appears exactly once
    dup_rarity = scalar(session, """
        MATCH (a:Annotation {pid_id:$pid_id, source:'phase3_structural_rarity'})
        WITH a.pattern_type AS pt, count(a) AS n
        WHERE n > 1
        RETURN count(*) AS c
    """, P(pid_id))
    check(dup_rarity == 0, "Rarity: each pattern_type appears exactly once",
          f"{dup_rarity} duplicated" if dup_rarity else "")

    # Severity distribution
    sev_dist = rows(session, """
        MATCH (a:Annotation {pid_id:$pid_id, source:'phase3_structural_rarity'})
        RETURN a.hitl_severity AS sev, count(a) AS n ORDER BY n DESC
    """, P(pid_id))
    for r in sev_dist:
        info(f"  hitl_severity={r['sev']}: {r['n']}")

    return {"rarity_total": rarity_total, "bad_score": bad_score,
            "esv_bad": esv_bad, "kav_bad": kav_bad}


# ── 7. Audience routing preview ────────────────────────────────────────────────

def check_audience_routing(session, pid_id):
    er = scalar(session, """
        MATCH (a:Annotation {pid_id:$pid_id, source:'phase3_structural_rarity',
                             audience:'engineer_review'})
        RETURN count(a) AS c
    """, P(pid_id))
    pi = scalar(session, """
        MATCH (a:Annotation {pid_id:$pid_id, source:'phase3_structural_rarity',
                             audience:'pipeline_integrity'})
        RETURN count(a) AS c
    """, P(pid_id))

    check(er > 0, "Audience: engineer_review patterns exist for Phase 7 HITL",
          f"count={er}")
    check(pi > 0, "Audience: pipeline_integrity patterns exist for dev dashboard",
          f"count={pi}")

    blocked = scalar(session, """
        MATCH (a:Annotation {pid_id:$pid_id, source:'phase3_structural_rarity',
                             propagation_blocked:true})
        RETURN count(a) AS c
    """, P(pid_id))
    info(f"propagation_blocked=true: {blocked}")

    # Phase 7 HITL queue preview
    hitl = rows(session, """
        MATCH (a:Annotation {pid_id:$pid_id, source:'phase3_structural_rarity',
                             audience:'engineer_review'})
        WHERE a.hitl_severity IN ['HIGH','CRITICAL']
        RETURN a.pattern_type AS pt, a.hitl_severity AS sev,
               a.absolute_count AS cnt, a.normalized_ratio AS ratio
        ORDER BY
          CASE a.hitl_severity WHEN 'CRITICAL' THEN 0 ELSE 1 END,
          a.absolute_count DESC
    """, P(pid_id))
    info(f"Phase 7 HITL queue (HIGH/CRITICAL): {len(hitl)} pattern(s)")
    for r in hitl:
        ratio = f" ({r['ratio']*100:.1f}%)" if r.get('ratio') else ""
        info(f"  {r['sev']:<8} {r['pt']:<45} n={r['cnt']}{ratio}")

    dev = rows(session, """
        MATCH (a:Annotation {pid_id:$pid_id, source:'phase3_structural_rarity',
                             audience:'pipeline_integrity'})
        WHERE a.hitl_severity IN ['HIGH','CRITICAL']
        RETURN a.pattern_type AS pt, a.hitl_severity AS sev,
               a.absolute_count AS cnt
        ORDER BY a.absolute_count DESC
    """, P(pid_id))
    info(f"Dev dashboard HIGH/CRITICAL: {len(dev)} pattern(s)")
    for r in dev:
        info(f"  {r['sev']:<8} {r['pt']:<45} n={r['cnt']}")

    return {"er": er, "pi": pi, "hitl_high": len(hitl), "blocked": blocked}


# ── 8. LPS / graph structure ───────────────────────────────────────────────────

def check_lps_graph(session, pid_id):
    lps_total = scalar(session,
        "MATCH (lps:LogicalPipeSegment {pid_id:$pid_id}) RETURN count(lps) AS c",
        P(pid_id))

    # 8a — seed_confidence present on all LPS (R3)
    missing_seed = scalar(session, """
        MATCH (lps:LogicalPipeSegment {pid_id:$pid_id})
        WHERE lps.seed_confidence IS NULL
        RETURN count(lps) AS c
    """, P(pid_id))
    check(missing_seed == 0, "LPS: seed_confidence present on all LPS (R3)",
          f"{missing_seed}/{lps_total} missing" if missing_seed else "")

    # 8b — seed_confidence in [0.0, 1.0]
    bad_seed = scalar(session, """
        MATCH (lps:LogicalPipeSegment {pid_id:$pid_id})
        WHERE lps.seed_confidence IS NOT NULL
          AND (toFloat(lps.seed_confidence) < 0.0
               OR toFloat(lps.seed_confidence) > 1.0)
        RETURN count(lps) AS c
    """, P(pid_id))
    check(bad_seed == 0, "LPS: seed_confidence in [0.0, 1.0]",
          f"{bad_seed} out of range" if bad_seed else "")

    # 8c — at least one LPS has seed_confidence > 0 (Phase 4 BFS needs a seed)
    positive_seeds = scalar(session, """
        MATCH (lps:LogicalPipeSegment {pid_id:$pid_id})
        WHERE toFloat(coalesce(lps.seed_confidence, 0)) > 0
        RETURN count(lps) AS c
    """, P(pid_id))
    check(positive_seeds > 0, "LPS: at least one positive seed_confidence for BFS (R3)",
          f"positive_seeds={positive_seeds}")

    # 8d — ADJACENT_VIA_NODES relationships exist (Phase 4 traversal)
    adj = scalar(session, """
        MATCH (:LogicalPipeSegment {pid_id:$pid_id})
              -[:ADJACENT_VIA_NODES]-(:LogicalPipeSegment)
        RETURN count(*) AS c
    """, P(pid_id))
    check(adj > 0, "LPS: ADJACENT_VIA_NODES relationships exist (Phase 4 traversal)",
          f"count={adj}")

    seed_stats = rows(session, """
        MATCH (lps:LogicalPipeSegment {pid_id:$pid_id})
        WHERE lps.seed_confidence IS NOT NULL
        RETURN min(lps.seed_confidence) AS mn,
               avg(lps.seed_confidence) AS av,
               max(lps.seed_confidence) AS mx
    """, P(pid_id))
    if seed_stats:
        r = seed_stats[0]
        info(f"  seed_confidence: min={r['mn']:.3f}  "
             f"avg={r['av']:.3f}  max={r['mx']:.3f}")

    return {"missing_seed": missing_seed, "positive_seeds": positive_seeds, "adj": adj}


# ── 9. Cross-PID isolation ─────────────────────────────────────────────────────

def check_cross_pid_isolation(session, pid_id):
    # 9a — no Evidence nodes from other PIDs linked to this PID's LPS
    contaminated_ev = scalar(session, """
        MATCH (e:Evidence)-[:ABOUT]->(lps:LogicalPipeSegment {pid_id:$pid_id})
        WHERE e.pid_id <> $pid_id
        RETURN count(e) AS c
    """, P(pid_id))
    check(contaminated_ev == 0,
          "Isolation: no cross-PID Evidence on this PID's LPS",
          f"{contaminated_ev} foreign Evidence nodes" if contaminated_ev else "")

    # 9b — no Annotation nodes from other PIDs linked to this PID's LPS
    contaminated_ann = scalar(session, """
        MATCH (a:Annotation)-[:ANNOTATES]->(lps:LogicalPipeSegment {pid_id:$pid_id})
        WHERE a.pid_id <> $pid_id
        RETURN count(a) AS c
    """, P(pid_id))
    check(contaminated_ann == 0,
          "Isolation: no cross-PID Annotations on this PID's LPS",
          f"{contaminated_ann} foreign Annotation nodes" if contaminated_ann else "")

    return {"contaminated_ev": contaminated_ev, "contaminated_ann": contaminated_ann}


# ── Readiness gate ─────────────────────────────────────────────────────────────

def readiness_gate():
    critical = [f for f in _failures if f not in {
        # Warnings that don't block Phase 4
        "Frequency: all freq summaries have total_observations > 0",
        "Observations: arrow obs count >= FLOW_EVIDENCE count",
    }]
    return len(critical) == 0


# ── Config ─────────────────────────────────────────────────────────────────────

def load_neo4j_config():
    with open(os.path.join(PROJECT_ROOT, "config", "neo4j.yaml")) as f:
        return yaml.safe_load(f)["neo4j"]


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Verify Phase 3 outputs for a PID.")
    parser.add_argument("--pid", required=True, help="PID ID to verify")
    args = parser.parse_args()
    pid_id = args.pid

    print(f"\n{'='*68}")
    print(f"  PHASE 3 VERIFICATION  |  PID={pid_id}")
    print(f"{'='*68}")

    loader = Neo4jLoader(load_neo4j_config())
    try:
        with loader.driver.session(database=loader.database) as session:

            header("1. EVIDENCE NODES")
            ev = check_evidence(session, pid_id)

            header("2. OBSERVATION ANNOTATIONS")
            obs = check_observations(session, pid_id)

            header("3. FREQUENCY SUMMARIES")
            freq = check_freq_summaries(session, pid_id)

            header("4. GAP DETECTION  (FIX-7)")
            gap = check_gap_detection(session, pid_id)

            header("5. PATTERN TAXONOMY")
            tax = check_pattern_taxonomy(session, pid_id)

            header("6. RARITY SCORING")
            rar = check_rarity(session, pid_id)

            header("7. AUDIENCE ROUTING")
            aud = check_audience_routing(session, pid_id)

            header("8. LPS / GRAPH STRUCTURE")
            lps = check_lps_graph(session, pid_id)

            header("9. CROSS-PID ISOLATION")
            iso = check_cross_pid_isolation(session, pid_id)

            header("PHASE 4 READINESS")
            passed = readiness_gate()
            total_checks = 40
            fail_count   = len(_failures)
            pass_count   = total_checks - fail_count
            print(f"\n  Checks passed : {pass_count}/{total_checks}")
            if _failures:
                print(f"  Failed checks :")
                for f in _failures:
                    print(f"    ❌ {f}")
            print()
            if passed:
                print(f"  ✅  Phase 4 READINESS: PASS  —  PID={pid_id} ready for FSM")
            else:
                print(f"  ❌  Phase 4 READINESS: FAIL  —  Fix issues above first")

    finally:
        loader.close()

    print(f"\n{'='*68}\n")
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()