# engine/phase1_segmentation/classify_nodes.py
#
# Structural node classification — Phase 1 only.
# Assigns structural_type to every Node based on id prefix and bbox position.
#
# Types:
#   CONNECTOR — pure topology wire node (id starts with 'connector')
#   SYMBOL    — any labeled node (valve, tank, arrow, crossing, general, etc.)
#   BOUNDARY  — node touching the drawing border (±10px from image edge)
#   UNKNOWN   — fallback (should be zero after this runs)
#
# No domain semantics assigned here. SYMBOL covers everything with a label.
# Phase 4 assigns Equipment / Instrument / etc. on top of SYMBOL.
#

def classify_nodes_structurally(driver, database, image_width, image_height, pid_id: str):
    """
    Two-pass classification:
      Pass 1 — base type from id prefix and label presence
      Pass 2 — override to BOUNDARY if bbox touches drawing edge

    FIX: Both queries now scoped to pid_id. Previously used MATCH (n:Node)
    which matched all nodes across all PIDs. When PID_0 ran after PID_2,
    PID_2 nodes were reclassified using PID_0's image dimensions, incorrectly
    marking PID_2 boundary nodes as BOUNDARY and contaminating LPS collapse.
    """

    # Pass 1: base structural type — scoped to pid_id
    base_query = """
    MATCH (n:Node {pid_id: $pid_id})
    WITH n,
         CASE
            WHEN n.id STARTS WITH 'connector' THEN 'CONNECTOR'
            WHEN n.label IS NOT NULL AND n.label <> '' THEN 'SYMBOL'
            ELSE 'UNKNOWN'
         END AS base_type
    SET n.structural_type = base_type
    RETURN count(n) AS updated
    """

    # Pass 2: boundary override — scoped to pid_id
    # Uses toFloat() to ensure parameter arithmetic works safely.
    # Nodes whose bbox touches within 10px of any image edge → BOUNDARY.
    boundary_query = """
    MATCH (n:Node {pid_id: $pid_id})
    WHERE n.xmin < 10
       OR n.ymin < 10
       OR n.xmax > toFloat($W) - 10
       OR n.ymax > toFloat($H) - 10
    SET n.structural_type = 'BOUNDARY'
    """

    with driver.session(database=database) as session:
        result = session.run(base_query, pid_id=pid_id)
        rec = result.single()
        updated = rec["updated"] if rec else 0

        session.run(boundary_query, W=image_width, H=image_height, pid_id=pid_id)

    print(f"[Phase 1] classify_nodes: {updated} nodes classified (image {image_width}×{image_height})")