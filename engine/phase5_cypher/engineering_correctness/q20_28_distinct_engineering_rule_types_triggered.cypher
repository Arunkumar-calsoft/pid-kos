// ============================================================================
// Question 20.28 — 20. Engineering Correctness Validation
// Engineer question: "How many distinct engineering rule types have been triggered?"
//
// Operation: count
// Intent: engineering_correctness
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (a:Annotation {pid_id:$pid_id, type:'engineering_rule_violation'}) RETURN count(DISTINCT a.pattern_type) AS distinct_rule_count
