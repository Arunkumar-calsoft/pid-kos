// ============================================================================
// Question 20.19 — 20. Engineering Correctness Validation
// Engineer question: "Show all engineering violations grouped by equipment type."
//
// Operation: count
// Intent: engineering_correctness
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (a:Annotation {pid_id:$pid_id, type:'engineering_rule_violation'})-[:ANNOTATES]->(n:Node) RETURN coalesce(n.functional_label, n.label) AS equipment_role, count(a) AS violation_count ORDER BY violation_count DESC
