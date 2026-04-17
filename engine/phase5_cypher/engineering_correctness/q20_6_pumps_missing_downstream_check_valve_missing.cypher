// ============================================================================
// Question 20.6 — 20. Engineering Correctness Validation
// Engineer question: "Which pumps are missing a downstream check valve? (missing_check_valve violations)"
//
// Operation: list
// Required keywords: pump, check
// Intent: engineering_correctness
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (a:Annotation {pid_id:$pid_id, type:'engineering_rule_violation', pattern_type:'missing_check_valve'})-[:ANNOTATES]->(n:Node) RETURN n.id AS pump_id, coalesce(n.functional_label, n.label) AS equipment_role, a.severity AS severity, a.explanation AS explanation ORDER BY n.id LIMIT 50
