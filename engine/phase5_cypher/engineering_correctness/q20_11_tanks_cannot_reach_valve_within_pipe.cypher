// ============================================================================
// Question 20.11 — 20. Engineering Correctness Validation
// Engineer question: "Which tanks cannot reach any valve within 8 PIPE hops? (unisolatable equipment)"
//
// Operation: list
// Required keywords: tank, reach
// Intent: isolation_reachability
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (t:Node {pid_id:$pid_id, label:'tank'}) WHERE NOT EXISTS { MATCH (t)-[:PIPE*1..8]-(v:Node {label:'valve'}) } RETURN t.id AS tank_id, coalesce(t.functional_label, t.label) AS equipment_role ORDER BY t.id LIMIT 50
