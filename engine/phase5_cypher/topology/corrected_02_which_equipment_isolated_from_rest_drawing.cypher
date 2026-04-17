// ===================================================================
// 02_which_equipment_isolated_from_rest_drawing.cypher (CORRECTED)
// ===================================================================

// Required keywords: isolated
MATCH (e:Node {pid_id: $pid_id})
WHERE e.label IN ['tank', 'valve', 'instrumentation', 'general', 'crossing', 'inlet/outlet']
  AND NOT EXISTS {
    MATCH (e)-[:ENDPOINT_OF]->(:LogicalPipeSegment)
  }
RETURN
  e.id      AS isolated_equipment,
  e.label   AS equipment_type
ORDER BY isolated_equipment
LIMIT 200;
