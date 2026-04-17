// ============================================================================
// Question 20.25 — 20. Engineering Correctness Validation
// Engineer question: "Show CRITICAL violations on equipment with resolved flow direction (SEEDED or PROPAGATED)."
//
// Operation: list
// Required keywords: flow, resolved
// Intent: cross_domain
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (a:Annotation {pid_id:$pid_id, type:'engineering_rule_violation', severity:'CRITICAL'})-[:ANNOTATES]->(n:Node) WHERE n.flow_state IN ['SEEDED', 'PROPAGATED'] RETURN a.pattern_type AS rule_id, n.id AS equipment_id, n.flow_direction AS direction, n.flow_confidence AS confidence ORDER BY n.flow_confidence DESC, n.id LIMIT 50
