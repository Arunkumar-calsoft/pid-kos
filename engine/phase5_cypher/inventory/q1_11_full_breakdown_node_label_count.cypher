// ============================================================================
// Question 1.11 — 1. Equipment Inventory
// Engineer question: "Show a full breakdown of every node label and its count."
//
// Operation: count
// Intent: engineering_inventory
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (n:Node {pid_id:$pid_id}) RETURN n.label AS equipment_type, count(n) AS type_count ORDER BY type_count DESC
