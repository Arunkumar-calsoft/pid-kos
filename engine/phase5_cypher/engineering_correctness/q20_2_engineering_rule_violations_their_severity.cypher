// ============================================================================
// Question 20.2 — 20. Engineering Correctness Validation
// Engineer question: "Show all engineering rule violations with their severity."
//
// Operation: list
// Intent: cross_domain
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (a:Annotation {pid_id:$pid_id, type:'engineering_rule_violation'})-[:ANNOTATES]->(n:Node) RETURN a.pattern_type AS rule_id, a.severity AS severity, n.id AS equipment_id, n.label AS equipment_type, coalesce(n.functional_label, n.label) AS equipment_role, a.explanation AS explanation ORDER BY CASE a.severity WHEN 'CRITICAL' THEN 1 WHEN 'HIGH' THEN 2 ELSE 3 END, a.pattern_type LIMIT 50
