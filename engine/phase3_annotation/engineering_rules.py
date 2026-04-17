# engine/phase3_annotation/engineering_rules.py
#
# Phase 3.5 — Engineering Rule Validation
#
# GAP-2 FIX (upstream rule_id):
#   validate_upstream_requirement previously emitted
#   rule_id=f"missing_{target_eq}_upstream" (e.g. "missing_suction_strainer_upstream")
#   which has no entry in CATEGORY_MAP or AUDIENCE_MAP.  Fixed to
#   rule_id=f"missing_{target_eq}" matching the downstream convention.
#
# GAP-7 FIX (upstream/downstream topologically identical):
#   Both validate_downstream_requirement and validate_upstream_requirement
#   used undirected ADJACENT_VIA_NODES traversal, making them functionally
#   identical — a downstream valve would satisfy an upstream check.
#   Fixed by computing the equipment's discharge axis (H/V) from bbox geometry
#   and filtering candidate targets to only nodes on the correct side of the
#   equipment center.  This is the same axis logic used in equipment_flow.py.
#
# NEW-A FIX (functional_label for pump-labeled tanks):
#   validate_equipment_topology_rules now resolves equipment functional role
#   using n.functional_label (stamped by classify_equipment.py in Phase 1).
#   Small 'tank' nodes with functional_label='pump' are looked up under
#   'pump' in symbol_dictionary.SKID_CONTEXT instead of 'tank', ensuring
#   that condensate pump units (CND-PU-162/163/164) receive check_valve and
#   suction_strainer validation.
#
# NEW-B FIX (inferred_check_valve labels):
#   'inferred_check_valve' nodes (relabeled by classify_equipment.py from 'general')
#   are now treated as 'check_valve' for rule-lookup purposes.
#   This means validate_downstream_requirement(pump → check_valve) can be
#   satisfied by an inferred_check_valve node, not just an explicitly labeled one.

from typing import Any, Dict, List, Optional

from engine.domain_knowledge.symbol_dictionary import get_equipment_rules


# ── Label normalisation ────────────────────────────────────────────────────────
#
# Maps node labels to their canonical engineering role for rule lookup.
# Covers both Phase 1 label-inference outputs and known aliases.

_LABEL_TO_RULE_KEY: dict[str, str | None] = {
    # Inferred labels from classify_equipment.py (NEW-B)
    "inferred_check_valve":       "check_valve",
    "inferred_inline_equipment":  None,            # No rules — skip
    # Common aliases
    "nrv":                        "check_valve",
    "non_return_valve":           "check_valve",
    "non_return":                 "check_valve",
    "check":                      "check_valve",
}

# Equipment labels to skip entirely (no engineering rules apply)
_SKIP_LABELS: frozenset[str] = frozenset({
    "connector", "crossing", "background", "arrow",
    "inlet/outlet", "instrumentation",
    "inferred_inline_equipment",
})


def _resolve_rule_key(label: str, functional_label: Optional[str]) -> Optional[str]:
    """
    Resolve the rule-lookup key for a given Node label.

    Resolution order:
      1. If n.functional_label is set (e.g. 'pump' for small tank), use it.
      2. If label is in _LABEL_TO_RULE_KEY, use the mapped key.
      3. Otherwise use label directly.
      4. Return None to skip labels in _SKIP_LABELS.

    Args:
        label:            Node.label (from Neo4j)
        functional_label: Node.functional_label (may be None)

    Returns:
        rule key string to pass to get_equipment_rules, or None to skip.
    """
    if label in _SKIP_LABELS:
        return None

    # functional_label wins (NEW-A)
    if functional_label and functional_label != label:
        return functional_label

    # label alias map (NEW-B)
    mapped = _LABEL_TO_RULE_KEY.get(label)
    if mapped is None and label in _LABEL_TO_RULE_KEY:
        return None  # explicitly mapped to None → skip
    if mapped is not None:
        return mapped

    return label


def _get_equipment_axis(eq_xmin: float, eq_xmax: float,
                        eq_ymin: float, eq_ymax: float) -> str:
    """
    Return 'H' (horizontal discharge to the right) or 'V' (vertical discharge
    upward) based on equipment bbox aspect ratio.

    Convention mirrors equipment_flow.py._dominant_axis:
      W >= H → horizontal (dominant axis is X)
      H > W  → vertical   (dominant axis is Y, discharge is upward = lower Y)
    """
    w = eq_xmax - eq_xmin
    h = eq_ymax - eq_ymin
    return "H" if w >= h else "V"


def validate_equipment_topology_rules(session, pid_id: str) -> None:
    """
    Phase 3.5 — Engineering rule validation with PID-specific semantic overrides.
    """
    from engine.domain_knowledge.semantic_override_system import get_pid_semantics
    from engine.domain_knowledge.semantic_override_system import get_equipment_rules_for_pid

    semantics           = get_pid_semantics(session, pid_id)
    skid_type           = semantics["skid_type"]
    process_conditions  = semantics["process_conditions"]
    semantic_source     = semantics["skid_type_source"]

    if not skid_type:
        print(f"[PHASE3.5][RULES] No skid_type found for PID={pid_id}, skipping rules")
        return

    print(f"[PHASE3.5][RULES] Validating PID={pid_id} with context:")
    print(f"  skid_type: {skid_type} (source: {semantic_source})")
    print(f"  process_conditions: {process_conditions}")
    if semantics.get("custom_rules"):
        print(f"  custom_rules: {list(semantics['custom_rules'].keys())}")

    # Fetch all equipment labels + functional labels in this PID
    equipment_rows = session.run("""
        MATCH (eq:Node {pid_id: $pid_id})
        WHERE eq.label IS NOT NULL
          AND eq.coord_system = 'float'
        RETURN DISTINCT eq.label             AS equipment_label,
                        eq.functional_label  AS functional_label
    """, pid_id=pid_id).data()

    total_violations = 0

    for eq_row in equipment_rows:
        equipment_label  = eq_row["equipment_label"]
        functional_label = eq_row.get("functional_label")

        rule_key = _resolve_rule_key(equipment_label, functional_label)
        if rule_key is None:
            continue

        # Get rules using functional role, not raw label
        # Pass cached semantics to avoid repeated DB queries per equipment type
        try:
            rules = get_equipment_rules_for_pid(
                session=session,
                pid_id=pid_id,
                equipment_label=rule_key,
                semantics=semantics,
            )
        except Exception as exc:
            print(f"[PHASE3.5][RULES] get_equipment_rules_for_pid failed for '{rule_key}': {exc}. Using base rules.")
            rules = get_equipment_rules(
                equipment_label=rule_key,
                skid_type=skid_type,
                process_conditions=process_conditions,
            )

        if not rules:
            continue

        if rules.get("skip_validation"):
            print(f"[PHASE3.5][RULES] Skipping {equipment_label} (skip_validation=true)")
            continue

        for req in rules.get("required_downstream", []):
            violations = validate_downstream_requirement(
                session, pid_id, equipment_label, rule_key, req,
                skid_type, semantic_source,
            )
            total_violations += violations

        for req in rules.get("required_upstream", []):
            violations = validate_upstream_requirement(
                session, pid_id, equipment_label, rule_key, req,
                skid_type, semantic_source,
            )
            total_violations += violations

        for req in rules.get("required_connections", []):
            if "spatial_constraint" in req:
                violations = validate_spatial_constraint(
                    session, pid_id, equipment_label, rule_key, req,
                    skid_type, semantic_source,
                )
                total_violations += violations

    print(
        f"[PHASE3.5][RULES] Engineering rule validation complete for PID={pid_id}. "
        f"Total violations: {total_violations}"
    )


# ── GAP-7 FIX: Spatial positional filter ──────────────────────────────────────

def _spatial_direction_cypher(side: str) -> str:
    """
    Return a Cypher WHERE fragment that filters targets to one spatial side
    of the equipment node, using bbox center coordinates.

    side: 'downstream' → right (H) or upward (V) of equipment
          'upstream'   → left (H)  or downward (V) of equipment

    The fragment references Cypher variables: eq (equipment node), target (target node).
    It falls through (always true) when axis cannot be determined.
    """
    return """
        CASE
          WHEN (eq.xmax - eq.xmin) >= (eq.ymax - eq.ymin) THEN
            CASE $side
              WHEN 'downstream' THEN
                ((target.xmin + target.xmax) / 2.0) >
                ((eq.xmin + eq.xmax) / 2.0 + $min_spatial_offset)
              WHEN 'upstream' THEN
                ((target.xmin + target.xmax) / 2.0) <
                ((eq.xmin + eq.xmax) / 2.0 - $min_spatial_offset)
              ELSE true
            END
          ELSE
            CASE $side
              WHEN 'downstream' THEN
                ((target.ymin + target.ymax) / 2.0) <
                ((eq.ymin + eq.ymax) / 2.0 - $min_spatial_offset)
              WHEN 'upstream' THEN
                ((target.ymin + target.ymax) / 2.0) >
                ((eq.ymin + eq.ymax) / 2.0 + $min_spatial_offset)
              ELSE true
            END
        END
    """


# Minimum pixel offset from equipment center for a target to count as
# directionally distinct. Prevents the equipment itself from satisfying its own rule.
_MIN_SPATIAL_OFFSET = 10.0


def validate_downstream_requirement(
    session,
    pid_id: str,
    equipment_label: str,
    rule_key: str,
    req: Dict[str, Any],
    skid_type: str,
    semantic_source: str,
) -> int:
    """
    Validate that all equipment of a given functional role have the required
    downstream equipment within max_hops AND spatially on the discharge side.

    GAP-7 FIX: Added spatial position filter using bbox center coordinates.
    Downstream = right (H axis) or upward (V axis) of equipment center.
    This prevents a valve to the LEFT of a pump (upstream) from satisfying
    a 'check_valve downstream' requirement.
    """
    target_eq = req["equipment"]
    max_hops  = req["max_hops"]
    severity  = req["severity"]
    reason    = req["reason"]

    # Target label includes both explicit and inferred variants
    target_labels = _get_target_labels(target_eq)

    violations = session.run(
        f"""
        MATCH (eq:Node {{pid_id: $pid_id}})
        WHERE (eq.label = $eq_label OR eq.functional_label = $rule_key)

        OPTIONAL MATCH path =
            (eq)-[:ENDPOINT_OF]->(lps:LogicalPipeSegment {{pid_id: $pid_id}})
            -[:ADJACENT_VIA_NODES*0..{max_hops}]-(lps2:LogicalPipeSegment {{pid_id: $pid_id}})
            <-[:ENDPOINT_OF]-(target:Node {{pid_id: $pid_id}})
        WHERE target.label IN $target_labels
          AND ({_spatial_direction_cypher('downstream')})

        WITH eq, count(DISTINCT target) AS found_count
        WHERE found_count = 0

        RETURN eq.id AS violator_id, eq.label AS eq_label
        """,
        pid_id=pid_id,
        eq_label=equipment_label,
        rule_key=rule_key,
        target_labels=target_labels,
        side="downstream",
        min_spatial_offset=_MIN_SPATIAL_OFFSET,
    ).data()

    for v in violations:
        _create_rule_violation(
            session, pid_id,
            rule_id=f"missing_{target_eq}",
            violator_id=v["violator_id"],
            severity=severity,
            explanation=(
                f"{equipment_label} (role={rule_key}) requires {target_eq} downstream "
                f"for {reason} (skid_type={skid_type}, source={semantic_source})"
            ),
            category="TOPOLOGY",
            skid_type=skid_type,
            semantic_source=semantic_source,
            max_hops_checked=max_hops,
            required_equipment=target_eq,
        )

    if violations:
        print(
            f"[PHASE3.5][RULES]   {equipment_label} → {target_eq}: "
            f"{len(violations)} violations (max_hops={max_hops})"
        )

    return len(violations)


def validate_upstream_requirement(
    session,
    pid_id: str,
    equipment_label: str,
    rule_key: str,
    req: Dict[str, Any],
    skid_type: str,
    semantic_source: str,
) -> int:
    """
    Validate that all equipment of a given functional role have the required
    upstream equipment within max_hops AND spatially on the suction side.

    GAP-2 FIX: rule_id changed from f"missing_{target_eq}_upstream" to
    f"missing_{target_eq}" to match the CATEGORY_MAP key convention.

    GAP-7 FIX: Added spatial position filter.
    Upstream = left (H axis) or downward (V axis) of equipment center.
    """
    target_eq = req["equipment"]
    max_hops  = req["max_hops"]
    severity  = req["severity"]
    reason    = req["reason"]

    target_labels = _get_target_labels(target_eq)

    violations = session.run(
        f"""
        MATCH (eq:Node {{pid_id: $pid_id}})
        WHERE (eq.label = $eq_label OR eq.functional_label = $rule_key)

        OPTIONAL MATCH path =
            (eq)-[:ENDPOINT_OF]->(lps:LogicalPipeSegment {{pid_id: $pid_id}})
            -[:ADJACENT_VIA_NODES*0..{max_hops}]-(lps2:LogicalPipeSegment {{pid_id: $pid_id}})
            <-[:ENDPOINT_OF]-(target:Node {{pid_id: $pid_id}})
        WHERE target.label IN $target_labels
          AND ({_spatial_direction_cypher('upstream')})

        WITH eq, count(DISTINCT target) AS found_count
        WHERE found_count = 0

        RETURN eq.id AS violator_id, eq.label AS eq_label
        """,
        pid_id=pid_id,
        eq_label=equipment_label,
        rule_key=rule_key,
        target_labels=target_labels,
        side="upstream",
        min_spatial_offset=_MIN_SPATIAL_OFFSET,
    ).data()

    for v in violations:
        _create_rule_violation(
            session, pid_id,
            # GAP-2 FIX: was f"missing_{target_eq}_upstream" — mismatch with CATEGORY_MAP
            rule_id=f"missing_{target_eq}",
            violator_id=v["violator_id"],
            severity=severity,
            explanation=(
                f"{equipment_label} (role={rule_key}) requires {target_eq} upstream "
                f"for {reason} (skid_type={skid_type}, source={semantic_source})"
            ),
            category="TOPOLOGY",
            skid_type=skid_type,
            semantic_source=semantic_source,
            max_hops_checked=max_hops,
            required_equipment=target_eq,
        )

    if violations:
        print(
            f"[PHASE3.5][RULES]   {equipment_label} ← {target_eq}: "
            f"{len(violations)} violations (max_hops={max_hops})"
        )

    return len(violations)


def _get_target_labels(target_eq: str) -> List[str]:
    """
    Expand a target equipment name to all node labels that can satisfy it.
    Includes inferred labels (NEW-B) alongside explicit ones.
    """
    base = [target_eq]
    # If we're looking for check_valve, also accept inferred_check_valve nodes
    if target_eq == "check_valve":
        base.extend(["inferred_check_valve", "nrv", "non_return_valve", "non_return", "check"])
    elif target_eq in ("strainer", "suction_strainer", "filter"):
        base.extend(["inferred_check_valve"])  # small general nodes may be strainers too
    return base


def validate_spatial_constraint(
    session,
    pid_id: str,
    equipment_label: str,
    rule_key: str,
    req: Dict[str, Any],
    skid_type: str,
    semantic_source: str,
) -> int:
    """
    Validate spatial positioning of connected equipment.
    Unchanged from original except rule_key passed through for future use.
    """
    conn_type = req["connection_type"]
    spatial   = req["spatial_constraint"]
    severity  = req["severity"]
    reason    = req["reason"]

    if spatial == "highest_point":
        max_distance = req.get("max_distance_from_top", 50)

        violations = session.run("""
            MATCH (tank:Node {pid_id: $pid_id})
            WHERE tank.label = $eq_label

            MATCH (tank)-[:ENDPOINT_OF]->(lps:LogicalPipeSegment {pid_id: $pid_id})
                 <-[:ENDPOINT_OF]-(vent:Node {pid_id: $pid_id})
            WHERE vent.id <> tank.id
              AND (vent.label CONTAINS $conn_type
                   OR vent.label CONTAINS 'vent'
                   OR vent.label CONTAINS 'relief')

            WITH tank, vent,
                 (vent.ymin - tank.ymin)                   AS y_delta,
                 abs(((vent.xmin + vent.xmax)/2.0) -
                     ((tank.xmin + tank.xmax)/2.0))        AS x_delta

            WHERE y_delta > $max_distance OR x_delta > 100

            RETURN tank.id AS violator_id,
                   vent.id AS vent_id,
                   y_delta, x_delta
        """, pid_id=pid_id, eq_label=equipment_label,
             conn_type=conn_type, max_distance=max_distance).data()

        for v in violations:
            _create_rule_violation(
                session, pid_id,
                rule_id=f"{equipment_label}_vent_position_violation",
                violator_id=v["violator_id"],
                severity=severity,
                explanation=(
                    f"{equipment_label} {conn_type} not at highest point "
                    f"(y_delta={v['y_delta']:.1f}, reason={reason}, "
                    f"skid_type={skid_type}, source={semantic_source})"
                ),
                category="SPATIAL",
                skid_type=skid_type,
                semantic_source=semantic_source,
                related_node=v["vent_id"],
                y_delta=v["y_delta"],
                x_delta=v["x_delta"],
            )

        if violations:
            print(
                f"[PHASE3.5][RULES]   {equipment_label} spatial: {conn_type} position: "
                f"{len(violations)} violations"
            )

        return len(violations)

    elif spatial == "lowest_point":
        max_distance = req.get("max_distance_from_bottom", 50)

        violations = session.run("""
            MATCH (tank:Node {pid_id: $pid_id})
            WHERE tank.label = $eq_label

            MATCH (tank)-[:ENDPOINT_OF]->(lps:LogicalPipeSegment {pid_id: $pid_id})
                 <-[:ENDPOINT_OF]-(drain:Node {pid_id: $pid_id})
            WHERE drain.id <> tank.id
              AND drain.label CONTAINS $conn_type

            WITH tank, drain,
                 (drain.ymax - tank.ymax)                   AS y_delta,
                 abs(((drain.xmin + drain.xmax)/2.0) -
                     ((tank.xmin + tank.xmax)/2.0))         AS x_delta

            WHERE y_delta < -$max_distance OR x_delta > 100

            RETURN tank.id AS violator_id,
                   drain.id AS drain_id,
                   y_delta, x_delta
        """, pid_id=pid_id, eq_label=equipment_label,
             conn_type=conn_type, max_distance=max_distance).data()

        for v in violations:
            _create_rule_violation(
                session, pid_id,
                rule_id=f"{equipment_label}_drain_position_violation",
                violator_id=v["violator_id"],
                severity=severity,
                explanation=(
                    f"{equipment_label} {conn_type} not at lowest point "
                    f"(y_delta={v['y_delta']:.1f}, reason={reason}, "
                    f"skid_type={skid_type}, source={semantic_source})"
                ),
                category="SPATIAL",
                skid_type=skid_type,
                semantic_source=semantic_source,
                related_node=v["drain_id"],
                y_delta=v["y_delta"],
                x_delta=v["x_delta"],
            )

        if violations:
            print(
                f"[PHASE3.5][RULES]   {equipment_label} spatial: {conn_type} position: "
                f"{len(violations)} violations"
            )

        return len(violations)

    return 0


def _create_rule_violation(
    session,
    pid_id: str,
    rule_id: str,
    violator_id: str,
    severity: str,
    explanation: str,
    category: str,
    **extra_props,
) -> None:
    """Create engineering rule violation annotation node."""
    ann_id = f"rule_{pid_id}_{rule_id}_{violator_id}"

    props = {
        "pid_id":       pid_id,
        "type":         "engineering_rule_violation",
        "source":       "phase3_engineering_rules",
        "pattern_type": rule_id,
        "category":     category,
        "severity":     severity,
        "explanation":  explanation,
        "target_id":    violator_id,
    }
    props.update(extra_props)

    set_clauses = ", ".join(f"a.{k} = ${k}" for k in props)

    query = f"""
        MATCH (target {{id: $violator_id, pid_id: $pid_id}})
        MERGE (a:Annotation {{id: $ann_id}})
        ON CREATE SET a.first_seen = datetime()
        ON MATCH  SET a.last_seen  = datetime()
        SET {set_clauses}
        MERGE (a)-[:ANNOTATES]->(target)
    """

    params = {"ann_id": ann_id, "violator_id": violator_id}
    params.update(props)
    session.run(query, params)