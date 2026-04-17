// ============================================================================
// Question 20.21 — 20. Engineering Correctness Validation
// Engineer question: "Show HITL review status for engineering violations."
//
// Operation: count
// Intent: cross_domain
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (a:Annotation {pid_id:$pid_id, type:'engineering_rule_violation'}) RETURN coalesce(properties(a).hitl_status, 'pending') AS review_status, count(a) AS violation_count ORDER BY violation_count DESC
