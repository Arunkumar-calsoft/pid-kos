// ===================================================================
// 01_equipment_completely_unconnected.cypher (CORRECTED)
// Engineer view: "What equipment exists on this P&ID and how is it used?"
//
// SCHEMA UPDATES APPLIED:
//   - Equipment nodes → Node with label IN [equipment_labels]
//   - [:CONNECTED] → [:ENDPOINT_OF]
//   - Added pid_id scoping
//
// Read-only. No assumptions, no inference.
// ===================================================================




// Required keywords: unconnected
/* -------------------------------------------------------------------
7. What equipment is completely unconnected?
   (Floating symbols / drawing errors)
   
   NOTE: Checks for equipment with no ENDPOINT_OF relationships
------------------------------------------------------------------- */




MATCH (e:Node {pid_id: $pid_id})
WHERE e.label IN ['tank', 'valve', 'instrumentation', 'general', 'crossing', 'inlet/outlet']
  AND NOT EXISTS {
    MATCH (e)-[:ENDPOINT_OF]->(:LogicalPipeSegment)
  }
RETURN
  e.id    AS equipment_tag,
  e.label AS equipment_type,
  e.bbox  AS location_on_drawing
ORDER BY equipment_tag
LIMIT 200
