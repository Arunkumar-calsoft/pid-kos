// ============================================================================
// Question 20.26 — 20. Engineering Correctness Validation
// Engineer question: "Give me a full engineering correctness summary for this drawing."
//
// Operation: count
// Intent: engineering_correctness
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (a:Annotation {pid_id:$pid_id, type:'engineering_rule_violation'}) WITH a.severity AS severity, a.pattern_type AS rule, coalesce(properties(a).hitl_status, 'pending') AS status, count(a) AS cnt RETURN severity, rule, status, cnt ORDER BY CASE severity WHEN 'CRITICAL' THEN 1 WHEN 'HIGH' THEN 2 ELSE 3 END, cnt DESC
