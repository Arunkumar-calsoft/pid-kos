// ============================================================================
// Question 20.17 — 20. Engineering Correctness Validation
// Engineer question: "Which equipment has missing_isolation_valve violations?"
//
// Operation: list
// Required keywords: isolation, missing
// Intent: engineering_correctness
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (a:Annotation {pid_id:$pid_id, type:'engineering_rule_violation', pattern_type:'missing_isolation_valve'})-[:ANNOTATES]->(n:Node) RETURN n.id AS equipment_id, coalesce(n.functional_label, n.label) AS equipment_role, a.severity AS severity, a.explanation AS explanation ORDER BY n.id LIMIT 50
