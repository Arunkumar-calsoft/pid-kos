// ============================================================================
// Question 17.9 — 17. Equipment Semantics
// Engineer question: "Which LPS have both arrow flow evidence and equipment semantics evidence?"
//
// Operation: list
// Intent: cross_domain
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (lps:LogicalPipeSegment {pid_id: $pid_id})
WHERE EXISTS { MATCH (lps)<-[:ABOUT]-(e1:Evidence) WHERE e1.source = 'phase2_flow_evidence' }
  AND EXISTS { MATCH (lps)<-[:ABOUT]-(e2:Evidence) WHERE e2.source = 'phase3_equipment_semantics' }
RETURN lps.id AS lps_id, lps.flow_state AS flow_state,
       lps.flow_direction AS flow_direction, lps.flow_confidence AS confidence
ORDER BY lps.id
LIMIT 50
