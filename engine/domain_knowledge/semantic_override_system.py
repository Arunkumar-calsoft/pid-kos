# engine/domain_knowledge/semantic_override_system.py
#
# PID-LEVEL SEMANTIC OVERRIDE SYSTEM
#
# GAP-3 FIX (_get_frequency_aggregation_function):
#   The probe list did not include 'compute_structural_frequencies', which is
#   the actual function name in frequency_aggregation.py.  Calling
#   revalidate_pid_semantics() would raise ImportError at runtime.
#   'compute_structural_frequencies' is now the first (highest-priority) probe.

from typing import Any, Dict, List, Optional, Tuple
import json
import sys
from pathlib import Path


def _get_frequency_aggregation_function():
    """
    Dynamically discover the correct function in frequency_aggregation.py.

    GAP-3 FIX: 'compute_structural_frequencies' added as first probe.
    """
    try:
        from engine.phase3_annotation import frequency_aggregation

        # Probe in priority order — first match wins
        for func_name in [
            'compute_structural_frequencies',   # GAP-3 FIX: actual function name
            'aggregate_frequencies',
            'compute_frequency_distribution',
            'calculate_frequencies',
            'aggregate_pattern_frequencies',
            'update_frequencies',
        ]:
            if hasattr(frequency_aggregation, func_name):
                return getattr(frequency_aggregation, func_name)

        available = [
            name for name in dir(frequency_aggregation)
            if not name.startswith('_') and callable(getattr(frequency_aggregation, name))
        ]
        raise ImportError(
            f"Could not find frequency aggregation function. "
            f"Available: {available}"
        )
    except ImportError as e:
        print(f"[ERROR] Failed to import frequency_aggregation module: {e}")
        raise


def _get_rarity_scoring_function():
    """Dynamically discover the correct function in rarity_scoring.py."""
    try:
        from engine.phase3_annotation import rarity_scoring

        for func_name in [
            'compute_structural_rarity',
            'calculate_rarity_scores',
            'score_pattern_rarity',
            'update_rarity',
        ]:
            if hasattr(rarity_scoring, func_name):
                return getattr(rarity_scoring, func_name)

        available = [
            name for name in dir(rarity_scoring)
            if not name.startswith('_') and callable(getattr(rarity_scoring, name))
        ]
        raise ImportError(
            f"Could not find rarity scoring function. Available: {available}"
        )
    except ImportError as e:
        print(f"[ERROR] Failed to import rarity_scoring module: {e}")
        raise


def get_pid_semantics(session, pid_id: str) -> Dict[str, Any]:
    """
    Get effective semantics for a PID with 4-level override resolution.

    Resolution order (highest priority first):
      4. PID.skid_type_override (user override)
      3. PID.process_conditions
      2. Skid.skid_type (default from registration)
      1. Universal base
    """
    try:
        row = session.run("""
            MATCH (pid:PID {pid_id: $pid_id})
            OPTIONAL MATCH (pid)<-[:HAS_PID]-(skid:Skid)
            RETURN
                properties(pid)  AS pid_props,
                skid.skid_type   AS skid_type_default
        """, pid_id=pid_id).single()
    except Exception as e:
        raise RuntimeError(f"Neo4j query failed for PID '{pid_id}': {e}")

    if not row:
        raise ValueError(f"PID '{pid_id}' not found in Neo4j")

    pid_props          = dict(row["pid_props"])
    skid_type_override = pid_props.get("skid_type_override")
    skid_type_default  = row.get("skid_type_default")

    if skid_type_override:
        skid_type        = skid_type_override
        skid_type_source = "override"
    elif skid_type_default:
        skid_type        = skid_type_default
        skid_type_source = "default"
    else:
        skid_type        = None
        skid_type_source = "none"

    process_conditions = pid_props.get("process_conditions") or []
    if isinstance(process_conditions, str):
        try:
            process_conditions = json.loads(process_conditions)
        except json.JSONDecodeError:
            process_conditions = []

    custom_rules = pid_props.get("custom_rules") or {}
    if isinstance(custom_rules, str):
        try:
            custom_rules = json.loads(custom_rules)
        except json.JSONDecodeError:
            custom_rules = {}

    return {
        "pid_id":                  pid_props.get("pid_id"),
        "skid_type":               skid_type,
        "skid_type_source":        skid_type_source,
        "skid_type_default":       skid_type_default,
        "skid_type_override":      skid_type_override,
        "process_conditions":      process_conditions,
        "custom_rules":            custom_rules,
        "semantics_last_modified": pid_props.get("semantics_last_modified"),
        "semantics_modified_by":   pid_props.get("semantics_modified_by"),
        "validation_count":        pid_props.get("semantics_validation_count") or 0,
    }


def set_pid_semantics(
    session,
    pid_id: str,
    skid_type_override: Optional[str] = None,
    process_conditions: Optional[List[str]] = None,
    custom_rules: Optional[Dict[str, Any]] = None,
    modified_by: str = "system",
    clear_existing: bool = False,
) -> Dict[str, Any]:
    """Set PID-specific semantic overrides."""
    params = {"pid_id": pid_id, "modified_by": modified_by}

    if clear_existing:
        try:
            session.run("""
                MATCH (pid:PID {pid_id: $pid_id})
                REMOVE pid.skid_type_override,
                       pid.process_conditions,
                       pid.custom_rules
                SET pid.semantics_last_modified = datetime(),
                    pid.semantics_modified_by   = $modified_by
            """, params)
            print(f"[SEMANTICS] Cleared all overrides for PID={pid_id}")
        except Exception as e:
            raise RuntimeError(f"Failed to clear semantics for PID '{pid_id}': {e}")

    set_clauses = []

    if skid_type_override is not None:
        set_clauses.append("pid.skid_type_override = $skid_type_override")
        params["skid_type_override"] = skid_type_override

    if process_conditions is not None:
        set_clauses.append("pid.process_conditions = $process_conditions")
        params["process_conditions"] = json.dumps(process_conditions)

    if custom_rules is not None:
        set_clauses.append("pid.custom_rules = $custom_rules")
        params["custom_rules"] = json.dumps(custom_rules)

    if set_clauses:
        set_clauses.extend([
            "pid.semantics_last_modified = datetime()",
            "pid.semantics_modified_by = $modified_by",
        ])
        query = f"""
            MATCH (pid:PID {{pid_id: $pid_id}})
            SET {', '.join(set_clauses)}
            RETURN pid
        """
        try:
            result = session.run(query, params).single()
            if not result:
                raise ValueError(f"PID '{pid_id}' not found")
        except Exception as e:
            raise RuntimeError(f"Failed to update semantics for PID '{pid_id}': {e}")

        print(f"[SEMANTICS] Updated semantics for PID={pid_id}")
        if skid_type_override:
            print(f"  skid_type_override: {skid_type_override}")

    return get_pid_semantics(session, pid_id)


def clear_pid_semantics(session, pid_id: str, modified_by: str = "system") -> Dict[str, Any]:
    """Clear all PID-specific semantic overrides (revert to Skid defaults)."""
    return set_pid_semantics(session, pid_id, clear_existing=True, modified_by=modified_by)


def get_equipment_rules_for_pid(
    session,
    pid_id: str,
    equipment_label: str,
    semantics: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Get equipment rules with full 4-level hierarchy resolution.

    Pass ``semantics`` (from a prior call to ``get_pid_semantics``) to avoid
    a redundant DB round-trip when the caller already has the PID context.
    """
    try:
        from engine.domain_knowledge.symbol_dictionary import get_equipment_rules, _merge_rules
    except ImportError as e:
        raise ImportError(f"Failed to import symbol_dictionary: {e}")

    if semantics is None:
        semantics = get_pid_semantics(session, pid_id)

    rules = get_equipment_rules(
        equipment_label=equipment_label,
        skid_type=semantics["skid_type"],
        process_conditions=semantics["process_conditions"],
    )

    custom_rules = semantics.get("custom_rules", {})
    if equipment_label in custom_rules:
        equipment_custom = custom_rules[equipment_label]
        if equipment_custom.get("skip_validation"):
            return {"skip_validation": True}
        rules = _merge_rules(rules, equipment_custom)

    return rules


def revalidate_pid_semantics(session, pid_id: str) -> Dict[str, Any]:
    """
    Re-run Phase 3.5 engineering rule validation with current semantics.
    Fast re-validation (~3 seconds vs full pipeline ~180 seconds).
    """
    try:
        from engine.phase3_annotation.engineering_rules import validate_equipment_topology_rules
    except ImportError:
        raise ImportError(
            "Cannot import validate_equipment_topology_rules. "
            "Ensure engine/phase3_annotation/engineering_rules.py exists."
        )

    frequency_aggregation_func = _get_frequency_aggregation_function()
    rarity_scoring_func        = _get_rarity_scoring_function()

    print(f"[REVALIDATE] Starting semantic re-validation for PID={pid_id}")

    semantics = get_pid_semantics(session, pid_id)
    print(f"[REVALIDATE] Using semantics:")
    print(f"  skid_type: {semantics['skid_type']} (source: {semantics['skid_type_source']})")
    print(f"  process_conditions: {semantics['process_conditions']}")

    try:
        before_count = session.run("""
            MATCH (a:Annotation {pid_id: $pid_id, type: 'engineering_rule_violation'})
            RETURN count(a) AS count
        """, pid_id=pid_id).single()["count"]

        before_patterns = set(
            r["pattern_type"] for r in session.run("""
                MATCH (a:Annotation {pid_id: $pid_id, type: 'engineering_rule_violation'})
                WHERE a.pattern_type IS NOT NULL
                RETURN DISTINCT a.pattern_type AS pattern_type
            """, pid_id=pid_id).data()
        )
    except Exception as e:
        raise RuntimeError(f"Failed to query existing violations: {e}")

    try:
        session.run("""
            MATCH (a:Annotation {pid_id: $pid_id, type: 'engineering_rule_violation'})
            DETACH DELETE a
        """, pid_id=pid_id)
        print(f"[REVALIDATE] Cleared {before_count} old violations")
    except Exception as e:
        raise RuntimeError(f"Failed to clear old violations: {e}")

    try:
        print(f"[REVALIDATE] Running engineering rules validation...")
        validate_equipment_topology_rules(session, pid_id)

        print(f"[REVALIDATE] Running frequency aggregation...")
        frequency_aggregation_func(session, pid_id)

        print(f"[REVALIDATE] Running rarity scoring...")
        rarity_scoring_func(session, pid_id)
    except Exception as e:
        raise RuntimeError(f"Phase 3.5 re-validation failed: {e}")

    try:
        after_count = session.run("""
            MATCH (a:Annotation {pid_id: $pid_id, type: 'engineering_rule_violation'})
            RETURN count(a) AS count
        """, pid_id=pid_id).single()["count"]

        after_patterns = set(
            r["pattern_type"] for r in session.run("""
                MATCH (a:Annotation {pid_id: $pid_id, type: 'engineering_rule_violation'})
                WHERE a.pattern_type IS NOT NULL
                RETURN DISTINCT a.pattern_type AS pattern_type
            """, pid_id=pid_id).data()
        )
    except Exception as e:
        raise RuntimeError(f"Failed to query new violations: {e}")

    violations_cleared = before_patterns - after_patterns
    violations_added   = after_patterns  - before_patterns

    try:
        session.run("""
            MATCH (pid:PID {pid_id: $pid_id})
            SET pid.semantics_validation_count =
                    coalesce(pid.semantics_validation_count, 0) + 1,
                pid.semantics_last_validated = datetime()
        """, pid_id=pid_id)
    except Exception as e:
        print(f"[WARN] Failed to update validation count: {e}")

    result = {
        "violations_before":  before_count,
        "violations_after":   after_count,
        "violations_cleared": sorted(violations_cleared),
        "violations_added":   sorted(violations_added),
        "semantic_context":   semantics,
    }

    print(f"[REVALIDATE] Re-validation complete:")
    print(f"  Violations: {before_count} → {after_count}")
    if violations_cleared:
        print(f"  Cleared: {result['violations_cleared']}")
    if violations_added:
        print(f"  Added: {result['violations_added']}")

    return result