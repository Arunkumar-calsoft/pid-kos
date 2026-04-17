// ============================================================================
// Question 2.3 — 2. Valve Placement & Connectivity
// Engineer question: "Which valve has the most pipe connections?"
//
// Operation: list
// Required keywords: most
// Intent: valve_placement
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (v:Node {label:'valve', pid_id:$pid_id}) WITH v, size([(v)-[:PIPE]-() |1]) AS deg RETURN v.id, deg ORDER BY deg DESC LIMIT 5
