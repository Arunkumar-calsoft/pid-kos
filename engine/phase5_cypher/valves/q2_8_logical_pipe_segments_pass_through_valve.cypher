// ============================================================================
// Question 2.8 — 2. Valve Placement & Connectivity
// Engineer question: "How many logical pipe segments pass through each valve?"
//
// Operation: count
// Required keywords: pass, through
// Intent: cross_domain
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (v:Node {label:'valve', pid_id:$pid_id})<-[:CONTAINS]-(ps:PipeSegment {pid_id:$pid_id})<-[:COVERS]-(lps) WITH v, count(lps) AS n RETURN v.id, n
