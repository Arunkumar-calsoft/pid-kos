// ============================================================================
// Question 20.8 — 20. Engineering Correctness Validation
// Engineer question: "Which tanks have no instruments within 5 PIPE hops? (uninstrumented equipment)"
//
// Operation: list
// Intent: engineering_correctness
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (t:Node {pid_id:$pid_id, label:'tank'}) WHERE NOT EXISTS { MATCH (t)-[:PIPE*1..5]-(inst:Node {label:'instrumentation'}) } RETURN t.id AS tank_id, coalesce(t.functional_label, t.label) AS equipment_role ORDER BY t.id LIMIT 50
