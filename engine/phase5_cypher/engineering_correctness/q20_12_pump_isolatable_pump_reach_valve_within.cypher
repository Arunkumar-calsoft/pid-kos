// ============================================================================
// Question 20.12 — 20. Engineering Correctness Validation
// Engineer question: "Is every pump isolatable? (can each pump reach a valve within 8 hops?)"
//
// Operation: list
// Intent: engineering_correctness
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (p:Node {pid_id:$pid_id, label:'tank'}) WHERE p.functional_label = 'pump' AND NOT EXISTS { MATCH (p)-[:PIPE*1..8]-(v:Node {label:'valve'}) } RETURN p.id AS pump_without_isolation, coalesce(p.functional_label, p.label) AS equipment_role ORDER BY p.id LIMIT 50
