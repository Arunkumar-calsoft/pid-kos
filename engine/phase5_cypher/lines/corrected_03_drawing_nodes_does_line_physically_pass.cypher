// ===================================================================
// 03_drawing_nodes_does_line_physically_pass.cypher (CORRECTED)
// Engineer view: "What lines exist and how are they drawn/connected?"
//
// SCHEMA UPDATES APPLIED:
//   - Added pid_id scoping
//
// Structural only. No flow or operation meaning.
// ===================================================================




/* -------------------------------------------------------------------
2. What drawing nodes does each line physically pass through?
   (Bends, junction points, endpoints)
------------------------------------------------------------------- */




MATCH (ps:PipeSegment {pid_id: $pid_id})-[:CONTAINS]->(n:Node)
RETURN
  ps.id              AS line_id,
  n.id               AS node_id,
  n.structural_type  AS node_type,
  n.label            AS node_label
ORDER BY line_id
LIMIT 500
