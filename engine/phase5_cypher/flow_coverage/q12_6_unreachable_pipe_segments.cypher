// ============================================================================
// Question 12.6 — 12. Flow Evidence Gaps
// Engineer question: "Show all unreachable pipe segments."
//
// Operation: list
// Required keywords: unreachable
// Intent: isolation_reachability
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (ann:Annotation {type:'ps_unreachable_from_evidence', pid_id:$pid_id})-[:ANNOTATES]->(ps:PipeSegment {pid_id:$pid_id}) RETURN ps.id, ps.component_id
LIMIT 50
