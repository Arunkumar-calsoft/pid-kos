// ===================================================================
// 05_valve_inventory.cypher (CORRECTED)
// Engineer view: "Where are valves drawn and how are they placed?"
//
// SCHEMA UPDATES APPLIED:
//   - Equipment nodes → Node with valve labels
//   - Added pid_id scoping
//
// Structural only — no operational or control interpretation.
// ===================================================================




/* -------------------------------------------------------------------
1. Valve inventory (as drawn)
   
   CORRECTED: Uses Node instances with valve labels
------------------------------------------------------------------- */




MATCH (v:Node {pid_id: $pid_id})
WHERE v.label IN ['valve']
RETURN
  v.id          AS valve_id,
  v.label       AS valve_type,
  v.flow_state  AS phase4_flow_state,
  v.flow_direction AS phase4_direction
ORDER BY valve_id
LIMIT 500
