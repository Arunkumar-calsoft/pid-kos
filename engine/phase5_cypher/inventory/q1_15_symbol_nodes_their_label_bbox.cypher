// ============================================================================
// Question 1.15 — 1. Equipment Inventory
// Engineer question: "Show all SYMBOL nodes with their label and bbox."
//
// Operation: list
// Required keywords: symbol
// Intent: engineering_inventory
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (n:Node {structural_type:'SYMBOL', pid_id:$pid_id}) RETURN n.id, n.label, n.xmin, n.xmax, n.ymin, n.ymax
LIMIT 50
