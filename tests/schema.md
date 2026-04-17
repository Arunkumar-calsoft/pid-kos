# Grounded Schema Context — PID Graph
> 100% verified against live Neo4j property samples + graphml source. Zero inference.
> Last verified: April 2026 against chatbot DB (PID_0 + PID_2, both PHASE7_COMPLETE).

---

## GRAPH PURPOSE
A structural graph extracted from a Piping & Instrumentation Diagram (PID) image.
No OCR tag names are stored. Identity is by node ID and symbol type only.
The graph captures: symbol positions, pipe connectivity, flow direction evidence,
and pre-computed structural quality annotations.

---

## NODE LABELS IN LIVE DB

| Label | Count | What it is |
|---|---|---|
| `Annotation` | 1502 | Pre-computed quality/structural observations (Phase 3) |
| `AnnotationRequest` | 75 | Human/system review requests for flagged nodes (Phase 0) |
| `Arrow` | 78 | Flow evidence carrier — linked to LPS via FLOW_EVIDENCE |
| `Evidence` | 469 | Directional evidence item for an LPS |
| `GlobalStatistic` | 8 | Cross-skid ESV frequency baseline (Phase 7) |
| `GlobalStatisticsSummary` | 1 | Plant-level statistics summary (Phase 7) |
| `LogicalPipeSegment` | 356 | Logical pipe route between two endpoint Nodes |
| `Node` | 914 | Every symbol + connector detected on the PID |
| `PID` | 2 | Top-level drawing node |
| `PipeSegment` | 223 | Physical pipe segment from graphml |
| `Plant` | 1 | Facility-level container |
| `Skid` | 1 | Process skid, owns PIDs |
| `SkidCorpus` | 1 | Cross-PID rarity corpus (Phase 7) |

> ⚠️ There is **NO** `Equipment` node label in the database.
>    Flow direction properties are denormalised onto `Node` records directly by Phase 4.

---

## Node.structural_type VALUES

`Node.structural_type` has **exactly 2 confirmed values** in the live DB:

| structural_type | Node.label | degree | What it means |
|---|---|---|---|
| `CONNECTOR` | `connector` | always 2 | Pipe path intermediate. Not a symbol — a junction point along a pipe. |
| `SYMBOL` | `tank`, `valve`, `instrumentation`, `general`, `arrow`, `crossing`, `inlet/outlet`, `inferred_check_valve` | varies | Any detected drawn symbol |

> ⚠️ `BOUNDARY` / `background` nodes are **filtered at Phase 0** and never loaded into Neo4j.
>    Do NOT query for `structural_type='BOUNDARY'` — that value does not exist in the live DB.
> ⚠️ `inlet/outlet` is `SYMBOL`, NOT `BOUNDARY`. Use `Node.label = 'inlet/outlet'` for external interfaces.

**Node.label values and meanings:**

| label | PID meaning | degree |
|---|---|---|
| `tank` | Main process vessel OR pump unit (when `functional_label='pump'`) | 4–12 |
| `valve` | Control or isolation valve | 1–3 |
| `instrumentation` | Instrument symbol (FT, LT, TE, PSV etc.) | 0–2 |
| `general` | Unclassified symbol — nozzle, reducer, misc fitting, tee point | 0–3 |
| `arrow` | Flow direction arrow drawn on a pipe (**symbol node** — NOT a flow evidence carrier) | always 2 |
| `crossing` | Pipe-over-pipe crossing or junction point | 1–3 |
| `inlet/outlet` | External system connection at drawing boundary | always 1 |
| `inferred_check_valve` | `general` node reclassified by Phase 1 as a check valve | 1–3 |
| `connector` | Pipe path intermediate (`structural_type='CONNECTOR'`) | always 2 |

> ⚠️ **There is NO `label='pump'` in the graph.**
>    Pump units (CND-PU-xxx) are `label='tank'` with `functional_label='pump'`.
>    **Query pumps with:** `n.label = 'tank' AND n.functional_label = 'pump'`

---

## NODE PROPERTIES (grounded)

### Node
- `id` → internal ID, format: `{label}{integer}` e.g. `valve94`, `connector306`, `tank12`
- `pid_id` → parent PID identifier e.g. `PID_0`, `PID_2`
- `label` → symbol class (see table above) — NOT an OCR tag name
- `functional_label` → set by Phase 1 on specific nodes:
  - `"pump"` — tank node with bbox width < 100 px (condensate pump unit CND-PU-xxx)
  - `"tank"` — small tank node reclassified from general
  - `"heat_exchanger"` — tank node reclassified as heat exchanger
  - **Query pumps with:** `n.label='tank' AND n.functional_label='pump'`
- `original_label` → preserved when Phase 0 or Phase 1 remapped the label
- `label_inferred` → BOOLEAN — `true` when Phase 1 changed the label from `general`
- `structural_type` → `SYMBOL` | `CONNECTOR` (BOUNDARY does not exist in live DB)
- `bbox` → `[xmin, ymin, xmax, ymax]` pixel coordinates on PID image
- `xmin`, `xmax`, `ymin`, `ymax` → individual bbox FLOAT pixel coordinates
- `coord_system` → coordinate reference system: `"float"` | `"int"`
- `source` → always `graphml`
- `flow_state` → `SEEDED` | `PROPAGATED` — only set on SYMBOL nodes after Phase 4; null otherwise
- `flow_direction` → `FORWARD` | `REVERSE` — null when unresolved
- `flow_confidence` → FLOAT 0.0–1.0 — null when unresolved
- `flow_source` → origin of flow assignment (set by Phase 4 flow_assignment)
- `flow_pid_id` → STRING — PID scope for the denormalised flow assignment

**Spatial bounds:** x=0–2292, y=0–1534

### LogicalPipeSegment
- `id` → `{nodeA_id}__{nodeB_id}` — encodes the two endpoint node IDs e.g. `arrow102__crossing151`
- `pid_id` → parent PID identifier
- `flow_state` → `SEEDED` | `PROPAGATED` | `UNKNOWN` | `BLOCKED` | `SEEDED_UNKNOWN`
  - `SEEDED` — direction confirmed directly from an arrow on the drawing
  - `PROPAGATED` — direction inferred by BFS expansion from a nearby seeded LPS
  - `UNKNOWN` — no direction could be determined; `flow_direction` is null
  - `BLOCKED` — propagation blocked by Phase 3.5 rule violation or structural rarity
  - `SEEDED_UNKNOWN` — has arrow evidence but direction is contradictory; `flow_direction` is null
- `flow_direction` → `FORWARD` | `REVERSE` | `null` (null when UNKNOWN / BLOCKED / SEEDED_UNKNOWN)
- `flow_confidence` → FLOAT 0.0–1.0
- `seed_confidence` → FLOAT — confidence at the seeding step (null for PROPAGATED/UNKNOWN)
- `flow_source` → `none` | `evidence` | `propagated` | `propagation_blocked`
- `flow_exit_node_id` → STRING — node ID where flow physically exits this LPS; used internally by Phase 4 BFS (FORWARD = spatially-last endpoint, REVERSE = spatially-first endpoint)
- `phase4_hint` → optional Phase 3/4 directive; confirmed values in live DB:
  - `direction_conflict_observed`
  - `direction_evidence_missing`  *(stamped directly on LPS by Phase 3 Step 5/Phase 4 pre-flight — no Annotation node)*
  - `lps_weak_evidence_consensus`
  - `lps_direction_unresolved`
  - `block_propagation_safety_violation`
- `phase4_blocked` → BOOLEAN — `true` on LPS blocked by Phase 3.5 safety violations
- `endpoints` → LIST of 2 node IDs `[nodeA_id, nodeB_id]`
- `trace_nodes` → ordered LIST of all node IDs along segment including endpoints
- `via` → LIST of intermediate connector node IDs (excludes endpoints)
- `length` → INTEGER hop count (1=direct, 2=one intermediate node)
- `source` → always `derived_logical`
- `created_at` → STRING ISO-8601 timestamp

### PipeSegment
- `id` → `PS_{integer}` e.g. `PS_1`, `PS_57`
- `pid_id` → parent PID identifier
- `segment_status` → `NORMAL` (only confirmed value)
- `node_count` → INTEGER number of nodes in segment (range: 2–8+)
- `component_id` → INTEGER connected component group ID (0=main network, >0=isolated subgraph)
- `geometry_hash` → STRING structural fingerprint for deduplication
- `source` → always `derived`

### Arrow
> ⚠️ `Arrow` is a **distinct node type** from `Node{label:'arrow'}`.
> - `Node{label:'arrow'}` — drawing symbol node on the PID, connected via PIPE edges
> - `Arrow` — flow evidence carrier, linked to `LogicalPipeSegment` via FLOW_EVIDENCE
> - Arrow nodes have **no incoming relationships** — they are sources only.

- `id` → `arrow{integer}` e.g. `arrow102`
- `pid_id` → parent PID identifier

### Evidence
Evidence nodes carry per-equipment directional evidence created by Phase 3 equipment semantics.
Arrow-level flow evidence lives on the `FLOW_EVIDENCE` relationship, not on Evidence nodes.

- `id` → unique evidence identifier
- `pid_id` → parent PID identifier
- `observed_direction` → `FORWARD` | `REVERSE` — **canonical resolved value; use this**
- `direction_hint` → `FORWARD` | `REVERSE` | `UNKNOWN`
- `confidence` → FLOAT 0.0–1.0
- `low_confidence` → BOOLEAN
- `role` → `upstream` | `downstream` | `inlet` | `outlet` | `ambiguous` | null
- `axis` → dominant axis: `H` (horizontal) | `V` (vertical) | null
- `equipment_id` → ID of the equipment Node this evidence is for
- `equipment_label` → label of the equipment Node
- `source` → `phase2_flow_evidence` | `phase3_boundary_semantics` | `phase3_equipment_semantics` | `phase3_check_valve` | `phase3_topology_inference` | `arrow_binding` | `phase3_freq_summary`
- `first_seen` → STRING ISO-8601 timestamp

### Annotation
- `id` → unique annotation identifier
- `pid_id` → parent PID identifier
- `intent` → `observation` | `statistical_summary` | `equipment_semantics` | `check_valve_semantics` | `topology_inference` | `boundary_inference` | null
- `type` → fine-grained annotation type (see full enum below)
- `pattern_type` → structural pattern name (overlaps with type, more specific)
- `source` → pipeline phase that created this (see Annotation.source enum below)
- `label` → mirrors the Node.label of the annotated node
- `category` → broad grouping e.g. `ESV`, `KAV`
- `audience` → intended consumer e.g. `engineer`
- `severity` → `CRITICAL` | `HIGH` | `MEDIUM`
- `hitl_severity` → `CRITICAL` | `HIGH` — Phase 7 HITL severity bucket
- `rarity_score` → FLOAT 0.0–1.0
- `rarity_label` → STRING human-readable rarity bucket
- `is_canary` → BOOLEAN
- `propagation_blocked` → BOOLEAN — marks LPS that should block Phase 4 propagation
- `phase4_hint` → propagation directive copied to LPS during Phase 3
- `node_id` → ID of the Node this annotation targets
- `lps_id` → ID of the LogicalPipeSegment this annotation targets
- `ps_id` → ID of the PipeSegment this annotation targets
- `target_id` → generic target ID (equipment node)
- `equipment_id` → ID of the equipment node (for equipment semantics annotations)
- `valve_id` → ID of the valve node (for check valve / isolation annotations)
- `role` → `inlet` | `outlet` — for equipment semantics annotations
- `explanation` → STRING human-readable description of the violation or observation
- `inferred_from` → STRING — source of inference (for topology_inference annotations)
- `semantic_source` → STRING — source of semantic rule
- `required_equipment` → STRING — equipment type required but missing (for rule violations)
- `resolution_rule` → STRING — the rule that was applied
- `directions` → STRING summary of direction counts
- `other_pids` → STRING cross-PID context
- `degree` → INTEGER connectivity degree of annotated node
- `adj_degree` → INTEGER adjacency degree
- `absolute_count` → INTEGER raw occurrence count
- `total_observations` → INTEGER total observations in corpus
- `n_total`, `n_forward`, `n_reverse`, `n_resolved` → INTEGER directional counts
- `lps_count` → INTEGER number of LPS involved
- `lps_list` → LIST of LPS IDs
- `unique_target_count` → INTEGER
- `normalized_ratio` → FLOAT — frequency relative to corpus
- `total_types`, `kav_types`, `kav_total`, `esv_types`, `esv_total` → summary counts (on PID-level summary annotations)
- `motif_chain_count` → INTEGER motif chain length
- `cycle_length` → INTEGER — for `pipe_segment_cycle_member` annotations
- `max_hops_checked` → INTEGER — for reachability annotations
- `pipeline_integrity_count` → INTEGER
- `engineer_review_count` → INTEGER
- `consensus_fraction` → FLOAT
- `skid_type` → STRING — skid classification
- `first_seen`, `last_seen` → STRING ISO-8601 timestamps
- `corpus_normalized` → BOOLEAN — cross-PID percentile normalization applied
- `corpus_mean` → FLOAT cross-PID mean frequency
- `corpus_std` → FLOAT cross-PID standard deviation
- `corpus_total` → INTEGER total observations across all PIDs
- `corpus_pid_count` → INTEGER number of PIDs contributing to corpus
- `corpus_updated_at` → STRING ISO-8601 timestamp of corpus update
- `percentile_rank` → FLOAT 0.0–1.0 percentile within cross-PID corpus
- `hitl_status` → `APPROVED` | `REJECTED` | null (pending) — Phase 7 review status
- `reviewed_by` → STRING reviewer identifier (e.g. `phase7_auto` for auto-approved)
- `review_note` → STRING approval note
- `rejection_reason` → STRING reason for rejection
- `reviewed_at` → STRING ISO-8601 timestamp

**Annotation.type full ENUM (confirmed from live DB):**

| type | typical target | meaning |
|---|---|---|
| `direction_observation` | `LogicalPipeSegment` | Observed flow direction on this segment |
| `direction_frequency_summary` | `LogicalPipeSegment` | Statistical direction frequency summary |
| `direction_conflict_observed` | `LogicalPipeSegment` | Conflicting arrows on same segment |
| `lps_direction_unresolved` | `LogicalPipeSegment` | Direction could not be resolved |
| `lps_weak_evidence_consensus` | `LogicalPipeSegment` | Weak consensus among evidence |
| `orphan_node` | `Node` | Node with no connections (degree=0) |
| `dead_end_pipe_segment` | `PipeSegment` | Single-end open pipe segment |
| `structural_branch` | `Node` | 3-way pipe junction (degree=3) |
| `structural_t_junction` | `Node` | T-shaped junction subtype |
| `structural_high_degree` | `Node` | Unusually high degree (4+) |
| `large_manifold_node` | `Node` | Very high degree manifold (≥10) |
| `pipe_junction` | `Node` | Generic pipe junction point |
| `pipe_segment_cycle_member` | `PipeSegment` | Part of a loop/cycle |
| `endpoint_collision` | `Node` | Two pipe ends at the same point |
| `pipe_segment_no_logical_mapping` | `PipeSegment` | No LPS covers this segment |
| `pipe_segment_no_evidence_via_lps` | `PipeSegment` | LPS has no flow evidence |
| `ps_unreachable_from_evidence` | `PipeSegment` | Cannot trace from any evidence |
| `engineering_rule_violation` | `Node` | Phase 3.5 rule violation (missing check valve / isolation valve / strainer) |
| `cross_pid_shared_node` | `Node` | Node ID shared across PIDs |
| `rare_motif_local` | `PipeSegment` | Rare local structural pattern |
| `structural_pattern_frequency` | `Annotation` | Occurrence frequency summary |
| `structural_pattern_rarity` | `Annotation` | Rarity score and tier |

**Annotation.source ENUM (confirmed from live DB):**
`phase3` | `phase3_structural_patterns` | `phase3_structural_frequencies` |
`phase3_structural_rarity` | `phase3_freq_summary` |
`phase3` | `phase3_structural_patterns` | `phase3_structural_frequencies` |
`phase3_structural_rarity` | `phase3_freq_summary` |
`phase3_engineering_rules` | `phase3_equipment_semantics` | `phase3_boundary_semantics` | `phase3_check_valve` | `phase3_topology_inference`

### AnnotationRequest
Created by Phase 0 for each anomaly detected during graphml ingestion.

- `request_id` → unique AR identifier
- `pid_id` → parent PID identifier
- `node_id` → ID of the flagged Node
- `label` → Node.label of the flagged node
- `anomaly_type` → `DUPLICATE_BBOX` | `DANGLING_INLINE` | `ORPHAN_NODE`
- `detail` → STRING human-readable description
- `status` → `OPEN` (only confirmed value)
- `source` → always `graphml`
- `phase_origin` → INTEGER pipeline phase that created this (0 = Phase 0)

### PID
- `pid_id` → drawing identifier e.g. `PID_0`, `PID_2`
- `graphml_path` → relative path to the graphml source file
- `image_path` → relative path to the PID image file
- `date` → drawing date string
- `rev` → revision identifier
- `status` → processing status e.g. `PHASE7_COMPLETE`, `PHASE6_COMPLETE`, `REGISTERED`

### Plant
- `plant_id` → facility identifier e.g. `PLANT_001`
- `name` → STRING plant name

### Skid
- `skid_id` → skid identifier e.g. `SKID_01`
- `skid_type` → skid classification e.g. `CONDENSATE`
- `plant_id` → back-reference to parent Plant

### SkidCorpus
- `id` → corpus identifier e.g. `corpus_SKID_01`
- `skid_id` → parent Skid identifier
- `pid_count` → INTEGER number of PIDs in the corpus
- `pattern_count` → INTEGER number of ESV patterns normalized
- `annotations_updated` → INTEGER number of rarity Annotations updated
- `created_at` → STRING ISO-8601 timestamp
- `updated_at` → STRING ISO-8601 timestamp
- Relationship: `(SkidCorpus)-[:CORPUS_OF]->(Skid)`
- Created by Phase 7 (`build_skid_corpus`). Requires ≥2 PIDs.

### GlobalStatistic
- `id` → statistic node identifier e.g. `gstat_structural_branch`
- `pattern_type` → ESV/KAV pattern name e.g. `dead_end_pipe_segment`, `pipe_junction`
- `category` → always `ESV`
- `plant_id` → parent Plant identifier
- `global_mean` → FLOAT mean `unique_target_count` across PIDs
- `global_std` → FLOAT standard deviation
- `global_total` → INTEGER sum of `absolute_count` across all PIDs
- `global_pid_count` → INTEGER number of contributing PIDs
- `skid_count` → INTEGER number of contributing skids
- `global_rarity` → `globally_absent` | `globally_rare` | `globally_typical` | `globally_common` | `globally_dominant`
  - ⚠️ `globally_uncommon` does **NOT** exist in live data — do not use it in queries
- `global_rarity_score` → FLOAT 0.0–1.0
- `created_at` → STRING ISO-8601 timestamp
- `updated_at` → STRING ISO-8601 timestamp
- Relationship: `(GlobalStatistic)-[:STATISTICS_OF]->(Plant)`
- Created by Phase 7. Consulted by Phase 4 FSM to adjust seed_confidence (rare → boost, dominant → reduce).

### GlobalStatisticsSummary
- `id` → summary identifier e.g. `gstat_summary_PLANT_001`
- `plant_id` → parent Plant identifier
- `pattern_count` → INTEGER number of GlobalStatistic nodes
- `total_pids` → INTEGER number of PIDs contributing
- `total_skids` → INTEGER number of skids contributing
- `created_at` → STRING ISO-8601 timestamp
- `updated_at` → STRING ISO-8601 timestamp
- Relationship: `(GlobalStatisticsSummary)-[:SUMMARY_OF]->(Plant)`

---

## RELATIONSHIP TYPES (grounded)

| Relationship | From → To | Properties | Notes |
|---|---|---|---|
| `PIPE` | `Node → Node` | `edge_label`=`"solid"`, `flow_direction`=`"UNKNOWN"`, `pid_id`, `source`=`"graphml"` | Physical pipe adjacency. Traversed undirected: `(a)-[:PIPE]-(b)`. `flow_direction` on PIPE is always UNKNOWN — use LPS for resolved direction. |
| `ENDPOINT_OF` | `Node → LogicalPipeSegment` | `source`=`"derived_logical"` | Structural endpoint binding only — no start/end semantics. |
| `ENDPOINT_OF` | `PipeSegment → Node` | `source`=`"derived_logical"` | Physical segment → endpoint node. |
| `FLOW_EVIDENCE` | `Arrow → LogicalPipeSegment` | `confidence`, `cosine_alignment`, `dx`, `dy`, `direction_hint`, `low_confidence`, `pixel_direction`, `direction_method`, `seg_vec_source`, `source`, `created_at` | Arrow → LPS directional evidence. `pixel_direction`: EAST/WEST/NORTH/SOUTH. `direction_method`: `pixel_tip`/`bbox_aspect`. |
| `COVERS` | `LogicalPipeSegment → PipeSegment` | `via_node`=connector ID, `source`=`"derived_logical"` | LPS → physical segment mapping. **Always LPS→PS, never reversed.** |
| `ADJACENT_VIA_NODES` | `LogicalPipeSegment → LogicalPipeSegment` | `via_nodes`=LIST, `via_count`=INTEGER | LPS adjacency for flow BFS propagation. |
| `ADJACENT_VIA_NODES` | `PipeSegment → PipeSegment` | `via_nodes`=LIST, `via_count`=INTEGER | Physical segment adjacency. |
| `JOINS_AT` | `PipeSegment → PipeSegment` | `kind`=`"two_hop"`, `trace_nodes`=LIST of 3 IDs | Segment junction. `trace_nodes[1]` is the junction symbol; indices 0 and 2 are connectors. |
| `CONTAINS` | `PID → Node` | none | Drawing scope containment. |
| `CONTAINS` | `PipeSegment → Node` | none | Physical segment → member nodes. |
| `ANNOTATES` | `Annotation → LogicalPipeSegment` | none | |
| `ANNOTATES` | `Annotation → Node` | none | |
| `ANNOTATES` | `Annotation → PipeSegment` | none | |
| `ANNOTATES` | `Annotation → PID` | none | Used for plant-level summary annotations (`esv_total`, `kav_total`, etc.) |
| `ANNOTATES` | `Annotation → Annotation` | none | Rarity annotation targeting a frequency annotation. |
| `SUPPORTED_BY` | `Annotation → Evidence` | none | |
| `ABOUT` | `Evidence → LogicalPipeSegment` | none | |
| `HAS_ANNOTATION` | `PID → AnnotationRequest` | none | Links drawing to flagged review requests. |
| `CONCERNS` | `AnnotationRequest → Node` | none | Links review request to the flagged node. |
| `HAS_PID` | `Skid → PID` | none | |
| `HAS_SKID` | `Plant → Skid` | none | |
| `CORPUS_OF` | `SkidCorpus → Skid` | none | |
| `STATISTICS_OF` | `GlobalStatistic → Plant` | none | |
| `SUMMARY_OF` | `GlobalStatisticsSummary → Plant` | none | |

> ⚠️ **`CONNECTED` does NOT exist** in the live database. The pipe adjacency relationship is called `PIPE`.

---

## VALID TRAVERSAL PATTERNS

```
(Arrow)-[:FLOW_EVIDENCE]->(LogicalPipeSegment)
(LogicalPipeSegment)-[:COVERS]->(PipeSegment)             -- always LPS->PS, never reversed
(Node)-[:ENDPOINT_OF]->(LogicalPipeSegment)
(PipeSegment)-[:ENDPOINT_OF]->(Node)
(Node)-[:PIPE]-(Node)                                     -- undirected, use - not ->
(PID)-[:CONTAINS]->(Node)
(PipeSegment)-[:CONTAINS]->(Node)
(Annotation)-[:ANNOTATES]->(LogicalPipeSegment)
(Annotation)-[:ANNOTATES]->(Node)
(Annotation)-[:ANNOTATES]->(PipeSegment)
(Annotation)-[:ANNOTATES]->(PID)
(Annotation)-[:ANNOTATES]->(Annotation)
(Annotation)-[:SUPPORTED_BY]->(Evidence)
(Evidence)-[:ABOUT]->(LogicalPipeSegment)
(Plant)-[:HAS_SKID]->(Skid)
(Skid)-[:HAS_PID]->(PID)
(PID)-[:HAS_ANNOTATION]->(AnnotationRequest)
(AnnotationRequest)-[:CONCERNS]->(Node)
(LogicalPipeSegment)-[:ADJACENT_VIA_NODES]->(LogicalPipeSegment)
(PipeSegment)-[:ADJACENT_VIA_NODES]->(PipeSegment)
(PipeSegment)-[:JOINS_AT]->(PipeSegment)
(SkidCorpus)-[:CORPUS_OF]->(Skid)
(GlobalStatistic)-[:STATISTICS_OF]->(Plant)
(GlobalStatisticsSummary)-[:SUMMARY_OF]->(Plant)
```
