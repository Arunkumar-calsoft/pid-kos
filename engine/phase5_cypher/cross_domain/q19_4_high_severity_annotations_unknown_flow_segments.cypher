// ============================================================================
// Question 19.4 — 19. Cross-Domain & Combined Questions
// Engineer question: "Show HIGH-severity annotations on UNKNOWN flow segments."
//
// Operation: list
// Required keywords: unknown, flow
// Intent: cross_domain
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (ann:Annotation {hitl_severity:'HIGH', pid_id:$pid_id})-[:ANNOTATES]->(lps:LogicalPipeSegment {flow_state:'UNKNOWN', pid_id:$pid_id}) RETURN ann.type, lps.id
LIMIT 50
