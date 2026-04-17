// ===================================================================
// 01_equipment_belongs_skid_package.cypher (CORRECTED)
// Engineer view: "What equipment exists on this P&ID and how is it used?"
//
// SCHEMA UPDATES APPLIED:
//   - Equipment nodes → Node with label IN [equipment_labels]
//   - Skid-[:HAS_SKID]->Equipment → Plant→Skid→PID→Node path
//   - Added pid_id scoping (implicit via PID match)
//
// NOTE: The schema hierarchy is Plant→Skid→PID→Node, not Skid→Equipment
//
// Read-only. No assumptions, no inference.
// ===================================================================




// Required keywords: skid
/* -------------------------------------------------------------------
4. What equipment belongs to each skid / package?
   (As drawn grouping — no functional meaning implied)
   
   CORRECTED: Follows Plant→Skid→PID→Node path
------------------------------------------------------------------- */




MATCH (plant:Plant)-[:HAS_SKID]->(skid:Skid)-[:HAS_PID]->(pid:PID)
MATCH (pid)-[:CONTAINS]->(e:Node)
WHERE e.label IN ['tank', 'valve', 'instrumentation', 'general', 'crossing', 'inlet/outlet']
RETURN
  plant.plant_id  AS plant,
  skid.skid_id    AS skid_id,
  pid.pid_id      AS pid_id,
  e.id            AS equipment_tag,
  e.label         AS equipment_type,
  e.flow_state    AS phase4_flow_state
ORDER BY skid_id, pid_id, equipment_tag
LIMIT 300
