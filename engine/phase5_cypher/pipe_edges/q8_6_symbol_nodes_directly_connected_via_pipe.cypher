// ============================================================================
// Question 8.6 — 8. Edge-Level Flow (PIPE Relationship)
// Engineer question: "Which SYMBOL nodes are directly connected via PIPE to another SYMBOL?"
//
// Operation: list
// Required keywords: symbol
// Intent: drawing_consistency
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (a:Node {structural_type:'SYMBOL', pid_id:$pid_id})-[:PIPE*1..3]-(b:Node {structural_type:'SYMBOL', pid_id:$pid_id}) WHERE a<>b RETURN DISTINCT a.id, a.label, b.id, b.label
LIMIT 50
