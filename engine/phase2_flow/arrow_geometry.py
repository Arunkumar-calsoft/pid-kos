# engine/phase2_flow/arrow_geometry.py
#
# Arrow orientation detection from bounding box geometry.
# Relative import of symbol_dictionary stays — both live in phase2_flow/.

from .symbol_dictionary import SYMBOL_DICTIONARY


def detect_arrow_geometry(nodes):
    """
    Detect arrow orientation from bounding box aspect ratio.

    Returns:
        List of dicts: {arrow_id, direction, confidence, source}
        direction is 'LEFT_TO_RIGHT' or 'TOP_TO_BOTTOM'
    """
    arrow_aliases = SYMBOL_DICTIONARY["arrow"]["aliases"]
    results = []

    for n in nodes:
        label = (n.get("attrs") or {}).get("label", "").lower()
        if not label or not any(a in label for a in arrow_aliases):
            continue

        attrs = n.get("attrs", {})
        xmin  = attrs.get("xmin", 0)
        xmax  = attrs.get("xmax", 0)
        ymin  = attrs.get("ymin", 0)
        ymax  = attrs.get("ymax", 0)

        width     = xmax - xmin
        height    = ymax - ymin
        direction = "LEFT_TO_RIGHT" if width > height else "TOP_TO_BOTTOM"

        results.append({
            "arrow_id":  n["id"],
            "direction": direction,
            "confidence": SYMBOL_DICTIONARY["arrow"]["confidence"],
            "source": "geometry_bbox",
        })

    return results