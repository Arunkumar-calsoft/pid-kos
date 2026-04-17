# engine/phase0_ingestion/load_to_neo4j.py
#
# Neo4j loader for Phase 0.
#
# Responsibilities:
#   - ensure_registry: marks PID status as IN_PROGRESS
#   - load_nodes: writes equipment/topology nodes with coord_system
#   - load_edges: writes undirected PIPE relationships
#   - load_annotation_requests: writes Phase 0 anomaly work queue
#   - summary_orphans: diagnostic print of degree-0 nodes
#
# FIXES APPLIED:
#   FIX-1:  load_nodes stamps pid_id on every Node node.
#   FIX-2:  load_annotation_requests stamps pid_id on every AnnotationRequest.
#   FIX-3:  clear_pid uses dual-strategy deletion (relationship + property).
#   FIX-4:  Neo4jLoader.__init__ accepts neo4j_cfg as optional parameter.
#   FIX-5:  load_edges stamps pid_id on PIPE relationship.
#
# GAP-5 FIX (clear cascade):
#   clear_pid now accepts a cascade_phase argument.  When Phase 0 re-runs on
#   a PID that is already at PHASE1_COMPLETE or beyond, calling clear_pid()
#   alone left PipeSegment / LogicalPipeSegment / Arrow / Evidence / Annotation
#   nodes with dangling CONTAINS and ENDPOINT_OF relationships pointing at the
#   freshly deleted Node nodes.  Phase 1 MERGE on PipeSegment would re-use the
#   existing PS node without removing its old rels, leaving ghost topology.
#
#   Resolution order for cascade_phase:
#     'node_only'   — delete Node + AnnotationRequest only (Phase 0 partial re-run)
#     'phase1'      — also delete PipeSegment, LogicalPipeSegment
#     'phase2'      — also delete Arrow nodes + FLOW_EVIDENCE rels
#     'phase3'      — also delete Evidence + Annotation nodes, remove lps.seed_confidence
#     'phase4'      — also remove Phase 4 flow properties from LPS + equipment Nodes
#     'full'        — alias for 'phase4' (everything)
#
#   run_phase0.py calls clear_pid(pid_id, cascade_phase='full') when PID status
#   is PHASE1_COMPLETE or beyond, guaranteeing a clean slate across all phases.
#
# GAP-12 FIX (Arrow cleanup):
#   clear_pid at cascade_phase >= 'phase2' now removes Arrow nodes stamped with
#   this pid_id.  Previously Arrow nodes were only cleaned by clear_phase2_data
#   in run_phase2.py, so Phase 0 re-runs left orphaned Arrow nodes from previous
#   Phase 2 runs.

import json
import os
import pathlib
import yaml
from neo4j import GraphDatabase


_REQUIRED_FIELDS     = {"uri", "user", "password"}
_CONFIG_FILE_FALLBACK = pathlib.Path(__file__).resolve().parents[2] / "config" / "neo4j.yaml"
_AGENT_CONFIG_PATH    = pathlib.Path(__file__).resolve().parents[2] / "agent" / "config.json"

# Ordered cascade levels — each level includes all levels below it.
_CASCADE_ORDER = ["node_only", "phase1", "phase2", "phase3", "phase4"]


class ConfigurationError(RuntimeError):
    """Raised when Neo4j connection parameters cannot be resolved."""


class Neo4jLoader:

    def __init__(self, neo4j_cfg: dict | None = None):
        """
        Accept config dict directly or fall back to config/neo4j.yaml.

        Resolution order:
          1. neo4j_cfg dict passed by caller
          2. config.json on disk (looks for "neo4j" key)
          3. config/neo4j.yaml
        """
        if isinstance(neo4j_cfg, str):
            with open(neo4j_cfg, "r") as f:
                raw = yaml.safe_load(f)
                neo4j_cfg = raw.get("neo4j", raw)

        if not neo4j_cfg:
            neo4j_cfg = self._load_from_agent_config() or self._load_from_yaml()

        if not neo4j_cfg:
            raise ConfigurationError(
                "Neo4j configuration not found. Provide one of:\n"
                "  1. config.json with a \"neo4j\" key\n"
                "  2. config/neo4j.yaml\n"
                "  3. Pass neo4j_cfg dict explicitly to Neo4jLoader(neo4j_cfg)"
            )

        missing = _REQUIRED_FIELDS - neo4j_cfg.keys()
        if missing:
            raise ConfigurationError(
                f"Neo4j config missing required fields: {missing}\n"
                f"Expected: uri, user, password (and optionally database)"
            )

        self.uri      = neo4j_cfg["uri"]
        self.user     = neo4j_cfg["user"]
        self.password = neo4j_cfg["password"]
        self.database = neo4j_cfg.get("database", "chatbot")

        # Environment variable overrides — take priority over config file values.
        # Set NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD in env to avoid storing
        # credentials in version-controlled config files.
        _env_uri      = os.environ.get("NEO4J_URI")
        _env_user     = os.environ.get("NEO4J_USER")
        _env_password = os.environ.get("NEO4J_PASSWORD")
        if _env_uri:
            self.uri = _env_uri
        if _env_user:
            self.user = _env_user
        if _env_password:
            self.password = _env_password

        self.driver = GraphDatabase.driver(self.uri, auth=(self.user, self.password))
        print(f"[NEO4J] Connected to {self.uri} (db={self.database})")

    # ── Config fallback loaders ──────────────────────────────────────────────

    @staticmethod
    def _load_from_agent_config() -> dict | None:
        candidates = [
            _AGENT_CONFIG_PATH,
            pathlib.Path(__file__).resolve().parents[2] / "agent" / "config.json",
            pathlib.Path.cwd() / "agent" / "config.json",
        ]
        for path in candidates:
            try:
                if path.exists():
                    raw = json.loads(path.read_text(encoding="utf-8"))
                    result = raw.get("neo4j")
                    if result:
                        return result
            except Exception:
                pass
        return None

    @staticmethod
    def _load_from_yaml() -> dict | None:
        candidates = [
            _CONFIG_FILE_FALLBACK,
            pathlib.Path(__file__).resolve().parents[1] / "config" / "neo4j.yaml",
            pathlib.Path.cwd() / "config" / "neo4j.yaml",
        ]
        for path in candidates:
            try:
                if path.exists():
                    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
                    result = raw.get("neo4j", raw) if isinstance(raw, dict) else None
                    if result and isinstance(result, dict):
                        return result
            except Exception:
                pass
        return None

    def close(self):
        self.driver.close()
        print("[NEO4J] Connection closed")

    def clear(self):
        """Full database wipe. Prefer clear_pid() in production."""
        with self.driver.session(database=self.database) as s:
            s.run("MATCH (n) DETACH DELETE n")
        print("[NEO4J] Database cleared")

    # ── GAP-5 + GAP-12: Cascading PID clear ──────────────────────────────────

    def clear_pid(self, pid_id: str, cascade_phase: str = "full") -> None:
        """
        Remove all data for one PID up to and including the specified phase.

        cascade_phase values (each includes all lower levels):
          'node_only' — Node + AnnotationRequest only
          'phase1'    — also PipeSegment, LogicalPipeSegment
          'phase2'    — also Arrow, FLOW_EVIDENCE (GAP-12)
          'phase3'    — also Evidence, Annotation, lps.seed_confidence
          'phase4'    — also LPS / Node flow properties, violation summaries
          'full'      — alias for 'phase4'

        Preserves: Plant → Skid → PID registry chain and file path metadata.
        Uses dual-strategy (relationship + pid_id property) throughout.
        """
        if cascade_phase == "full":
            cascade_phase = "phase4"

        if cascade_phase not in _CASCADE_ORDER:
            raise ValueError(
                f"Unknown cascade_phase '{cascade_phase}'. "
                f"Valid values: {_CASCADE_ORDER + ['full']}"
            )

        level = _CASCADE_ORDER.index(cascade_phase)

        with self.driver.session(database=self.database) as s:

            # ── Always: Node cleanup ───────────────────────────────────────
            s.run("MATCH (pid:PID {pid_id:$p})-[:CONTAINS]->(n:Node) DETACH DELETE n", p=pid_id)
            s.run("MATCH (n:Node {pid_id:$p}) DETACH DELETE n", p=pid_id)

            # ── Always: AnnotationRequest cleanup ─────────────────────────
            s.run("MATCH (pid:PID {pid_id:$p})-[:HAS_ANNOTATION]->(ar:AnnotationRequest) DETACH DELETE ar", p=pid_id)
            s.run("MATCH (ar:AnnotationRequest {pid_id:$p}) DETACH DELETE ar", p=pid_id)

            if level >= _CASCADE_ORDER.index("phase1"):
                # Phase 1: PipeSegment + LogicalPipeSegment
                s.run("MATCH (lps:LogicalPipeSegment {pid_id:$p}) DETACH DELETE lps", p=pid_id)
                s.run("MATCH (ps:PipeSegment {pid_id:$p}) DETACH DELETE ps", p=pid_id)
                print(f"[NEO4J] Cleared Phase 1 data (PipeSegment, LogicalPipeSegment) for PID={pid_id}")

            if level >= _CASCADE_ORDER.index("phase2"):
                # Phase 2: Arrow nodes + FLOW_EVIDENCE rels (GAP-12)
                s.run("MATCH (a:Arrow {pid_id:$p})-[r:FLOW_EVIDENCE]->() DELETE r", p=pid_id)
                s.run("MATCH (a:Arrow {pid_id:$p}) DETACH DELETE a", p=pid_id)
                print(f"[NEO4J] Cleared Phase 2 data (Arrow, FLOW_EVIDENCE) for PID={pid_id}")

            if level >= _CASCADE_ORDER.index("phase3"):
                # Phase 3: Evidence + Annotation nodes + lps.seed_confidence
                # (LPS already deleted at phase1, but in case cascade_phase='phase3'
                #  is called without phase1 cleanup we handle it gracefully)
                s.run("MATCH (e:Evidence {pid_id:$p}) DETACH DELETE e", p=pid_id)
                s.run("MATCH (a:Annotation {pid_id:$p}) DETACH DELETE a", p=pid_id)
                s.run("""
                    MATCH (lps:LogicalPipeSegment {pid_id:$p})
                    REMOVE lps.seed_confidence
                """, p=pid_id)
                # Phase 4 violation summaries on equipment nodes (cascade from Phase 3.5)
                s.run("""
                    MATCH (n:Node)-[:ENDPOINT_OF]->(lps:LogicalPipeSegment {pid_id:$p})
                    WHERE n.has_rule_violations IS NOT NULL
                       OR n.rule_violation_count IS NOT NULL
                       OR n.rule_violation_types IS NOT NULL
                    REMOVE n.has_rule_violations,
                           n.rule_violation_count,
                           n.rule_violation_types
                """, p=pid_id)
                print(f"[NEO4J] Cleared Phase 3 data (Evidence, Annotation, seed_confidence) for PID={pid_id}")

            if level >= _CASCADE_ORDER.index("phase4"):
                # Phase 4: LPS flow properties + equipment Node flow properties
                s.run("""
                    MATCH (lps:LogicalPipeSegment {pid_id:$p})
                    REMOVE lps.flow_state, lps.flow_direction,
                           lps.flow_confidence, lps.flow_source,
                           lps.phase4_blocked, lps.phase4_hint,
                           lps.phase4_resolution_rule
                """, p=pid_id)
                s.run("""
                    MATCH (n:Node {flow_source:'phase4_equipment_assignment'})
                          -[:ENDPOINT_OF]->(lps:LogicalPipeSegment {pid_id:$p})
                    REMOVE n.flow_state, n.flow_direction,
                           n.flow_confidence, n.flow_source,
                           n.flow_pid_id,
                           n.has_rule_violations, n.rule_violation_count,
                           n.rule_violation_types
                """, p=pid_id)
                print(f"[NEO4J] Cleared Phase 4 data (flow properties) for PID={pid_id}")

            # Revert PID status to REGISTERED so the pipeline can re-run from scratch
            s.run("MATCH (pid:PID {pid_id:$p}) SET pid.status = 'REGISTERED'", p=pid_id)

        print(f"[NEO4J] clear_pid complete for PID={pid_id} (cascade_phase={cascade_phase})")

    # ── Registry ──────────────────────────────────────────────────────────────

    def ensure_registry(self, plant_id, skid_id, skid_type, pid_id):
        """
        Mark PID as IN_PROGRESS. Does NOT overwrite graphml_path or image_path.
        Plant and Skid nodes are created if missing (idempotent).
        """
        with self.driver.session(database=self.database) as s:
            s.run(
                """
                MERGE (plant:Plant {plant_id: $plant_id})
                MERGE (skid:Skid   {skid_id:  $skid_id})
                  ON CREATE SET skid.skid_type = $skid_type,
                                skid.plant_id  = $plant_id
                MERGE (pid:PID {pid_id: $pid_id})
                  SET pid.status = 'IN_PROGRESS'
                MERGE (plant)-[:HAS_SKID]->(skid)
                MERGE (skid)-[:HAS_PID]->(pid)
                """,
                plant_id=plant_id, skid_id=skid_id,
                skid_type=skid_type, pid_id=pid_id,
            )
        print(f"[NEO4J] Registry | Plant={plant_id} → Skid={skid_id} → PID={pid_id} [IN_PROGRESS]")

    # ── Nodes ─────────────────────────────────────────────────────────────────

    def load_nodes(self, nodes, pid_id):
        """
        FIX-1: pid_id is part of the MERGE key and stamped as a property
        on every Node node for direct pid_id-based filtering.
        """
        print(f"[NEO4J] Loading {len(nodes)} nodes → PID={pid_id}")

        query = """
        MATCH (pid:PID {pid_id: $pid_id})
        MERGE (n:Node {id: $id, pid_id: $pid_id})
        SET
            n.label        = $label,
            n.xmin         = $xmin,
            n.ymin         = $ymin,
            n.xmax         = $xmax,
            n.ymax         = $ymax,
            n.bbox         = $bbox,
            n.coord_system = $coord_system,
            n.source       = 'graphml',
            n.pid_id       = $pid_id
        MERGE (pid)-[:CONTAINS]->(n)
        """

        with self.driver.session(database=self.database) as s:
            for n in nodes:
                a = n["attrs"]
                s.run(
                    query,
                    pid_id=pid_id, id=n["id"],
                    label=a.get("label"),
                    xmin=a["xmin"], ymin=a["ymin"],
                    xmax=a["xmax"], ymax=a["ymax"],
                    bbox=[a["xmin"], a["ymin"], a["xmax"], a["ymax"]],
                    coord_system=a.get("coord_system", "none"),
                )

        print("[NEO4J] Nodes loaded")

    # ── Edges ─────────────────────────────────────────────────────────────────

    def load_edges(self, edges, pid_id: str):
        """
        Load topology as undirected PIPE relationships.
        FIX-5: pid_id stamped on PIPE relationship.
        """
        print(f"[NEO4J] Loading {len(edges)} undirected PIPE edges")

        query = """
        MATCH (a:Node {id: $src, pid_id: $pid_id}),
              (b:Node {id: $dst, pid_id: $pid_id})
        MERGE (a)-[r:PIPE]-(b)
        SET r.edge_label     = $edge_label,
            r.flow_direction = 'UNKNOWN',
            r.source         = 'graphml',
            r.pid_id         = $pid_id
        """

        with self.driver.session(database=self.database) as s:
            for e in edges:
                attrs = e.get("attrs", {})
                s.run(
                    query,
                    src=e["src"], dst=e["dst"], pid_id=pid_id,
                    edge_label=attrs.get("edge_label", "solid"),
                )

        print(f"[NEO4J] Edges loaded | count={len(edges)}")

    # ── Annotation Requests ───────────────────────────────────────────────────

    def load_annotation_requests(self, anomalies, pid_id):
        """
        Write Phase 0 anomalies as AnnotationRequest nodes.
        FIX-2: pid_id stamped on every AnnotationRequest.
        """
        if not anomalies:
            print("[NEO4J] No annotation requests")
            return

        print(f"[NEO4J] Loading {len(anomalies)} annotation requests")

        query = """
        MATCH (pid:PID {pid_id: $pid_id})
        MATCH (subject:Node {id: $node_id, pid_id: $pid_id})
        MERGE (ar:AnnotationRequest {request_id: $request_id})
        SET
            ar.pid_id       = $pid_id,
            ar.anomaly_type = $anomaly_type,
            ar.node_id      = $node_id,
            ar.label        = $label,
            ar.detail       = $detail,
            ar.status       = 'OPEN',
            ar.phase_origin = 0,
            ar.source       = 'graphml'
        MERGE (ar)-[:CONCERNS]->(subject)
        MERGE (pid)-[:HAS_ANNOTATION]->(ar)
        """

        with self.driver.session(database=self.database) as s:
            for a in anomalies:
                s.run(
                    query,
                    pid_id=pid_id,
                    request_id=f"AR_P0_{a['node_id']}_{a['type']}",
                    anomaly_type=a["type"],
                    node_id=a["node_id"],
                    label=a["label"],
                    detail=a["detail"],
                )

        from collections import Counter
        counts = Counter(a["type"] for a in anomalies)
        print("[NEO4J] Annotation requests loaded:")
        for t, c in counts.items():
            print(f"  {t}: {c}")

    # ── Orphan summary ────────────────────────────────────────────────────────

    def summary_orphans(self, limit=20):
        with self.driver.session(database=self.database) as s:
            rows = s.run(
                """
                MATCH (n:Node)
                WHERE NOT (n)-[:PIPE]-()
                RETURN n.id AS id, n.label AS label
                ORDER BY n.label, n.id
                LIMIT $limit
                """,
                limit=limit,
            ).data()

        print(f"[NEO4J] Orphan nodes (no PIPE connections), limit={limit}:")
        for r in rows:
            print(f"  {r['id']} ({r['label']})")

        return rows