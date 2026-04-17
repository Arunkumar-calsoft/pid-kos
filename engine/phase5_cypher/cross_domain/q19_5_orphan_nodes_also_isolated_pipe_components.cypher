// ============================================================================
// Question 19.5 — 19. Cross-Domain & Combined Questions
// Engineer question: "Which orphan nodes are also in isolated pipe components?"
//
// Operation: list
// Required keywords: orphan, isolated
// Intent: cross_domain
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (ann:Annotation {type:'orphan_node', pid_id:$pid_id})-[:ANNOTATES]->(n:Node {pid_id:$pid_id})<-[:CONTAINS]-(ps:PipeSegment {pid_id:$pid_id}) WHERE ps.component_id > 0 RETURN n.id, n.label, ps.component_id
LIMIT 50
