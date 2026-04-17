// ============================================================================
// Question 20.3 — 20. Engineering Correctness Validation
// Engineer question: "Show a breakdown of violations by severity level."
//
// Operation: count
// Intent: cross_domain
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (a:Annotation {pid_id:$pid_id, type:'engineering_rule_violation'}) RETURN a.severity AS severity, count(a) AS violation_count ORDER BY CASE a.severity WHEN 'CRITICAL' THEN 1 WHEN 'HIGH' THEN 2 ELSE 3 END
