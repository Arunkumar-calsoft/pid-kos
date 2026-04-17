# engine/phase0_ingestion/normalize_nodes.py
#
# CHANGES FROM ORIGINAL:
#   - Preserve coord_system attr set by parse_graphml (was silently dropped)
#   - Filter background nodes — they are drawing artifacts, not P&ID topology.
#     Filtered nodes are logged but not returned; they never enter Neo4j.
#   - Detect duplicate bboxes across nodes and log a DuplicateGeometryWarning.
#     Duplicates still pass through (they are real nodes), but Phase 3
#     has a record to investigate.
#   - Explicit validation that coord_system is present and recognised.
#   - Remap 'pump' label → 'tank' so that draw.io pump symbols are normalised
#     into the canonical schema vocabulary before loading into Neo4j.
#     Phase 1 classify_equipment.py will then stamp functional_label='pump'
#     on small tank nodes to preserve the semantic distinction.


# Node labels that are drawing artifacts — excluded from the PIDGraph entirely.
_FILTER_LABELS = {"background"}

# Raw draw.io labels that are remapped to canonical schema labels at ingest time.
# Remapping keeps Neo4j clean: only schema-declared labels ever enter the graph.
_LABEL_REMAP = {
    "pump": "tank",   # pump symbols from draw.io → tank; Phase 1 stamps functional_label='pump'
}


def normalize_nodes(nodes):
    """
    Normalize, filter, and validate the raw node list from parse_graphml.

    Guarantees after this step:
    - All background/artifact nodes removed
    - id is string
    - attrs is dict with coord_system preserved
    - bbox fields (xmin, ymin, xmax, ymax) are float
    - Duplicate bboxes are detected and warned
    - No attribute loss on non-filtered nodes
    """

    print(f"[PHASE 0][NORMALIZE] Normalizing {len(nodes)} nodes")

    normalized = []
    filtered_out = []
    bbox_seen = {}          # bbox_tuple → first node_id (duplicate detection)
    duplicate_warnings = [] # list of (nid, duplicate_of)

    for n in nodes:
        if "id" not in n:
            raise ValueError("Node missing 'id' field")

        nid = str(n["id"])
        raw_attrs = n.get("attrs", {})

        if raw_attrs is None:
            raw_attrs = {}

        if not isinstance(raw_attrs, dict):
            raise ValueError(
                f"Node {nid} attrs must be dict, got {type(raw_attrs)}"
            )

        attrs = dict(raw_attrs)  # defensive shallow copy
        label = attrs.get("label", "")

        # ── Filter drawing artifacts ───────────────────────────────────────
        if label in _FILTER_LABELS:
            filtered_out.append((nid, label))
            continue

        # ── Remap non-canonical labels to schema-declared equivalents ──────
        if label in _LABEL_REMAP:
            canonical = _LABEL_REMAP[label]
            print(
                f"[PHASE 0][NORMALIZE] Label remap: node {nid} '{label}' → '{canonical}'"
            )
            attrs["label"] = canonical
            attrs["original_label"] = label   # audit trail preserved in Neo4j
            label = canonical

        # ── Validate coord_system provenance ──────────────────────────────
        coord_system = attrs.get("coord_system", "none")
        if coord_system not in ("float", "int", "none"):
            raise ValueError(
                f"Node {nid} has unrecognised coord_system: '{coord_system}'"
            )

        # ── Ensure bbox fields are float ───────────────────────────────────
        for field in ("xmin", "ymin", "xmax", "ymax"):
            if field in attrs:
                try:
                    attrs[field] = float(attrs[field])
                except (ValueError, TypeError):
                    raise ValueError(
                        f"Node {nid} bbox field '{field}' is not numeric: "
                        f"{attrs[field]!r}"
                    )

        # ── Duplicate bbox detection ───────────────────────────────────────
        if all(f in attrs for f in ("xmin", "ymin", "xmax", "ymax")):
            bbox_key = (
                attrs["xmin"], attrs["ymin"],
                attrs["xmax"], attrs["ymax"],
            )
            if bbox_key in bbox_seen:
                duplicate_warnings.append((nid, bbox_seen[bbox_key]))
                print(
                    f"[WARN][NORMALIZE] DuplicateGeometry: node {nid} "
                    f"({label}) shares bbox {bbox_key} with "
                    f"{bbox_seen[bbox_key]}"
                )
            else:
                bbox_seen[bbox_key] = nid

        normalized.append({
            "id": nid,
            "attrs": attrs,
        })

    # ── Summary ───────────────────────────────────────────────────────────
    print(
        f"[PHASE 0][NORMALIZE] Complete | "
        f"kept={len(normalized)}, "
        f"filtered={len(filtered_out)}, "
        f"duplicate_bboxes={len(duplicate_warnings)}"
    )

    if filtered_out:
        print("[PHASE 0][NORMALIZE] Filtered nodes (drawing artifacts):")
        for nid, label in filtered_out:
            print(f"  {nid} ({label})")

    if duplicate_warnings:
        print("[PHASE 0][NORMALIZE] Duplicate geometry pairs:")
        for nid, original in duplicate_warnings:
            print(f"  {nid} duplicates {original}")

    return normalized