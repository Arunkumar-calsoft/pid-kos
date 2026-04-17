// ============================================================================
// Question 1.16 — 1. Equipment Inventory
// Engineer question: "How many pumps are on this drawing?"
//
// Operation: count
// Intent: engineering_inventory
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (n:Node {pid_id:$pid_id}) WHERE n.label = 'tank' AND n.functional_label = 'pump' RETURN count(n) AS pump_count
