// ============================================================================
// 06_orphan_arrows.cypher (CORRECTED)
// Engineer View — AS-DRAWN flow indication on the P&ID
//
// SCHEMA UPDATES APPLIED:
//   - Arrow-[:FLOW_EVIDENCE]->LPS  →  Evidence-[:ABOUT]->LPS check
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
5. Orphan arrows
   Engineer question:
     "Are there arrows drawn that don't clearly belong to any pipe?"
--------------------------------------------------------------------------- */




MATCH (a:Arrow {pid_id: $pid_id})
WHERE NOT EXISTS {
  MATCH (:LogicalPipeSegment {pid_id: $pid_id})<-[:ABOUT]-(e:Evidence)
  WHERE e.source = 'phase2_flow_evidence' AND e.arrow_id = a.id
}
RETURN
  a.id AS orphan_arrow
ORDER BY a.id
LIMIT 100
