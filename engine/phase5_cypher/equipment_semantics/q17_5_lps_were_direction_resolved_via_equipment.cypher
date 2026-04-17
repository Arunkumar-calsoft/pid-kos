// ============================================================================
// Question 17.5 — 17. Equipment Semantics
// Engineer question: "How many LPS were direction-resolved via equipment semantics?"
//
// Operation: count
// Intent: cross_domain
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (e:Evidence {source:'phase3_equipment_semantics', pid_id:$pid_id})-[:ABOUT]->(lps:LogicalPipeSegment {pid_id:$pid_id}) RETURN count(DISTINCT lps) AS total
