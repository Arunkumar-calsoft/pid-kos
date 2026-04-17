// ============================================================================
// Question 20.10 — 20. Engineering Correctness Validation
// Engineer question: "Are all tanks instrumented? (summary count)"
//
// Operation: count
// Intent: engineering_correctness
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (t:Node {pid_id:$pid_id, label:'tank'}) WITH t, EXISTS { MATCH (t)-[:PIPE*1..5]-(inst:Node {label:'instrumentation'}) } AS has_instrument RETURN has_instrument, count(t) AS tank_count ORDER BY has_instrument
