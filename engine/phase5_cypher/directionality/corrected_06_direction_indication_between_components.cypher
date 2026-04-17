// ============================================================================
// 06_direction_indication_between_components.cypher (CORRECTED)
// Engineer View — AS-DRAWN flow indication on the P&ID
//
// SCHEMA UPDATES APPLIED:
//   - Equipment nodes → Node with label IN [equipment_labels]
//   - [:CONNECTED] → [:ENDPOINT_OF]
//   - Arrow-[:FLOW_EVIDENCE]->LPS → Evidence-[:ABOUT]->LPS
//   - Added pid_id scoping
//
// This file answers only:
//   "What direction information is explicitly drawn on the diagram?"
//
// NO inference
// NO operational meaning
// NO assumptions about real flow
// ============================================================================




/* ---------------------------------------------------------------------------
6. Direction indication BETWEEN components (structural inspection)
   Engineer question:
   "Is a single logical pipe run—with arrows—spanning two equipment endpoints?"
   NOTE:
     • No parameters (verifier-safe)
     • Returns ALL such cases for inspection
--------------------------------------------------------------------------- */




MATCH (e1:Node)-[:ENDPOINT_OF]->(lps:LogicalPipeSegment {pid_id: $pid_id})<-[:ENDPOINT_OF]-(e2:Node)
WHERE e1.label IN ['tank', 'valve', 'instrumentation', 'general', 'crossing', 'inlet/outlet']
  AND e2.label IN ['tank', 'valve', 'instrumentation', 'general', 'crossing', 'inlet/outlet']
  AND e1.id < e2.id  // Avoid duplicates
OPTIONAL MATCH (lps)<-[:ABOUT]-(ev:Evidence)
WHERE ev.source = 'phase2_flow_evidence'
RETURN DISTINCT
  e1.id                           AS equipment_A,
  e1.label                        AS equipment_A_type,
  e2.id                           AS equipment_B,
  e2.label                        AS equipment_B_type,
  lps.id                          AS pipe_run,
  collect(DISTINCT ev.arrow_id)   AS direction_arrows,
  lps.flow_state                  AS phase4_flow_state,
  lps.flow_direction              AS phase4_direction
ORDER BY size(direction_arrows) DESC
LIMIT 200
