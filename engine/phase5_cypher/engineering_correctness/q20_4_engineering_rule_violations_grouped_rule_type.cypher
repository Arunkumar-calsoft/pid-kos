// ============================================================================
// Question 20.4 — 20. Engineering Correctness Validation
// Engineer question: "Show engineering rule violations grouped by rule type."
//
// Operation: count
// Intent: engineering_correctness
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (a:Annotation {pid_id:$pid_id, type:'engineering_rule_violation'}) RETURN a.pattern_type AS rule_type, a.severity AS severity, count(a) AS violation_count ORDER BY violation_count DESC
