// ============================================================================
// Question 12.4 — 12. Flow Evidence Gaps
// Engineer question: "Show low-confidence LPS and their confidence scores."
//
// Operation: list
// Required keywords: low, confidence
// Intent: flow_coverage
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (ann:Annotation {type:'lps_low_confidence_evidence', pid_id:$pid_id})-[:ANNOTATES]->(lps) RETURN lps.id, lps.flow_confidence, lps.seed_confidence
LIMIT 50
