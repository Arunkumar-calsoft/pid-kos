// ============================================================================
// Question 20.18 — 20. Engineering Correctness Validation
// Engineer question: "Which pumps are missing a suction strainer? (missing_suction_strainer violations)"
//
// Operation: list
// Required keywords: pump, suction, strainer
// Intent: drawing_consistency
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (a:Annotation {pid_id:$pid_id, type:'engineering_rule_violation', pattern_type:'missing_suction_strainer'})-[:ANNOTATES]->(n:Node) RETURN n.id AS pump_id, coalesce(n.functional_label, n.label) AS equipment_role, a.severity AS severity, a.explanation AS explanation ORDER BY n.id LIMIT 50
