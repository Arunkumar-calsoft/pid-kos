// ============================================================================
// Question 20.5 — 20. Engineering Correctness Validation
// Engineer question: "Show all CRITICAL-severity engineering violations."
//
// Operation: list
// Required keywords: critical
// Intent: engineering_correctness
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (a:Annotation {pid_id:$pid_id, type:'engineering_rule_violation', severity:'CRITICAL'})-[:ANNOTATES]->(n:Node) RETURN a.pattern_type AS rule_id, n.id AS equipment_id, coalesce(n.functional_label, n.label) AS equipment_role, a.explanation AS explanation ORDER BY a.pattern_type, n.id LIMIT 50
