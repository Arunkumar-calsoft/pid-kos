// ============================================================================
// Question 10.10 — 10. External Interfaces
// Engineer question: "What equipment does each external interface ultimately connect to?"
//
// Operation: list
// Intent: external_interfaces
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (io:Node {pid_id: $pid_id, label: 'inlet/outlet'})-[:PIPE*1..20]-(equip:Node)
WHERE equip.label IN ['tank', 'valve', 'instrumentation']
  AND equip.structural_type = 'SYMBOL'
RETURN DISTINCT io.id AS interface_id, equip.id AS equipment_id,
       equip.label AS equipment_type,
       coalesce(equip.functional_label, equip.label) AS equipment_role
ORDER BY io.id, equip.id
LIMIT 50
