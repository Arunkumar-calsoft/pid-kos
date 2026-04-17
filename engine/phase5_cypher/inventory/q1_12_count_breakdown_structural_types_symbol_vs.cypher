// ============================================================================
// Question 1.12 — 1. Equipment Inventory
// Engineer question: "Show a count breakdown of structural types (SYMBOL vs CONNECTOR)."
//
// Operation: count
// Required keywords: breakdown
// Intent: drawing_consistency
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (n:Node {pid_id:$pid_id}) RETURN n.structural_type AS structural_type, count(n) AS type_count ORDER BY type_count DESC
