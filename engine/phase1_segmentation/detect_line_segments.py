# engine/phase1_segmentation/detect_line_segments.py
#
# Topology node classifier — Phase 1 only.
# Determines whether a node is a pure line/connector carrier
# (no semantic meaning, just structural wire).
#
# Moved from segmentation/ to phase1_segmentation/ because
# is_line_node is a topology classification utility, not flow detection.
# detect_arrows / arrow geometry stays in phase2_flow/.
#
# FIX-1: Removed dead degree guard. `degree` is not a property on node
#         dicts from parse_graphml/normalize_nodes — it was always 0,
#         making the guard silently dead and is_line_node always False
#         for any node where degree check was the deciding factor.
#         Label match alone is the correct and sufficient classifier here.

CONNECTOR_LABELS = {"connector", "crossing", "line_mid", "junction"}


def is_line_node(node):
    """
    Returns True if the node is a pure structural connector
    based on its label.

    Connector labels: connector, crossing, line_mid, junction.

    NOTE: degree guard was removed (FIX-1) — degree is a graph
    property not present on raw node dicts at this stage.
    """
    attrs = node.get("attrs", {})
    label = attrs.get("label", "").lower()
    return label in CONNECTOR_LABELS