// ===================================================================
// 03_which_lines_have_multiple_branches.cypher (CORRECTED)
// Engineer view: "What lines exist and how are they drawn/connected?"
//
// SCHEMA UPDATES APPLIED:
//   - Added pid_id scoping
//
// Structural only. No flow or operation meaning.
// ===================================================================




/* -------------------------------------------------------------------
6. Which lines have multiple branches?
   (Highly connected piping)
------------------------------------------------------------------- */




MATCH (ps:PipeSegment {pid_id: $pid_id})-[j:JOINS_AT]->()
WITH ps, count(j) AS branch_count
WHERE branch_count > 1
RETURN
  ps.id         AS line_id,
  branch_count  AS number_of_branches
ORDER BY branch_count DESC
LIMIT 100
