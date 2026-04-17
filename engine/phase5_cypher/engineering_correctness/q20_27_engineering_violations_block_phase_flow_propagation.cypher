// ============================================================================
// Question 20.27 — 20. Engineering Correctness Validation
// Engineer question: "Which engineering violations block Phase 4 flow propagation? (propagation_blocked=true)"
//
// Operation: list
// Intent: flow_coverage
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (a:Annotation {pid_id:$pid_id, type:'engineering_rule_violation'})-[:ANNOTATES]->(n:Node) WHERE a.propagation_blocked = true RETURN a.pattern_type AS rule_id, a.severity AS severity, n.id AS equipment_id, a.explanation AS explanation ORDER BY a.severity, n.id LIMIT 50
