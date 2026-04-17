// ============================================================================
// Question 20.16 — 20. Engineering Correctness Validation
// Engineer question: "Which vessels have missing_pressure_relief_valve violations?"
//
// Operation: list
// Required keywords: pressure, relief
// Intent: engineering_correctness
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (a:Annotation {pid_id:$pid_id, type:'engineering_rule_violation', pattern_type:'missing_pressure_relief_valve'})-[:ANNOTATES]->(n:Node) RETURN n.id AS vessel_id, n.label AS vessel_type, a.severity AS severity, a.explanation AS explanation ORDER BY n.id LIMIT 50
