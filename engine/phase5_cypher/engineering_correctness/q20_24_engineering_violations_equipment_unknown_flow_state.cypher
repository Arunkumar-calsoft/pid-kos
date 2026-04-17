// ============================================================================
// Question 20.24 — 20. Engineering Correctness Validation
// Engineer question: "Which engineering violations are on equipment with UNKNOWN flow state?"
//
// Operation: list
// Intent: engineering_correctness
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (a:Annotation {pid_id:$pid_id, type:'engineering_rule_violation'})-[:ANNOTATES]->(n:Node) WHERE n.flow_state = 'UNKNOWN' OR n.flow_state IS NULL RETURN a.pattern_type AS rule_id, a.severity AS severity, n.id AS equipment_id, n.flow_state AS flow_state ORDER BY a.severity, n.id LIMIT 50
