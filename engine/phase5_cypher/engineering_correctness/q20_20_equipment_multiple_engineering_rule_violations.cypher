// ============================================================================
// Question 20.20 — 20. Engineering Correctness Validation
// Engineer question: "Which equipment has multiple engineering rule violations?"
//
// Operation: list
// Intent: engineering_correctness
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (a:Annotation {pid_id:$pid_id, type:'engineering_rule_violation'})-[:ANNOTATES]->(n:Node) WITH n, count(a) AS violation_count, collect(a.pattern_type) AS rules WHERE violation_count > 1 RETURN n.id AS equipment_id, coalesce(n.functional_label, n.label) AS equipment_role, violation_count, rules ORDER BY violation_count DESC, n.id LIMIT 50
