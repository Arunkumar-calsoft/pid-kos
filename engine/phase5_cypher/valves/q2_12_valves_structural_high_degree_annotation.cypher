// ============================================================================
// Question 2.12 — 2. Valve Placement & Connectivity
// Engineer question: "Which valves have a structural_high_degree annotation?"
//
// Operation: list
// Required keywords: degree
// Intent: drawing_consistency
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (ann:Annotation {type:'structural_high_degree', pid_id:$pid_id})-[:ANNOTATES]->(n:Node {label:'valve', pid_id:$pid_id}) RETURN n.id, ann.degree
LIMIT 50
