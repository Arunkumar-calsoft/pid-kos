// ============================================================================
// Question 20.1 — 20. Engineering Correctness Validation
// Engineer question: "How many engineering rule violations exist on this drawing?"
//
// Operation: count
// Intent: engineering_correctness
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (a:Annotation {pid_id:$pid_id, type:'engineering_rule_violation'}) RETURN count(a) AS violation_count
