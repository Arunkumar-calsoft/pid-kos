// ============================================================================
// Question 1.2 — 1. Equipment Inventory
// Engineer question: "List all equipment symbol node IDs."
//
// Operation: list
// Required keywords: equipment
// Intent: engineering_inventory
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (n:Node {pid_id: $pid_id})
WHERE n.structural_type = 'SYMBOL' AND n.label <> 'background'
RETURN n.id AS symbol_id, n.label AS symbol_type
ORDER BY n.label, n.id
LIMIT 50
