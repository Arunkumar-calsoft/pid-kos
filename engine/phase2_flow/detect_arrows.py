# engine/phase2_flow/detect_arrows.py
#
# Arrow detection on a segment's node list.
#
# Changes from pid_kos version:
#   - from segmentation.symbol_dictionary → from .symbol_dictionary (relative, same package)
#   - Fixed label access: n['label'] → n['attrs']['label']
#     (nodes carry attrs dict, not top-level label key)

from .symbol_dictionary import SYMBOL_DICTIONARY


def detect_arrow_on_segment(nodes):
    """
    Detect arrow orientation from Node geometry within a segment.

    Args:
        nodes: list of node dicts (each has 'id' and 'attrs' sub-dict)

    Returns:
        dict: {direction, confidence, source}
    """
    arrow_aliases = SYMBOL_DICTIONARY["arrow"]["aliases"]

    arrow_nodes = [
        n for n in nodes
        if any(
            a in (n.get("attrs", {}).get("label") or "").lower()
            for a in arrow_aliases
        )
    ]

    if not arrow_nodes:
        return {"direction": "UNKNOWN", "confidence": 0.0, "source": "no_arrow_detected"}

    if len(arrow_nodes) > 1:
        return {"direction": "AMBIGUOUS", "confidence": 0.3, "source": "multiple_arrows"}

    arrow = arrow_nodes[0]
    attrs  = arrow.get("attrs", {})
    width  = attrs.get("xmax", 0) - attrs.get("xmin", 0)
    height = attrs.get("ymax", 0) - attrs.get("ymin", 0)

    direction = "LEFT_TO_RIGHT" if width > height else "TOP_TO_BOTTOM"

    return {
        "direction": direction,
        "confidence": SYMBOL_DICTIONARY["arrow"]["confidence"],
        "source": "geometry_arrow",
    }