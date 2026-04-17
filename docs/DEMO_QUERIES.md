# PID-KOS: Demo Query Catalogue

Sample queries demonstrating all chatbot capabilities. Each section maps to one
intent route in the agent. Queries are designed for the live **Condensate System**
P&ID (`PID_2` / `PID_0`).

---

## 1. Equipment Inventory

Count and classify all symbols on the drawing.

| # | Query |
|---|-------|
| 1 | How many valves are on this drawing? |
| 2 | How many tanks are there? |
| 3 | How many pumps? |
| 4 | How many instruments are on this drawing? |
| 5 | How many check valves are there? |
| 6 | How many inline equipment symbols? |
| 7 | How many arrows? |
| 8 | How many external interfaces? |
| 9 | Count symbols by type. |
| 10 | Show all equipment on this drawing. |
| 11 | List all valves. |
| 12 | List all tanks. |
| 13 | List all pumps. |
| 14 | Show all instruments. |
| 15 | Show all check valves. |

---

## 2. Valve Placement

Valve enumeration, placement context, and pipe connectivity.

| # | Query |
|---|-------|
| 16 | Which valves are upstream of the tank? |
| 17 | Which valves are downstream of the pump? |
| 18 | Show valves connected to pumps. |
| 19 | Which valves connect to tanks? |
| 20 | What types of valves are on this drawing? |
| 21 | Show valve type breakdown. |
| 22 | Show all check valves. |
| 23 | Where are check valves located? |
| 24 | Show valve locations. |

---

## 3. Instrument Attachment

Instrument presence, type breakdown, and attachment to equipment and pipe lines.

| # | Query |
|---|-------|
| 25 | How many instruments are attached to pipe segments? |
| 26 | Which instruments are attached to equipment? |
| 27 | Show instruments attached to tanks. |
| 28 | Are there any orphan instruments? |
| 29 | Which instruments have no attachment? |
| 30 | List instruments by type. |
| 31 | What types of instruments are on this drawing? |

---

## 4. Engineering Correctness & Safety

Topology-based P&ID conformance checks against engineering rules.

### 4a. Rule Violation Summary

| # | Query |
|---|-------|
| 32 | Are there any engineering rule violations? |
| 33 | Show all rule violations. |
| 34 | Show critical severity violations. |
| 35 | Show high severity violations. |

### 4b. Check Valve (Backflow Protection)

| # | Query |
|---|-------|
| 36 | Which pumps are missing a check valve? |
| 37 | Show missing check valve violations. |
| 38 | Is there reverse flow protection on all pumps? |
| 39 | Which equipment has no check valve downstream? |

### 4c. Isolation Valves

| # | Query |
|---|-------|
| 40 | Do all pumps have isolation valves? |
| 41 | Show missing isolation valve violations. |
| 42 | Are all tanks isolatable? |
| 43 | Which tanks have no isolation valve? |

### 4d. Suction Strainers

| # | Query |
|---|-------|
| 44 | Are there any missing suction strainers? |
| 45 | Show missing suction strainer violations. |
| 46 | Which pumps are missing a strainer upstream? |

### 4e. Instrumentation Coverage

| # | Query |
|---|-------|
| 47 | Are all tanks instrumented? |
| 48 | Which tanks have no instruments? |
| 49 | Which tanks are unmonitored? |

### 4f. Boundary Integrity

| # | Query |
|---|-------|
| 50 | Are all boundary interfaces correctly connected? |
| 51 | Show external interface integrity. |

---

## 5. Pipe Lines (Logical Pipe Segments)

Route-level queries on LogicalPipeSegment nodes.

| # | Query |
|---|-------|
| 52 | How many logical pipe segments are there? |
| 53 | List all pipe lines. |
| 54 | How many pipe lines have SEEDED flow state? |
| 55 | How many pipe lines have PROPAGATED flow? |
| 56 | How many pipe lines have UNKNOWN flow state? |
| 57 | Show all LPS with FORWARD flow direction. |
| 58 | Show pipe lines with REVERSE flow. |
| 59 | Show LPS with flow confidence below 0.5. |
| 60 | Which pipe lines have low confidence? |
| 61 | What is the flow state breakdown across all pipe lines? |
| 62 | Show all pipe segments. |

---

## 6. Flow Direction

As-drawn flow direction resolved from arrow evidence.

| # | Query |
|---|-------|
| 63 | What is the flow direction coverage? |
| 64 | What percentage of pipe lines have a resolved flow direction? |
| 65 | How many pipe lines have unknown flow direction? |
| 66 | Show all flow arrows and their confidence scores. |
| 67 | How many arrows are there? |
| 68 | Show all valves with resolved flow direction. |
| 69 | Which tanks have SEEDED flow state? |
| 70 | Which valve nodes have flow confidence below 0.5? |
| 71 | Show segments with PROPAGATED flow. |
| 72 | Show flow direction gaps. |
| 73 | What is the flow state breakdown? |

---

## 7. Connectivity & Topology

PIPE-graph traversal — adjacency, upstream/downstream paths, reachability.

| # | Query |
|---|-------|
| 74 | What is downstream of valve94? |
| 75 | What is upstream of tank12? |
| 76 | Find all nodes reachable from tank12. |
| 77 | What nodes are connected to tank91? |
| 78 | What valves are connected to tank67? |
| 79 | How many valves are connected to tank67? |
| 80 | Show all connections from this node. |
| 81 | Show which nodes have degree greater than 3. |
| 82 | How many PIPE connections are there? |
| 83 | Are all symbols connected? |
| 84 | Show disconnected nodes. |

---

## 8. Drawing Consistency (Structural Defects)

Pre-computed structural anomaly detection via Annotation nodes.

### 8a. Quality Defects

| # | Query |
|---|-------|
| 85 | Are there any drawing quality issues? |
| 86 | Is this diagram structurally consistent? |
| 87 | Are there any orphaned symbols? |
| 88 | Give me a full structural anomaly report. |
| 89 | Show all drawing defects. |

### 8b. Structural Topology Inventory

| # | Query |
|---|-------|
| 90 | How many T-junctions are there? |
| 91 | Show all T-junction nodes. |
| 92 | Show all pipe junction nodes. |
| 93 | How many pipe junctions are there? |
| 94 | Show all high-degree nodes. |
| 95 | How many high-degree nodes? |
| 96 | Show all manifold nodes. |
| 97 | List all dead-end segments. |
| 98 | How many dead-end segments? |
| 99 | Show all structural branch nodes. |
| 100 | List all crossing nodes. |

---

## 9. External Interfaces (Boundary Connections)

External system connections at the P&ID boundary.

| # | Query |
|---|-------|
| 101 | How many external interfaces are on this drawing? |
| 102 | Show all external interfaces. |
| 103 | List all inlet/outlet nodes. |
| 104 | Which external interfaces are on the left boundary? |
| 105 | Which interfaces are on the right side? |
| 106 | What external interfaces does this drawing have? |

---

## 10. Rarity & Redundancy Patterns

Structural redundancy detection, rare motifs, and corpus-level rarity scoring.

| # | Query |
|---|-------|
| 107 | Show rare structural motifs. |
| 108 | Which nodes have the rarest local neighbourhood pattern? |
| 109 | Show patterns labelled as architecturally rare. |
| 110 | Show the rarity label distribution. |
| 111 | Are there any duplicate pipe segments? |
| 112 | Which pipe segments have identical geometry hashes? |
| 113 | Show dominant patterns. |
| 114 | How many structural pattern frequency annotations exist? |

---

## 11. Pipe Segment Junctions

PipeSegment-level junction and adjacency analysis.

| # | Query |
|---|-------|
| 115 | Which pipe segments meet at a valve junction? |
| 116 | Show segments joining at a common point. |
| 117 | How many junctions are there? |
| 118 | Where do pipe segments branch? |
| 119 | Show adjacent pipe segments. |
| 120 | Which segments are adjacent? |

---

## 12. Annotation Requests (HITL Review Queue)

Human- or system-raised review requests on specific nodes.

| # | Query |
|---|-------|
| 121 | Are there any pending annotation requests? |
| 122 | How many pending requests? |
| 123 | Which nodes have been flagged for review? |
| 124 | Show annotation requests by anomaly type. |
| 125 | How many DUPLICATE_BBOX requests are there? |
| 126 | Show all dangling inline annotation requests. |
| 127 | Show annotation requests for valve nodes. |
| 128 | Which valves are flagged for review? |

---

## 13. Cross-Domain Queries

Multi-entity queries combining equipment, pipe lines, annotations, and flow data.

| # | Query |
|---|-------|
| 129 | Which valves are on pipe lines with unknown flow direction? |
| 130 | Which pipe segments contain both a valve and an instrument? |
| 131 | Show instruments attached to pipe segments that have no logical mapping. |
| 132 | Which tanks are reachable from inlet nodes? |
| 133 | Show all equipment with at least one quality annotation. |
| 134 | What is the ESV count for this drawing? |
| 135 | What is the KAV breakdown? |
| 136 | Show all HIGH-severity annotations. |
| 137 | List critical annotations. |
| 138 | Show annotations grouped by pipeline phase. |
| 139 | Show annotations grouped by intent. |
| 140 | Which annotation types co-occur most on the same node? |
| 141 | Show evidence nodes from equipment semantics. |

---

## 14. Architecture-Specific Showcase Queries

These queries demonstrate capabilities that are unique to the PID-KOS architecture
and differentiate it from basic graph databases or simple diagram viewing tools.

| # | Query | Capability Demonstrated |
|---|-------|------------------------|
| 142 | Which pumps are missing a check valve? | Phase 3.5 engineering rules + HITL approval |
| 143 | What is the flow direction coverage? | Phase 4 FSM seeding + propagation |
| 144 | Show rare structural motifs. | Phase 3 rarity scoring across corpus |
| 145 | Are there any engineering rule violations? | Pre-computed violation Annotations |
| 146 | Show all high severity violations. | Severity classification (CRITICAL/HIGH/MEDIUM) |
| 147 | Show segments with PROPAGATED flow. | Phase 4 FSM propagation beyond seeded arrows |
| 148 | Give me a full structural anomaly report. | Phase 3 pattern detection across all types |
| 149 | Show annotations grouped by pipeline phase. | 8-phase pipeline traceability |
| 150 | Which pipe lines have low confidence? | Flow confidence scoring from arrow evidence |

---

## Notes

- **PID scope**: All queries run against the active PID shown in the UI (`PID_0` or `PID_2`).  
- **No tag names in graph**: Nodes are identified by ID (e.g. `valve94`, `tank12`). Queries 74–79 use node IDs exactly as shown in the UI tooltip.  
- **Pumps stored as tanks**: The graph has no `label='pump'`. Pumps are `label='tank'` with `functional_label='pump'` — the agent handles this translation automatically.  
- **Pre-computed results**: Engineering violations, structural annotations, and rarity scores are pre-computed at ingestion time; query responses are deterministic and fast.
