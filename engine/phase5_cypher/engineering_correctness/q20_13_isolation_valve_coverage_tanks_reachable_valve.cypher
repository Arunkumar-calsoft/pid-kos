// ============================================================================
// Question 20.13 — 20. Engineering Correctness Validation
// Engineer question: "Show isolation valve coverage for all tanks (reachable valve count per tank)."
//
// Operation: list
// Intent: isolation_reachability
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (t:Node {pid_id:$pid_id, label:'tank'}) OPTIONAL MATCH (t)-[:PIPE*1..8]-(v:Node {label:'valve'}) WITH t, count(DISTINCT v) AS reachable_valves RETURN t.id AS tank_id, coalesce(t.functional_label, t.label) AS equipment_role, reachable_valves ORDER BY reachable_valves ASC, t.id LIMIT 50
