// ============================================================================
// Question 1.13 — 1. Equipment Inventory
// Engineer question: "Show all tanks on this drawing."
//
// Operation: list
// Required keywords: tank
// Intent: engineering_inventory
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (n:Node {label:'tank', pid_id:$pid_id}) RETURN n.id, n.xmin, n.ymin
LIMIT 50
