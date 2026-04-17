# PID-KOS — P&ID Knowledge & Orchestration System

> An automated platform for ingesting, analysing, and querying Piping & Instrumentation Diagrams (P&IDs) using a Neo4j knowledge graph and an LLM-backed conversational agent.

**Author:** Arun Kumar — Calsoft Pvt Ltd  
**Version:** 1.0 · April 2026

---

## What it does

| Capability | Details |
|---|---|
| **Graph ingestion** | Parses GraphML P&ID drawings into a Neo4j graph (Plant → Skid → PID hierarchy) |
| **Pipe topology** | Reconstructs raw geometry into PipeSegments and LogicalPipeSegments |
| **Flow resolution** | Determines flow direction via FSM + BFS over arrow evidence, check-valve semantics, and equipment topology |
| **Engineering validation** | Validates 9 engineering rules (CRITICAL / HIGH / MEDIUM) against a domain-knowledge dictionary |
| **Pattern detection** | Detects 30+ structural patterns — branches, dead-ends, cycles, parallel paths, rarity scoring |
| **Query registry** | 333 pre-verified Cypher queries across 17 categories, auto-built from `.cypher` source files |
| **Reasoning traces** | Deterministic audit trails per query category |
| **HITL workflow** | Human-in-the-loop review, approval, cross-PID statistical normalisation |
| **LLM agent** | 15+ intent types → engineer-readable natural language answers via Groq API |
| **Web UI** | Flask-served SPA with drawing overlay, node highlighting, violation markers, Q&A chat |
| **GraphML editor** | Standalone admin tool for patching graph connectivity live in Neo4j + corrected GraphML export |

## Architecture at a glance

```
Phase 0  Ingestion     GraphML → Neo4j (Node, PIPE, Plant/Skid/PID hierarchy)
Phase 1  Segmentation  PipeSegment, LogicalPipeSegment, JOINS_AT, ENDPOINT_OF
Phase 2  Flow Evidence Arrow→LPS binding, observed_direction
Phase 3  Annotation    30+ patterns, 9 engineering rules, ESV classification
Phase 4  FSM           Flow direction BFS propagation, confidence scoring
Phase 5  Cypher        333-query registry across 17 analytical categories
Phase 6  Traces        Deterministic reasoning trace generation
Phase 7  HITL          Review corpus, approval workflow, global statistics
Agent    LLM           Intent classification → Cypher → NL explanation
UI       Flask         Chatbot console (port 8080) + GraphML editor (port 8081)
```

## Tech stack

| Layer | Technology |
|---|---|
| Graph database | Neo4j (Bolt) |
| Backend | Python 3.11+, Flask |
| LLM | Groq API (Llama / Mixtral) |
| Frontend | Vanilla HTML / JS |
| Config | YAML + JSON |

## Quick start

```bash
# 1. Clone and install dependencies
pip install -r requirements.txt

# 2. Configure Neo4j connection
cp config/neo4j.yaml.example    config/neo4j.yaml
#    → set your Neo4j URI, user, password, and database name

# 3. Configure storage (where your P&ID drawing files live)
cp config/storage.yaml.example  config/storage.yaml
#    → set store_root to the absolute path of your pid_store folder
#    → folder structure: pid_store/<PLANT_ID>/<SKID_ID>/<PID_ID>/<drawing>.graphml + .png

# 4. Set your LLM API key (never commit the real key)
cp agent/groq.env.example  agent/groq.env
#    → paste your Groq API key

# 4. Register a PID and run the full pipeline
python scripts/register_pid.py  PLANT_001 SKID_01 PID_0  path/to/drawing.graphml
python scripts/run_all.ps1      # or run each phase individually

# 5. Start the web console
python server.py                        # http://localhost:8080
python editor_server.py --port 8081     # http://localhost:8081  (admin editor)
```

## Docs

| File | Description |
|---|---|
| [docs/PROJECT_OVERVIEW.md](docs/PROJECT_OVERVIEW.md) | Full architecture, all pipeline phases, graph schema, roadmap |
| [docs/DEMO_QUERIES.md](docs/DEMO_QUERIES.md) | Example natural-language queries and expected answers |
| [docs/Command.md](docs/Command.md) | CLI command reference |

## Repository layout

```
agent/          LLM agent — intent parsing, hybrid optimizer, Cypher generator
engine/
  phase0_ingestion/   GraphML → Neo4j loader
  phase1_segmentation/
  phase2_flow/
  phase3_annotation/
  phase4_fsm/
  phase5_cypher/      .cypher source files (17 categories, 333 queries)
  phase6_trace/
  phase7_hitl/
  domain_knowledge/   Engineering rule dictionaries
graphml_editor/ Standalone admin GraphML correction tool
config/         neo4j.yaml.example, storage.yaml.example
scripts/        Phase runners, DB utilities
tests/          Smoke tests, verification scripts
ui/             index.html (console), editor.html (admin editor)
docs/           PROJECT_OVERVIEW.md, DEMO_QUERIES.md, Command.md
server.py       Main Flask app (port 8080)
editor_server.py  GraphML editor Flask app (port 8081)
```

## Licence

Internal / proprietary — Calsoft Pvt Ltd.
