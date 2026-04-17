// ============================================================================
// Question 20.23 — 20. Engineering Correctness Validation
// Engineer question: "Show engineering violations still pending HITL review."
//
// Operation: list
// Intent: cross_domain
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (a:Annotation {pid_id:$pid_id, type:'engineering_rule_violation'})-[:ANNOTATES]->(n:Node) WHERE properties(a).hitl_status IS NULL RETURN a.pattern_type AS rule_id, a.severity AS severity, n.id AS equipment_id, coalesce(n.functional_label, n.label) AS equipment_role, a.explanation AS explanation ORDER BY CASE a.severity WHEN 'CRITICAL' THEN 1 WHEN 'HIGH' THEN 2 ELSE 3 END LIMIT 50
