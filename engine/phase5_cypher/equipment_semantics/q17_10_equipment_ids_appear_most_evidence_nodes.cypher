// ============================================================================
// Question 17.10 — 17. Equipment Semantics
// Engineer question: "Show which equipment IDs appear most in Evidence nodes."
//
// Operation: count
// Intent: cross_domain
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (e:Evidence {pid_id:$pid_id}) WHERE e.equipment_id IS NOT NULL RETURN e.equipment_id, count(*) AS n ORDER BY n DESC
