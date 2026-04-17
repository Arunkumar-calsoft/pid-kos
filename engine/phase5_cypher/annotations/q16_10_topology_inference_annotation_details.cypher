// ============================================================================
// Question 16.10 — 16. Annotation Triage & Metadata
// Engineer question: "Show topology inference annotation details."
//
// Operation: list
// Required keywords: topology, inference
// Intent: connectivity_topology
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (ann:Annotation {intent:'topology_inference', pid_id:$pid_id}) RETURN ann.id, ann.type, ann.target_id
LIMIT 50
