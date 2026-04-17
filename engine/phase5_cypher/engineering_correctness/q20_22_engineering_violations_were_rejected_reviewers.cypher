// ============================================================================
// Question 20.22 — 20. Engineering Correctness Validation
// Engineer question: "Show engineering violations that were REJECTED by reviewers."
//
// Operation: list
// Intent: engineering_correctness
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (a:Annotation {pid_id:$pid_id, type:'engineering_rule_violation'})-[:ANNOTATES]->(n:Node)
WHERE properties(a).hitl_status = 'REJECTED'
RETURN a.pattern_type AS rule_id, n.id AS equipment_id,
       properties(a).rejection_reason AS reason,
       properties(a).reviewed_by AS reviewer
ORDER BY properties(a).reviewed_at DESC
LIMIT 50
