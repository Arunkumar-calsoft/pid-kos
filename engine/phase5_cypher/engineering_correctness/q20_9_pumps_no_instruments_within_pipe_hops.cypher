// ============================================================================
// Question 20.9 — 20. Engineering Correctness Validation
// Engineer question: "Which pumps have no instruments within 5 PIPE hops?"
//
// Operation: list
// Required keywords: instrument
// Intent: engineering_correctness
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (p:Node {pid_id:$pid_id, label:'tank'}) WHERE p.functional_label = 'pump' AND NOT EXISTS { MATCH (p)-[:PIPE*1..5]-(inst:Node {label:'instrumentation'}) } RETURN p.id AS pump_id ORDER BY p.id LIMIT 50
