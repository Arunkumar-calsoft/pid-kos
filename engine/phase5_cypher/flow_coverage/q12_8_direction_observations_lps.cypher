// ============================================================================
// Question 12.8 — 12. Flow Evidence Gaps
// Engineer question: "Show direction observations for all LPS."
//
// Operation: list
// Required keywords: observation
// Intent: flow_direction
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (ann:Annotation {type:'direction_observation', pid_id:$pid_id})-[:ANNOTATES]->(lps)
OPTIONAL MATCH (ann)-[:SUPPORTED_BY]->(e:Evidence)
RETURN lps.id, lps.flow_direction, ann.source AS observation_source, e.confidence AS confidence
LIMIT 50
