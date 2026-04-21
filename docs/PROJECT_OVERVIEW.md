# PID-KOS: P&ID Knowledge & Orchestration System

## Complete Project Documentation

**Version**: 1.1  
**Date**: April 21, 2026  
**Author**: Arun Kumar — Calsoft Pvt Ltd

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [System Architecture](#2-system-architecture)
3. [Pipeline Phases (0–7)](#3-pipeline-phases-07)
4. [Engineering Rule Validation](#4-engineering-rule-validation)
5. [Flow Resolution FSM (Phase 4)](#5-flow-resolution-fsm-phase-4)
6. [Domain Knowledge System](#6-domain-knowledge-system)
7. [Cypher Query Registry (Phase 5)](#7-cypher-query-registry-phase-5)
8. [LLM Agent (Phase 8)](#8-llm-agent-phase-8)
9. [Web UI & API Layer](#9-web-ui--api-layer)
10. [Graph Schema Reference](#10-graph-schema-reference)
11. [Market Comparison](#11-market-comparison)
12. [CAD Integration Scenarios](#12-cad-integration-scenarios)
13. [RelationFormer + OCR Pipeline](#13-relationformer--ocr-pipeline)
14. [PID2Graph Synthetic Data Strategy](#14-pid2graph-synthetic-data-strategy)
15. [Roadmap & Future Work](#15-roadmap--future-work)

---

## 1. Executive Summary

PID-KOS is a **complete automated P&ID (Piping & Instrumentation Diagram) analysis platform** that:

1. **Ingests** GraphML P&ID drawings into a Neo4j graph database with a hierarchical Plant → Skid → PID structure
2. **Reconstructs** piping topology from raw geometry into pipe segments and logical pipe segments
3. **Determines** flow direction through evidence collection (arrows, equipment semantics, check valves, topology inference) and a finite state machine with BFS propagation
4. **Validates** 9 engineering rules at 3 severity levels (CRITICAL/HIGH/MEDIUM) against a domain-knowledge dictionary covering 4 skid types and 3 process conditions
5. **Detects** 30+ structural patterns (branches, dead-ends, orphans, cycles, parallel paths, pattern rarity)
6. **Provides** 333 pre-verified analytical Cypher queries across 17 categories
7. **Builds** deterministic reasoning traces for auditability
8. **Supports** human-in-the-loop review with approval workflows and cross-PID statistical normalization
9. **Exposes** a chatbot agent that classifies 15+ intent types and generates engineer-readable natural language answers backed by LLM explanation
10. **Serves** a web UI with drawing visualization, node highlighting, violation overlays, and interactive Q&A
11. **Provides** a standalone GraphML correction editor (port 8081) for admin patching of drawing topology live in Neo4j, with corrected GraphML export for pipeline re-ingestion

### Technology Stack

| Component | Technology |
|---|---|
| Graph Database | Neo4j (Bolt protocol) |
| Backend | Python 3.11+ |
| Web Server | Flask |
| LLM | Groq API (Llama/Mixtral) |
| Frontend | Vanilla HTML/JS (single-page) |
| GraphML Editor | Standalone Flask app (port 8081) + SVG canvas |
| Configuration | YAML + JSON |

---

## 2. System Architecture

### High-Level Pipeline

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   Phase 0    │────→│   Phase 1    │────→│   Phase 2    │────→│   Phase 3    │
│  Ingestion   │     │ Segmentation │     │Flow Evidence │     │  Annotation  │
│  (GraphML →  │     │(PipeSegment, │     │(Arrow→LPS    │     │(30+ patterns,│
│   Neo4j)     │     │ LPS, Equip.) │     │ binding)     │     │ eng. rules)  │
└──────────────┘     └──────────────┘     └──────────────┘     └──────────────┘
                                                                      │
       ┌──────────────────────────────────────────────────────────────┘
       ▼
┌──────────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   Phase 4    │────→│   Phase 5    │────→│   Phase 6    │────→│   Phase 7    │
│  FSM Flow    │     │Cypher Query  │     │  Reasoning   │     │ HITL Review  │
│  Resolution  │     │  Registry    │     │   Traces     │     │+ Corpus +    │
│              │     │ (333 qry)    │     │              │     │ Global Stats │
└──────────────┘     └──────────────┘     └──────────────┘     └──────────────┘
                                                                      │
       ┌──────────────────────────────────────────────────────────────┘
       ▼
┌──────────────────────────────────────────────────────────┐
│                    Phase 8 — LLM Agent                   │
│  IntentParser → IntentConfirmer → LogicalPlanBuilder     │
│  → HybridOptimizer → QueryRunner → NL Explainer         │
│                                                          │
│  Flask Server + Web UI (node highlighting, violations)   │
└──────────────────────────────────────────────────────────┘
```

### Data Hierarchy

```
Plant (PLANT_001)
  └── Skid (CONDENSATE_SKID, STEAM_SKID, ...)
        └── PID (PID_0, PID_2, ...)
              ├── Node (valve94, connector306, tank12, ...)
              ├── PipeSegment (PS_1, PS_57, ...)
              ├── LogicalPipeSegment (arrow102__crossing151, ...)
              ├── Annotation (engineering rules, structural patterns, ...)
              ├── Evidence (direction_frequency, ...)
              └── Equipment (instrumentation92, valve94, ...)
```

### Feedback Loops

| Code | Flow | Purpose |
|---|---|---|
| C11 | Phase 3 → Phase 4 | Seed confidence + safety-critical blocking |
| C12 | Phase 7 → Phase 3 | HITL decisions written back to Annotations |
| C19 | Global Stats → Phase 4 | Cross-skid rarity adjusts FSM seed confidence |

---

## 3. Pipeline Phases (0–7)

### Phase 0 — GraphML Ingestion

**Purpose**: Parse `.graphml` files exported from P&ID CAD tools, normalize node coordinates/labels, verify against ground truth, and load raw `Node` records into Neo4j.

**Key features**:
- Scoped per-PID with re-ingestion guards and cascade clearing
- Label normalization (draw.io `pump` → `tank`)
- Coordinate extraction from bbox geometry
- Plant → Skid → PID hierarchy creation

**Input**: `.graphml` file + PID image (PNG)  
**Output**: Raw `Node` records in Neo4j with `CONNECTED` edges

---

### Phase 1 — Structural Reconstruction

**Purpose**: Group edges into `PipeSegment` records, classify nodes structurally, infer equipment labels, and build `LogicalPipeSegment` (LPS) topology.

**Key features**:
- Node classification: `CONNECTOR` (degree=2 pipe intermediates), `SYMBOL` (drawn symbols)
  Note: `BOUNDARY`/`background` nodes are **filtered at Phase 0** and never loaded into Neo4j.
- Equipment label inference: small "general" nodes → `inferred_check_valve`; small tanks → `functional_label='pump'`; `functional_label='heat_exchanger'` also possible
- `PipeSegment` construction with `CONTAINS`, `ADJACENT_VIA_NODES`, `JOINS_AT` relationships
- `LogicalPipeSegment` collapsing with endpoint extraction
- WCC (Weakly Connected Component) computation
  Note: There is **no** separate `Equipment` node — flow properties are denormalised onto `Node` directly by Phase 4.

**Input**: Raw Neo4j graph from Phase 0  
**Output**: Fully structured topology with PipeSegments and LPS; Node records carry structural classification

---

### Phase 2 — Flow Evidence Generation

**Purpose**: Bind arrow symbols to LogicalPipeSegments using bbox geometry alignment vectors, persist `FLOW_EVIDENCE` relationships.

**Key features**:
- Arrow-to-LPS spatial matching via bbox center coordinates and direction vectors
- Cosine alignment scoring
- Does NOT assign final flow direction — only collects directional evidence
- Creates `FLOW_EVIDENCE` relationships (Arrow → LPS) with confidence, dx, dy, direction_hint

**Input**: Arrow nodes + LPS topology from Phase 1  
**Output**: `Evidence` nodes with `FLOW_EVIDENCE` and `ABOUT` relationships

---

### Phase 3 — Evidence Annotation & Pattern Detection

**Purpose**: The main analytical phase — lifts evidence, detects patterns, validates engineering rules, computes rarity scores.

**Sub-phases**:

| Sub-phase | What it does |
|---|---|
| 3.1 Flow evidence lifting | Creates `Evidence` and `Annotation` nodes from Phase 2 data |
| 3.2 Equipment-based flow inference | Pump/compressor flow evidence (R4), check valve evidence (R6/R6b), dead-end inference (R5) |
| 3.3 Direction-frequency summaries | Aggregates evidence per LPS, computes seed confidence |
| 3.4 Structural pattern detection | 30+ patterns: orphans, endpoint mismatches, duplicate symbols, motif chains, degree outliers, rare patterns |
| 3.5 Engineering rule validation | 9 engineering rules at 3 severity levels (see Section 4) |
| 3.6 Frequency aggregation | Cross-pattern frequency analysis, rarity scoring |

**30+ Structural Patterns Detected**:

| Pattern | Target | Meaning |
|---|---|---|
| `orphan_node` | Node | No pipe connections |
| `endpoint_count_mismatch` | PipeSegment | Unexpected endpoint count |
| `endpoint_collision` | Node | Overlapping pipe ends |
| `pipe_segment_no_logical_mapping` | PipeSegment | Disconnected pipe stub |
| `dead_end_pipe_segment` | PipeSegment | Open-ended pipe stub |
| `identical_ps_neighborhood` | Node | Same neighborhood as another node |
| `duplicate_symbol_candidate` | Node | Likely duplicate symbol |
| `motif_ps_node_chain` | Node | Repeating structural motif |
| `degree_outlier` | Node | Unusually high/low connectivity |
| `rare_motif_local` | PipeSegment | Rare local structural pattern |
| `structural_pattern_rarity` | Annotation | Rarity score for pattern |
| `direction_frequency_summary` | LPS | Flow direction frequency summary |
| `direction_conflict_observed` | LPS | Conflicting arrows on same segment |
| `logical_no_evidence` | LPS | No flow evidence on segment |
| ... | ... | (and more) |

**Input**: Phase 1-2 topology + evidence  
**Output**: `Annotation` nodes linked via `ANNOTATES` → target, `SUPPORTED_BY` → Evidence

---

### Phase 4 — Flow Resolution FSM

**Purpose**: Resolve definitive flow direction across the entire piping network using a finite state machine with BFS propagation.

See [Section 5](#5-flow-resolution-fsm-phase-4) for full details.

---

### Phase 5 — Cypher Query Registry

**Purpose**: Build a static registry of all analytical Cypher queries across 17 categories. Validate each file is atomic and contains a `RETURN` clause. The registry is the authority for the chatbot agent.

**Key features**:
- Scans `engine/phase5_cypher/` for `.cypher` files organized by category
- Validates query syntax (atomic, has RETURN)
- Builds `_meta/queries.json` registry file
- 333 queries across 17 categories (see Section 7)

**Input**: `.cypher` files in categorized folders  
**Output**: `_meta/queries.json` registry, PHASE5_COMPLETE status

---

### Phase 6 — Reasoning Trace Generation

**Purpose**: Execute all verified Phase 5 queries through `Phase5Adapter`, build per-category reasoning traces.

**Key features**:
- Groups queries by trace category
- Uses Phase5Adapter to execute against Neo4j
- Builds `TraceBuilder` per category
- Writes trace JSON files to `engine/phase6_trace/traces/`
- Deterministic: same graph → same trace output

**Input**: Phase 5 query registry  
**Output**: Per-category trace JSON files, PHASE6_COMPLETE status

---

### Phase 7 — Human-in-the-Loop + Corpus + Global Statistics

**Purpose**: Present violations and high-severity annotations for human review, build cross-PID statistical models.

**Three sub-systems**:

#### 7a. HITL Approval Workflow
- Builds queue from: engineering rule violations + HIGH/CRITICAL rarity annotations
- Each `HitlItem` has: item_id, annotation_type, severity, node_id, label, explanation
- Actions: `approve()`, `reject(reason)`, `auto_approve_all()`
- Writes `hitl_status`, `reviewed_by`, `review_note`, `reviewed_at` back to Annotation nodes in Neo4j
- Supports `--auto-approve` CLI flag for batch processing

#### 7b. Per-Skid Corpus (Cross-PID Normalization)
- Collects ESV (Equipment-StructuralType-Via) frequencies across all PIDs in a Skid
- Computes percentile ranks per ESV pattern
- Creates `SkidCorpus` node linked via `CORPUS_OF` → Skid
- Sets `corpus_normalized=true` on processed Annotations
- Percentile tiers: ≤5% → `corpus_rare`, ≤25% → `corpus_uncommon`, ≤75% → `corpus_typical`, ≤95% → `corpus_common`, >95% → `corpus_dominant`
- Requires ≥2 PIDs in a Skid to produce meaningful percentiles

#### 7c. Global Statistical Knowledge Layer
- Aggregates ESV patterns across all Skids in a Plant
- Creates `GlobalStatistic` nodes per ESV pattern linked via `STATISTICS_OF` → Plant
- Creates `GlobalStatisticsSummary` node linked via `SUMMARY_OF` → Plant
- Global rarity tiers: ≤2 → `globally_absent`, ≤5 → `globally_rare`, ≤50 → `globally_typical`, ≤100 → `globally_common`, >100 → `globally_dominant`
  Note: `globally_uncommon` does **not** appear in the live database.
- Fed back into Phase 4 FSM Step 0c (C19 feedback loop)

---

## 4. Engineering Rule Validation

### All 9 Violation Types

| # | Pattern Type | Severity | Description |
|---|---|---|---|
| 1 | `missing_check_valve` | **CRITICAL** | Pump has no check valve downstream — backflow risk |
| 2 | `missing_pressure_relief_valve` | **CRITICAL** | Pressure vessel has no relief valve — overpressure protection missing |
| 3 | `missing_warming_coil` | **CRITICAL** | Equipment in cryogenic service has no warming coil — seal ice-up risk |
| 4 | `missing_cooling_jacket` | **CRITICAL** | Equipment in high-temperature service has no cooling jacket — bearing damage risk |
| 5 | `missing_isolation_valve` | **HIGH** | Component has no isolation valve — cannot be taken out of service safely |
| 6 | `tank_vent_position_violation` | **HIGH** | Tank vent is not at the highest point — atmospheric equalization may fail |
| 7 | `control_valve_after_orifice` | **HIGH** | Control valve downstream of orifice plate — disturbs flow measurement |
| 8 | `missing_suction_strainer` | **MEDIUM** | Pump has no suction strainer upstream — debris risk |
| 9 | `tank_drain_position_violation` | **MEDIUM** | Tank drain is not at the lowest point — tank may not drain completely |

### Validation Logic

- **Downstream/upstream checks**: Traverses `ADJACENT_VIA_NODES` with configurable `max_hops`, using spatial position filtering based on bbox center coordinates to distinguish upstream from downstream
- **Spatial constraint checks**: Validates physical position of vents (highest point) and drains (lowest point) relative to tank bbox
- **4-level semantic resolution**: Universal rules → Skid type rules → Process condition overrides → PID-specific custom rules
- The 4 CRITICAL violations block FSM propagation in Phase 4 (`phase4_blocked=true`)

### Impact on Pipeline

| Severity | Phase 4 Impact | HITL Queue |
|---|---|---|
| CRITICAL | Blocks BFS propagation on connected LPS | Auto-queued for review |
| HIGH | No propagation blocking | Auto-queued for review |
| MEDIUM | No propagation blocking | Not auto-queued |

---

## 5. Flow Resolution FSM (Phase 4)

### FSM States

| State | Meaning |
|---|---|
| `SEEDED` | Directional vote from Evidence ≥ threshold |
| `SEEDED_UNKNOWN` | Evidence present but vote too weak to resolve |
| `HITL_PENDING` | Conflict annotation with `resolution_rule='hitl_required'` |
| `PROPAGATED` | Reached by BFS from a SEEDED neighbor |
| `BLOCKED` | Structural flaw or safety-critical rule violation |
| `UNKNOWN` | No evidence and not reachable from any seed |

### Configuration

| Parameter | Value | Purpose |
|---|---|---|
| `DECAY` | 0.8 | Confidence decay per BFS hop |
| `BRANCH_DECAY` | 0.85 | Additional decay at conflict/branch nodes |
| `MIN_CONFIDENCE` | 0.05 | BFS stops below this threshold |
| `MAX_ITERATIONS` | 100 | Maximum BFS propagation iterations |
| `UNCERTAIN_THR` | 0.40 | Below this, evidence vote is uncertain |

### Processing Steps

```
Step 0a: Pre-flight — stamp phase4_blocked from structural rarity patterns
                      (propagation_blocked=true)

Step 0b: Pre-flight — stamp phase4_blocked on LPS connected to equipment
                      with CRITICAL safety violations (missing check valve,
                      pressure relief, warming coil, cooling jacket)

Step 0c: Pre-flight — consult GlobalStatistic nodes
                      globally_rare/absent → seed_confidence × 1.25
                      globally_dominant → seed_confidence × 0.85

Step 1:  Reset — clear all prior flow state

Step 2:  Seeding — weighted vote over all Evidence per LPS
                   FORWARD = +1, REVERSE = −1
                   Uses seed_confidence from Phase 3

Step 3:  BFS Propagation — traverse ADJACENT_VIA_NODES
                          confidence decays by DECAY per hop
                          BRANCH_DECAY at conflict nodes
                          Stops at MIN_CONFIDENCE or MAX_ITERATIONS

Step 4:  Mark Remaining — unresolved blocked LPS → BLOCKED
                         unreachable → UNKNOWN

Step 5:  Equipment flow stamping — flow_state, flow_direction, flow_confidence
                             written to Node records (label IN ['tank','valve','instrumentation','general','inlet/outlet'])
                             There is no separate Equipment node.
```

---

## 6. Domain Knowledge System

### Symbol Dictionary

#### Universal Equipment

| Equipment | Function | Creates Flow? | Safety Critical? | Evidence Confidence |
|---|---|---|---|---|
| `pump` | Pressure increase | Yes (unidirectional) | Yes | 0.80 |
| `centrifugal_pump` | Centrifugal pressure increase | Yes | Yes | 0.80 |
| `compressor` | Gas pressure increase | Yes | Yes | 0.80 |
| `ejector` | Vacuum/mixing | Yes | No | 0.75 |
| `blower` | Air movement | Yes | No | 0.75 |
| `fan` | Air circulation | Yes | No | 0.70 |
| `tank` | Storage (bidirectional) | No | Yes | — |
| `check_valve` / `nrv` / `non_return_valve` | Backflow prevention | No (unidirectional) | Yes | 0.80–0.85 |
| `inferred_check_valve` | Backflow (inferred label) | No | Yes | 0.70 |
| `valve` | Flow isolation (bidirectional) | No | No | — |
| `control_valve` | Flow regulation | No | No | — |
| `orifice_plate` | Flow measurement | No | No | — |
| `inlet/outlet` | System boundary | No | No | — |

### Skid-Specific Contexts

| Skid Type | Description | Key Equipment Rules |
|---|---|---|
| **CONDENSATE** | Atmospheric condensate collection/return | Pump: check valve (5 hops, CRITICAL), isolation valve (8 hops, HIGH), suction strainer (3 hops, MEDIUM). Tank: vent/drain spatial + level instrument |
| **STEAM** | High-pressure steam generation/distribution | Tank: safety relief valve at highest point (CRITICAL), pressure gauge (HIGH), level instrument (CRITICAL) |
| **CHEMICAL_REACTOR** | High-pressure chemical processing | Pump: check valve (3 hops), pressure relief valve (5 hops), all CRITICAL. Tank: ASME §VIII relief valve + rupture disk |
| **COOLING_WATER** | Recirculating cooling water systems | Pump: check valve (4 hops, HIGH). Tank: overflow + makeup water connections |

### Process Condition Overrides

| Condition | Applies To | Additional Requirements |
|---|---|---|
| **CRYOGENIC** (<−100°C) | CHEMICAL_REACTOR, CONDENSATE | Pump: warming coil (CRITICAL). Tank: pressure building coil (CRITICAL) |
| **HIGH_TEMPERATURE** (>300°C) | CHEMICAL_REACTOR, STEAM | Pump: cooling jacket (CRITICAL) |
| **CORROSIVE** | CHEMICAL_REACTOR | Pump: flushing connection (HIGH) |

### Semantic Override System (4-Level Hierarchy)

```
Priority 1 (highest): PID.skid_type_override     — user-set per PID
Priority 2:           PID.process_conditions      — process-specific modifiers
Priority 3:           Skid.skid_type              — default from registration
Priority 4 (lowest):  Universal base              — UNIVERSAL_EQUIPMENT dictionary
```

**Key capabilities**:
- `get_pid_semantics()`: Resolves full 4-level hierarchy
- `set_pid_semantics()`: Sets PID-specific overrides with audit trail
- `revalidate_pid_semantics()`: Re-runs Phase 3.5 validation in ~3 seconds (vs ~180s full pipeline)

---

## 7. Cypher Query Registry (Phase 5)

### Query Categories

| Category | # Queries | Description |
|---|---|---|
| **annotations** | 45 | Annotation requests, ESV/KAV patterns, severity breakdown |
| **cross_domain** | 15 | Multi-domain queries: valves + flow + annotations together |
| **directionality** | 19 | Arrow coverage, orphan arrows, flow direction analysis |
| **engineering_correctness** | 28 | Rule violations, HITL status, pending reviews |
| **equipment_semantics** | 10 | Equipment classification, functional labels |
| **external** | 16 | Boundary nodes, inlet/outlet connections, interface count |
| **flow_coverage** | 12 | Flow direction observations, LPS evidence completeness |
| **flow_nodes** | 10 | Node-level flow state and direction |
| **instruments** | 19 | Instrument inventory, attachment, evidence-supported |
| **inventory** | 19 | Equipment inventory, unconnected equipment |
| **lines** | 35 | Pipe segments, LPS, flow state breakdown |
| **pipe_edges** | 8 | PIPE edge queries, symbol connections |
| **quality** | 26 | Structural anomalies, orphans, junction analysis |
| **reachability** | 17 | Isolated components, connected network queries |
| **redundancy** | 14 | Pattern frequency, rarity scoring, motif chains |
| **topology** | 21 | Equipment paths, series/parallel, degree analysis |
| **valves** | 19 | Valve inventory, flow direction, connections |

**Total: 333 verified Cypher queries**

---

## 8. LLM Agent (Phase 8)

### Architecture

5-layer deterministic QA pipeline:

```
User question
     │
     ▼
┌─────────────────┐
│  IntentParser    │  Keyword-based extraction (zero latency)
└────────┬────────┘
         ▼
┌─────────────────┐
│ IntentConfirmer  │  LLM reclassification (only for unknown_intent)
└────────┬────────┘
         ▼
┌─────────────────┐
│LogicalPlanBuilder│  Registry-locked query selection
└────────┬────────┘
         ▼
┌─────────────────┐
│HybridOptimizer   │  Cypher resolution (template → schema generator → registry fallback)
└────────┬────────┘
         ▼
┌─────────────────┐
│ QueryRunner →    │  Execute Cypher, build trace, generate NL explanation
│ TraceBuilder →   │  (LLM-powered with SimpleExplainer fallback)
│ NL Explainer     │
└─────────────────┘
```

### Cross-cutting Components

| Component | Purpose |
|---|---|
| `QueryLogger` | Logs all queries with intent, cypher, records, timestamps |
| `AmbiguityResolver` | LLM auto-resolution when question matches multiple intents |
| `GraphTraceTools` | PIPE-based connectivity traversal for topology queries |
| `CypherValidator` | Validates generated Cypher against schema before execution |

### Intent Types

| Intent Type | Domain |
|---|---|
| `valve_placement` | Valve queries (count, list, connections, placement) |
| `instrument_attachment` | Instrument queries (attached, lines, host equipment) |
| `engineering_inventory` | Equipment inventory (tanks, pumps, vessels) |
| `line_attributes` | Pipe/segment queries (LPS attributes, adjacency) |
| `flow_direction` | Flow direction queries (arrows, evidence, upstream/downstream) |
| `flow_coverage` | Analysis completeness (coverage %, gaps, unresolved) |
| `drawing_consistency` | Quality checks (orphans, dangling ends, defects) |
| `connectivity_topology` | Graph connectivity (paths, degree, reachability) |
| `isolation_reachability` | Component isolation, islands, unreachable equipment |
| `external_interfaces` | Drawing boundary connections |
| `redundancy_patterns` | Structural redundancy, rarity, duplicates |
| `engineering_correctness` | Topology conformance (do all tanks have instruments?) |
| `annotation_requests` | Open annotation requests, quality reports |
| `cross_domain` | Multi-domain queries, ESV/KAV triage, severity |
| `segment_junction_topology` | Junction/crossing/JOINS_AT topology |
| `unknown_intent` | Unrecognized — routed to LLM IntentConfirmer |

---

## 9. Web UI & API Layer

### API Endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `/` | GET | Serves the UI (`ui/index.html`) |
| `/api/pids` | GET | Lists all available PID IDs and the active PID |
| `/api/pid` | POST | Sets the active PID for the session |
| `/api/image/<pid_id>` | GET | Serves the P&ID drawing image (PNG) |
| `/api/nodes/<pid_id>` | GET | Returns all nodes with coordinates, labels, functional labels, violation data |
| `/api/violations/<pid_id>` | GET | Phase 3.5 violations summary (total, by severity, by pattern, HITL status) |
| `/api/cache/clear` | POST | Clears the server-side node cache |
| `/api/query` | POST | Main chatbot endpoint — question → answer + highlights + context |

### Query Response Format

```json
{
    "answer":       "Sanitized natural-language answer",
    "intent":       "valve_placement",
    "strategy":     "registry_match",
    "cypher":       "MATCH (n:Node)...",
    "records":      [{"node_id": "valve94", ...}],
    "highlight":    {"nodes": ["valve94"], "labels": ["valve"]},
    "node_context": {"valve94": {"reason": "...", "severity": "CRITICAL"}}
}
```

### Violations Response Format

```json
{
    "total": 17,
    "by_severity": {"CRITICAL": 10, "HIGH": 5, "MEDIUM": 2},
    "by_pattern": {"missing_check_valve": 5, ...},
    "violations": [
        {
            "node_id": "valve94", "label": "valve",
            "functional_label": null,
            "issue_type": "missing_check_valve",
            "severity": "CRITICAL",
            "explanation": "Pump has no check valve downstream",
            "skid_type": "CONDENSATE",
            "hitl_status": "approved",
            "reviewed_by": "auto"
        }
    ]
}
```

### GraphML Correction Editor (port 8081)

A standalone admin tool for correcting drawing topology errors discovered during analysis. Runs independently of the main chatbot server.

**Server**: `editor_server.py` — Flask app on port 8081, serves `ui/editor.html`

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/pids` | GET | Lists available PID IDs |
| `/api/image/<pid_id>` | GET | Serves the P&ID drawing image |
| `/api/nodes/<pid_id>` | GET | All node positions and labels |
| `/api/edges/<pid_id>` | GET | All PIPE/CONNECTED edges |
| `/api/node_props/<pid_id>/<node_id>` | GET | Full Neo4j properties for a node |
| `/api/patches/<pid_id>` | GET | Patch history for a PID |
| `/api/patch` | POST | Apply a new patch (add/remove edge, set property) |
| `/api/patch/<pid_id>/<patch_id>` | DELETE | Revert a specific patch |
| `/api/graphml/<pid_id>` | GET | Download corrected GraphML for re-ingestion |

**Editor UI features** (`ui/editor.html`):
- Three interaction modes: **SELECT** (inspect/edit properties), **CONNECT** (draw PIPE edges), **ERASE** (remove edges)
- Zoom/pan canvas with scroll wheel and middle-drag; +/−/⊞ buttons
- Node hover tooltips with label and node ID
- "Connect by Node ID" panel with autocomplete for micro-connections
- All changes patched live into Neo4j AND saved to `patches/{pid_id}_patches.json`
- "⬇ CORRECTED GRAPHML" downloads patched GraphML for Phase 0 re-ingestion
- Completely isolated: zero imports from `server.py`, `agent/`, or `engine/`

---

## 10. Graph Schema Reference

### Node Labels

| Label | structural_type | degree | Meaning |
|---|---|---|---|
| `connector` | CONNECTOR | always 2 | Pipe path intermediate |
| `background` | BOUNDARY | always 0 | Isolated noise (NOT an external interface) |
| `tank` | SYMBOL | 4–12 | Process vessel (storage, heater, filter, pump) |
| `valve` | SYMBOL | 1–3 | Control or isolation valve |
| `instrumentation` | SYMBOL | 0–2 | Instrument symbol (FT, LT, TE, PSV) |
| `general` | SYMBOL | 0–3 | Unclassified symbol (nozzle, reducer, fitting) |
| `arrow` | SYMBOL | always 2 | Flow direction arrow |
| `crossing` | SYMBOL | 1–3 | Pipe crossing or junction point |
| `inlet/outlet` | SYMBOL | always 1 | External system connection |

### New Node Labels (Phase 7)

| Label | Purpose | Relationship |
|---|---|---|
| `SkidCorpus` | Cross-PID ESV normalization corpus | `CORPUS_OF` → Skid |
| `GlobalStatistic` | Cross-skid ESV pattern statistics | `STATISTICS_OF` → Plant |
| `GlobalStatisticsSummary` | Plant-level statistical summary | `SUMMARY_OF` → Plant |

### Relationship Types

| Relationship | Properties | Direction |
|---|---|---|
| `CONNECTED` | `edge_label`, `source` | Node ↔ Node (undirected) |
| `ENDPOINT_OF` | `endpoint_type`, `source` | Node → LPS |
| `FLOW_EVIDENCE` | direction_hint, confidence, cosine, dx, dy, source | Arrow → LPS |
| `COVERS` | `via_node`, `source` | LPS → PipeSegment |
| `ADJACENT_VIA_NODES` | `via_nodes`, `via_count` | PipeSegment ↔ PipeSegment |
| `JOINS_AT` | `kind`, `trace_nodes` | PipeSegment → PipeSegment |
| `ANNOTATES` | — | Annotation → target |
| `CONTAINS` | — | PipeSegment/PID → Node/Equipment |
| `SUPPORTED_BY` | — | Annotation → Evidence |
| `ABOUT` | — | Evidence → LPS |
| `HAS_PID` | — | Skid → PID |
| `HAS_SKID` | — | Plant → Skid |
| `CORPUS_OF` | — | SkidCorpus → Skid |
| `STATISTICS_OF` | — | GlobalStatistic → Plant |
| `SUMMARY_OF` | — | GlobalStatisticsSummary → Plant |

---

## 11. Market Comparison

### Competitive Landscape

| Category | Key Players | What They Do | Price Range |
|---|---|---|---|
| **Intelligent P&ID Platforms** | AVEVA E3D, Hexagon Smart P&ID, Bentley OpenPlant, AutoCAD Plant 3D | Native CAD authoring + rule-based validation | $15K–$80K/seat/year |
| **AI P&ID Digitization** | Aize, I2V, Detect Technologies, Yokogawa AI P&ID | OCR + ML to extract tags, line numbers, equipment from scanned P&IDs | $50K–$500K/project |
| **HAZOP/Safety Tools** | PHA-Pro (Sphera), PHAWorks, HAZOP Manager | Structured HAZOP/LOPA worksheets, no drawing integration | $5K–$30K/seat |
| **Digital Twins** | AspenTech, COMOS (Siemens), Honeywell Forge, AVEVA NET | Full lifecycle data management | $100K–$1M+ enterprise |

### Feature-by-Feature Comparison

| Capability | AVEVA/Hexagon | AI Digitizers | HAZOP Tools | **PID-KOS** |
|---|---|---|---|---|
| Input format | Native CAD | Scanned PDF/raster | Manual entry | GraphML (future: CAD + image) |
| Symbol recognition | Built-in | ML-based OCR | N/A | Pre-labeled (future: RelationFormer) |
| Tag name extraction | Yes (native) | Yes (OCR + ML) | Manual | Not yet (future: OCR) |
| Topology reconstruction | Yes (native) | Partial | No | **Yes** |
| Flow direction resolution | Manual | No | No | **Yes** (automated FSM) |
| Engineering rule validation | Configurable | No | Manual checklist | **Yes** (9 rules, 3 severities) |
| Structural pattern detection | Limited | No | No | **Yes** (30+ patterns) |
| Natural language querying | No | No | No | **Yes** (15+ intent types) |
| Graph-based reasoning | No (SQL) | No | No | **Yes** (Neo4j + 333 Cypher queries) |
| Cross-drawing analysis | Yes (full model) | Limited | No | Partial (corpus + global stats) |
| HITL approval workflow | Yes | No | Yes | **Yes** |
| Setup cost | $15K–$80K/seat | $50K–$500K | $5K–$30K | **Near zero** (OSS stack) |

### Unique Differentiators

1. **Automated flow direction resolution** — No commercial tool automates this. AVEVA/Hexagon require manual assignment.
2. **Graph-based structural analysis** — Neo4j traversals give reachability, isolation, path-finding queries that are extremely awkward in SQL.
3. **Natural language interface** — No P&ID tool has a chatbot answering "which pumps are missing check valves?" in plain English.
4. **Skid-type-aware semantic rules** — 4-level override hierarchy with 3-second revalidation, more flexible than commercial static rule engines.

### Market Positioning

```
Drawing Checker ←─── PID-KOS ───→ Design Review Automation
(geometry only)   (structural     (full tag-aware)
                   + semantic)
     ↑                                    ↑
 AutoCAD rules                     AVEVA/Hexagon
```

PID-KOS is a **quality assurance overlay** — not a replacement for CAD tools. It catches the 80% of routine checks that consume review hours.

---

## 12. CAD Integration Scenarios

### Three Input Scenarios

#### Scenario 1: Vanilla AutoCAD DWG/DXF ("Dumb" CAD)

Just vector geometry — no intelligence.

```
DWG/DXF → Convert to image → RelationFormer + OCR → Phase 0b → Pipeline
```

Same as scanned images but cleaner lines and crisper text.

#### Scenario 2: Semi-Intelligent CAD (AutoCAD Plant 3D, Visio)

Tagged blocks with attributes — the sweet spot.

```
Plant 3D DWG → Extract block attributes + connectivity → Phase 0c → Neo4j → Pipeline
```

| CAD Attribute | Maps To |
|---|---|
| Block name ("VALVE_GATE_2WAY") | `Node.label = 'valve'` + `Node.tag_name` |
| Block insertion point | `Node.bbox` |
| TAG, SERVICE, LINE_NO | `Node.tag_name`, `Node.service`, `LPS.line_number` |
| Pipe polylines | `CONNECTED` edges |
| Instrument attributes | `Node.instrument_type`, `Node.range`, `Node.setpoint` |

No ML required — structured data in, structured data out.

#### Scenario 3: Intelligent P&ID (AVEVA, Hexagon SmartPlant)

Full engineering databases. **Skip Phases 1-2 entirely.**

```
SmartPlant XML / AVEVA export → Direct schema mapping → Phase 0d → Neo4j → Phase 3-7 only
```

Phases 3-7 still add value: engineering rule validation, flow direction for unannotated pipes, analytical queries, reasoning traces, NL querying.

### Multi-Format Ingestion Architecture

```
                    ┌─────────────────┐
Scanned PDF/Image → │ RelationFormer  │──┐
                    │ + OCR           │  │
                    └─────────────────┘  │
                                         │   ┌──────────────┐
GraphML (draw.io/yEd) ──────────────────┼──→│   Phase 0    │──→ Phase 1-7
                                         │   │  (Unified     │
AutoCAD Plant 3D DWG ──── CAD Parser ──┼──→│   Ingestion)  │
                                         │   └──────────────┘
AVEVA/SmartPlant XML ── Schema Mapper ──┘
```

---

## 13. RelationFormer + OCR Pipeline

### Architecture

```
Raw P&ID Image (scanned PDF / PNG / TIFF)
       │
       ▼
┌─────────────────────────────┐
│  RelationFormer             │ → Symbol detection + relationship prediction
│  (object detection +        │    (bounding boxes, classes, connectivity)
│   relationship prediction)  │
├─────────────────────────────┤
│  OCR Pipeline               │ → Tag names (FT-101, LV-201, 4"-CW-101)
│  (text detection +          │    Line numbers, equipment IDs
│   text recognition +        │    Spec break annotations
│   tag association)          │
└─────────────────────────────┘
       │
       ▼
Phase 0b (Ingestion — adapted for RF+OCR output)
       │
       ▼
Phase 1-7 (Analysis — now with tag-aware rules)
```

### Feasibility Assessment

| Challenge | Difficulty | Feasible? | Confidence |
|---|---|---|---|
| Symbol detection | Medium | **Yes** | 90% — well-proven with DETR/YOLO |
| Image patching | Easy | **Yes** | 95% — solved problem (DOTA approach) |
| Per-patch GraphML output | Easy | **Yes** | 90% — straightforward mapping |
| Pipe connectivity / edge formation | **Hard** | **Partially** | 60-70% — open research problem |
| Patch merging | Medium | **Yes** | 85% — standard NMS + stitching |
| Training data | **Hard** | **Conditionally** | Depends on annotated P&ID access |
| OCR / tag extraction | Medium | **Yes** | 85% — PaddleOCR/DocTR/TrOCR |

### Key Technical Risks

1. **Pipe connectivity across patches** — RelationFormer predicts local relationships well but cannot reason about pipes spanning 10+ patches. Mitigations: line segment detection (LSD/LETR), Phase 1 segmentation as post-processing, border-node stitching.

2. **Training data scarcity** — Requires 500+ annotated P&IDs. Mitigated by PID2Graph dataset (see Section 14).

3. **Crossing vs. connected pipes** — Visually ambiguous without crossing symbol detection or line geometry tracing.

### How Existing Pipeline Mitigates ML Errors

The Phase 1-7 pipeline acts as a **safety net** for imperfect digitization:
- Phase 1 catches structural anomalies from detection errors
- Phase 3 flags orphan nodes, endpoint mismatches, disconnected stubs
- Phase 4 FSM's confidence decay handles uncertain connectivity
- Phase 7 HITL puts detection errors in front of humans for correction

An **80% accurate digitizer** becomes a **95%+ accurate system** with this pipeline.

### New Engineering Rules Enabled by OCR

| Rule | Severity | Requires |
|---|---|---|
| `instrument_loop_incomplete` | HIGH | Tag names (ISA S5.1 loop check) |
| `tag_numbering_gap` | MEDIUM | Sequential tag extraction |
| `line_number_mismatch` | HIGH | Line number → service inference |
| `spec_break_missing_valve` | CRITICAL | Line spec parsing |
| `duplicate_tag` | HIGH | Full tag extraction |
| `tag_format_violation` | MEDIUM | Company naming convention |

---

## 14. PID2Graph Synthetic Data Strategy

### The Dataset

**PID2Graph** (Zenodo DOI: 10.5281/zenodo.14803338)

| Metric | Value |
|---|---|
| Size | 9.3 GB |
| Complete P&IDs | 500+ full drawings |
| Format | PNG image + paired GraphML ground truth |
| Patched versions | Pre-cut patches with overlap + per-patch GraphML with border-nodes |
| Sources | 3 sub-datasets: Dataset PID (Digitize-PID), OPEN100 (nuclear reactor), Synthetic |
| License | CC BY-SA 4.0 (commercial use allowed) |
| Paper | IEEE DSAA 2025 — "From Engineering Diagrams to Graphs: Digitizing P&IDs with Transformers" |
| Origin | DLR (German Aerospace Center) |

### Why It Fits

1. **Same GraphML format** — Nodes with bboxes + labels, edges with labels, connector nodes. Compatible with existing Phase 0 ingestion.
2. **Pre-patched with overlaps** — Ready for RelationFormer training without custom patching pipeline.
3. **Border-node annotations** — Teaches the model about patch-boundary stitching.
4. **500+ P&IDs** — Sufficient for solid pre-training (90-93% symbol detection, 80-85% connectivity).
5. **3 source domains** — Provides style diversity (real industrial, nuclear, synthetic).

### Recommended Training Strategy

```
Step 1: Pre-train on PID2Graph (all 500+)
        ├── Symbol detection (DETR/YOLO head)
        ├── Relationship prediction (RelationFormer head)
        └── Patch border stitching (border-node prediction)

Step 2: Validate on held-out PID2Graph split (80/20)
        └── Measure: symbol mAP, connectivity F1, stitching accuracy

Step 3: Feed output GraphML into Phase 0-7 pipeline
        └── Phase 3 anomaly detection catches detection errors
        └── This tells you WHERE the model fails

Step 4: Fine-tune on client data (50-100 annotated P&IDs)
        └── Active learning: model pre-annotates, human corrects
        └── 2-3 rounds → production quality for that client

Step 5: Add OCR head (separate or joint)
        └── Use ICDAR / SROIE / DocTR datasets for text detection pre-training
        └── Fine-tune text association on client P&IDs
```

### Expected Performance

| Training Data Size | Symbol Detection mAP | Connectivity F1 |
|---|---|---|
| 50 P&IDs | 70-80% | 60-70% |
| 200 P&IDs | 85-90% | 75-80% |
| **500 P&IDs (PID2Graph)** | **90-93%** | **80-85%** |
| 500 + 100 fine-tuned | 93-95% | 85-90% |

---

## 15. Roadmap & Future Work

### Near-Term (Implemented)

- [x] Phase 0-4: Full pipeline (ingestion → flow resolution)
- [x] Phase 5: Cypher query registry (333 queries, 17 categories)
- [x] Phase 6: Reasoning trace generation
- [x] Phase 7: HITL + corpus + global statistics
- [x] Phase 8: LLM agent (15+ intents, NL explanation)
- [x] Web UI with violation overlays and node highlighting
- [x] Standalone GraphML correction editor (port 8081) with live Neo4j patching
- [x] 9 engineering rules at 3 severity levels
- [x] 4-level semantic override system
- [x] Cross-PID statistical normalization

### Medium-Term (Planned)

- [ ] RelationFormer pre-training on PID2Graph dataset
- [ ] OCR pipeline for tag name / line number extraction
- [ ] Phase 0b: Image → GraphML ingestion adapter
- [ ] Phase 0c: AutoCAD Plant 3D DWG parser
- [ ] Tag-aware engineering rules (ISA S5.1 loop checks, spec break validation)
- [ ] Multi-drawing pipe continuation (cross-PID piping)
- [ ] Regulatory compliance report templates (ASME, API, NFPA)

### Long-Term (Vision)

- [ ] Phase 0d: AVEVA / Hexagon SmartPlant XML adapter
- [ ] Active learning loop (model pre-annotates → human corrects → retrain)
- [ ] Multi-user deployment with role-based access
- [ ] Integration with HAZOP tools (PHA-Pro export)
- [ ] 3D model linking (P&ID → 3D model cross-reference)
- [ ] Client-specific fine-tuning pipeline (50-100 drawings → production model)

---

## Appendix A: Project Structure

```
Chatbot/
├── server.py                          # Flask chatbot server + API endpoints (port 8080)
├── editor_server.py                   # Standalone GraphML correction editor (port 8081)
├── requirements.txt                   # Python dependencies (pinned)
├── pyproject.toml                     # Project metadata
├── config/
│   ├── neo4j.yaml.example             # Neo4j connection config template
│   └── storage.yaml.example           # File storage paths template
├── agent/
│   ├── groq.env.example               # LLM API key template
│   ├── agent.py                       # Main agent orchestrator
│   ├── intent_parser.py               # Keyword-based intent extraction
│   ├── intent_confirmer.py            # LLM intent reclassification
│   ├── intent_engine.py               # Intent routing engine
│   ├── logical_plan_builder.py        # Registry-locked query planning
│   ├── hybrid_optimizer.py            # Cypher resolution strategies
│   ├── query_runner.py                # Neo4j query execution
│   ├── query_registry.py              # Query registry interface
│   ├── schema_context.py              # Graph schema for LLM prompts
│   ├── llm_client.py                  # Groq API client
│   ├── grounded_generator.py          # Schema-grounded Cypher generation
│   ├── cypher_validator.py            # Cypher syntax validation
│   ├── ambiguity_resolver.py          # Multi-intent disambiguation
│   ├── nl_explainer.py                # LLM-powered NL explanation
│   ├── simple_explainer.py            # Rule-based fallback explainer
│   ├── tools.py                       # Graph traversal tools
│   ├── query_logger.py                # Query logging
│   ├── trace_adapter.py               # Trace building adapter
│   └── config.json                    # Agent configuration
├── engine/
│   ├── domain_knowledge/
│   │   ├── symbol_dictionary.py       # Universal equipment dictionary
│   │   └── semantic_override_system.py # 4-level semantic hierarchy
│   ├── phase0_ingestion/              # GraphML parsing + Neo4j loading
│   ├── phase1_segmentation/           # Topology reconstruction
│   ├── phase2_flow/                   # Arrow-to-LPS evidence binding
│   ├── phase3_annotation/
│   │   ├── (pattern detection + engineering rules)
│   │   ├── skid_corpus_rarity.py      # Cross-PID ESV normalization
│   │   └── global_statistics.py       # Cross-skid statistical aggregation
│   ├── phase4_fsm/
│   │   └── fsm_core.py               # Flow resolution FSM + GlobalStats Step 0c
│   ├── phase5_cypher/                 # 333 analytical Cypher queries (17 categories)
│   ├── phase6_trace/                  # Reasoning trace builder
│   └── phase7_hitl/
│       └── approval.py               # HITL approval workflow
├── graphml_editor/                    # Standalone admin editor package
│   ├── __init__.py
│   ├── patch_store.py                 # Append-only JSON patch persistence
│   ├── neo4j_patcher.py               # Live Neo4j patch application/revert
│   └── graphml_patcher.py             # Patched GraphML export for re-ingestion
├── scripts/
│   ├── register_pid.py                # PID registration utility
│   ├── run_phase0.py – run_phase7.py  # Phase orchestrators
│   ├── audit_annotations.py           # Annotation audit utility
│   ├── audit_trace_consistency.py     # Trace consistency checker
│   ├── check_db_state.py              # Database state inspector
│   └── clear_db.py                    # Database reset utility
├── tests/
│   ├── smoke_engineering.py           # Engineering rule smoke tests
│   ├── smoke_safety.py                # Safety rule smoke tests
│   ├── smoke_tiers.py                 # Tier/severity smoke tests
│   ├── verify_agent_logic.py          # Agent intent verification
│   └── verify_phase*.py               # Phase verification scripts
├── ui/
│   ├── index.html                     # Main chatbot web UI
│   └── editor.html                    # Admin GraphML editor UI
├── docs/
│   ├── PROJECT_OVERVIEW.md            # This document
│   ├── DEMO_QUERIES.md                # Example queries reference
│   └── Command.md                     # CLI command reference
├── pid_store/                         # PID data storage (gitignored)
│   └── PLANT_001/                     # Per-plant PID files
└── logs/                              # Pipeline logs (gitignored)
```

---

## Appendix B: Configuration Reference

### Neo4j Connection

```yaml
# config/neo4j.yaml
uri: neo4j://localhost:7687
database: chatbot
user: neo4j
```

### Storage

```yaml
# config/storage.yaml
store_root: ./pid_store
```

### FSM Parameters

```json
{
    "DECAY": 0.8,
    "BRANCH_DECAY": 0.85,
    "MIN_CONFIDENCE": 0.05,
    "MAX_ITERATIONS": 100,
    "UNCERTAIN_THR": 0.40
}
```

---

*Document generated March 27, 2026 — PID-KOS v1.0  
Updated April 21, 2026 — PID-KOS v1.1*
