// ============================================================================
// Question 16.7 — 16. Annotation Triage & Metadata
// Engineer question: "Show annotations for the pipeline integrity team."
//
// Operation: list
// Required keywords: pipeline, integrity
// Intent: cross_domain
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (ann:Annotation {audience:'pipeline_integrity', pid_id:$pid_id}) RETURN ann.id, ann.type
LIMIT 50
