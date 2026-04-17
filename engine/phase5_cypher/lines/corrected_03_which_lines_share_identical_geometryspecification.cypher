// ===================================================================
// 03_which_lines_share_identical_geometryspecification.cypher (CORRECTED)
// ===================================================================

MATCH (ps:PipeSegment {pid_id: $pid_id})
WITH ps.geometry_hash AS geometry_hash,
     collect(ps.id) AS lines
WHERE geometry_hash IS NOT NULL AND size(lines) > 1
RETURN
  geometry_hash,
  lines AS similar_lines,
  size(lines) AS line_count
ORDER BY line_count DESC
LIMIT 200;
