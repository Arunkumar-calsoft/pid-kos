# agent/cli.py
"""
CLI — Composition Root + Conversational Interface

The engineer never sees:
  - query IDs, category names, strategy tags
  - internal error class names on ambiguity
  - raw record dumps

They see:
  - Natural language answers (via NLExplainer / Groq)
  - Friendly clarifying questions on ambiguity
  - Plain error messages on failure
  - Conversational replies to greetings / off-topic questions

LLM is wired from config.json:
    {
      "llm": {
        "provider":         "groq",
        "groq_api_key_env": "GROQ_API_KEY",
        "model":            "llama-3.3-70b-versatile",
        "max_tokens":       800
      }
    }

GROQ_API_KEY is loaded from agent/groq.env automatically if not set in the
real environment. File format is plain KEY=VALUE lines:
    GROQ_API_KEY=gsk_your_key_here

If the key is missing, NLExplainer falls back to SimpleExplainer and
IntentConfirmer becomes a zero-overhead pass-through.

=== GROQ POWER FALLBACK (added) ===
GroqClient now automatically tries models strongest → weakest on 429 rate-limit.
When the full chain is exhausted, this CLI shows a friendly "wait/upgrade" message
instead of a raw traceback.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# .env loader — must run BEFORE any LLM imports so the key is in os.environ
# ---------------------------------------------------------------------------
import os as _os
from pathlib import Path as _Path


def _load_env_file(env_path: _Path) -> None:
    """Load KEY=VALUE pairs from a .env file into os.environ."""
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key   = key.strip()
        value = value.strip().strip('"').strip("'")
        # Never overwrite a key already in the real environment
        if key and key not in _os.environ:
            _os.environ[key] = value


_HERE = _Path(__file__).resolve().parent
_load_env_file(_HERE / "groq.env")       # agent/groq.env  ← primary
_load_env_file(_HERE / ".env")            # agent/.env      ← alt
_load_env_file(_HERE.parent / ".env")    # project root    ← fallback

# ---------------------------------------------------------------------------
# Normal imports
# ---------------------------------------------------------------------------
import json
import re
from typing import Tuple, Optional, List, Dict, Any

from engine.phase0_ingestion.load_to_neo4j import Neo4jLoader

from agent.agent                import Phase8Agent, AnswerResult
from agent.ambiguity_resolver   import AmbiguityResolver
from agent.grounded_generator   import GroundedGenerator
from agent.query_registry       import load_registry
from agent.intent_parser        import IntentParser
from agent.intent_confirmer     import IntentConfirmer
from agent.logical_plan_builder import LogicalPlanBuilder, AmbiguityError
from agent.hybrid_optimizer     import HybridOptimizer, TemplateMatcher, SchemaGenerator
from agent.query_runner         import QueryRunner
from agent.trace_adapter        import TraceAdapter
from agent.simple_explainer     import SimpleExplainer
from agent.nl_explainer         import NLExplainer, RecordSanitizer
from agent.llm_client           import build_llm_client_from_config, LLMClient
from agent.query_logger         import QueryLogger


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_CONFIG_PATH = _Path(__file__).resolve().parent / "config.json"


def _load_config() -> dict:
    if _CONFIG_PATH.exists():
        return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    return {}


# ---------------------------------------------------------------------------
# Hardcoded Cypher templates (Template Match fast path — Tier 1)
# Key = QueryEntry["id"], Value = validated Cypher string.
# Promote well-tested queries here to bypass all other tiers entirely.
#
# Tier ordering:
#   1. TemplateMatcher  → this dict (zero latency)
#   2. Registry file    → Phase 5 .cypher (fixed queries, pre-validated)
#   3. GroundedGenerator→ LLM (customisable queries with entity filters)
#   4. SchemaGenerator  → deterministic fallback
# ---------------------------------------------------------------------------

CYPHER_TEMPLATES: dict[str, str] = {
    # Example (uncomment and add your validated query):
    # "q_eng_inventory_01": (
    #     "MATCH (e:Equipment) "
    #     "RETURN e.equipment_type AS type, count(e) AS total "
    #     "ORDER BY total DESC"
    # ),
}


# ---------------------------------------------------------------------------
# Conversational fallback
# For non-P&ID inputs like "hello", "what can you do?", "thanks"
# ---------------------------------------------------------------------------

_CONVERSATIONAL_SYSTEM = """
You are a helpful assistant embedded in a P&ID (Piping and Instrumentation
Diagram) analysis tool. You help process engineers query their plant drawings.

When the user sends a greeting or asks a general question not related to
P&ID data (e.g. "hello", "what can you do", "help"), respond warmly and
briefly explain what you can help with. Keep replies to 2–4 sentences.

What you CAN help with:
- Equipment counts and inventories (valves, pumps, tanks, instruments)
- Pipe segment and flow direction analysis
- Connectivity and path tracing between nodes
- Drawing quality checks (dangling ends, orphaned annotations, disconnected segments)
- External interfaces and boundary nodes
- Redundancy and adjacency patterns

You CANNOT help with general engineering questions outside the P&ID graph.
Always guide the user back to asking about their drawings.
""".strip()

_CONVERSATIONAL_EXAMPLES = {
    "hello", "hi", "hey", "help", "what can you do", "what do you do",
    "who are you", "what are you", "thanks", "thank you", "goodbye", "bye",
}

_PID_KEYWORDS = {
    "valve", "pump", "pipe", "segment", "flow", "instrument", "equipment",
    "line", "arrow", "annotation", "node", "connect", "path", "drawing",
    "dangling", "orphan", "junction", "boundary", "interface", "redundan",
}


def _is_conversational(question: str) -> bool:
    """Heuristic: greetings, very short inputs with no P&ID keywords."""
    q = question.strip().lower()
    if q in _CONVERSATIONAL_EXAMPLES:
        return True
    words = q.split()
    if len(words) <= 3 and not any(kw in q for kw in _PID_KEYWORDS):
        return True
    return False


def _conversational_reply(question: str, llm_client: Optional[LLMClient]) -> str:
    """Use LLM for a friendly reply, or return a canned response."""
    if llm_client is not None:
        try:
            return llm_client.complete(
                system     = _CONVERSATIONAL_SYSTEM,
                message    = question,
                max_tokens = 200,
            ).strip()
        except Exception:
            pass
    # Canned fallback when LLM is unavailable
    q = question.strip().lower()
    if any(g in q for g in ("hello", "hi", "hey")):
        return (
            "Hello! I'm your P&ID Assistant. Ask me about equipment, valves, "
            "pipe segments, flow directions, or drawing quality on your P&ID drawings."
        )
    return (
        "I'm a P&ID Assistant. I can answer questions about equipment counts, "
        "valve placement, pipe connectivity, flow direction, dangling ends, and "
        "drawing consistency. Try: 'How many valves are there?' or "
        "'Show dangling ends'."
    )


# ---------------------------------------------------------------------------
# Ambiguity presenter
# ---------------------------------------------------------------------------

def _friendly_choice(candidate: dict, index: int) -> str:
    title: str = candidate.get("title", "")
    title = re.sub(r"^\d+\s+", "", title).strip()
    return f"  {index}. {title.capitalize()}"


def _present_ambiguity(candidates: list) -> None:
    print(
        "\nI found a few different things you might be asking about. "
        "Could you clarify?\n"
    )
    for i, c in enumerate(candidates, start=1):
        print(_friendly_choice(c, i))
    print()


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

def build_agent() -> Tuple[Phase8Agent, Neo4jLoader, Optional[LLMClient]]:
    cfg      = _load_config()
    llm_cfg  = cfg.get("llm", {})
    # Pass None when "neo4j" key is absent so Neo4jLoader's fallback
    # chain (config.json → neo4j.yaml) fires correctly.
    # An empty {} would skip the fallback since `if not {}` is True,
    # but explicit None makes intent clearer.
    neo4j_cfg = cfg.get("neo4j") or None

    loader   = Neo4jLoader(neo4j_cfg)
    registry = load_registry()

    fallback  = SimpleExplainer()
    sanitizer = RecordSanitizer()

    # Build LLM client — returns None if GROQ_API_KEY not set
    llm_client = build_llm_client_from_config(llm_cfg)

    # NL Explainer: uses LLM when available, SimpleExplainer otherwise
    if llm_client is not None:
        explainer = NLExplainer(
            llm_client = llm_client,
            fallback   = fallback,
            sanitizer  = sanitizer,
        )
    else:
        explainer = fallback  # type: ignore[assignment]

    # IntentConfirmer: LLM reclassification for unknown_intent queries.
    # When llm_client is None, the class itself is a zero-overhead pass-through
    # (no external guard needed here — IntentConfirmer handles it internally).
    intent_confirmer = IntentConfirmer(
        llm_client           = llm_client,
        confirm_unknown_only = True,
    )

    # SchemaGenerator: pure deterministic Cypher generation from schema rules.
    # No LLM injection — it does not need one.
    schema_generator = SchemaGenerator()

    # GroundedGenerator (Tier 2.5): LLM-powered Cypher, grounded in full schema.
    # Only wired when llm_client is available; falls through to Tier 3 otherwise.
    grounded_generator = GroundedGenerator(llm_client) if llm_client is not None else None

    # AmbiguityResolver: LLM auto-picks between tied registry candidates.
    # Only presents choices to the user when LLM confidence is genuinely low.
    ambiguity_resolver = AmbiguityResolver(llm_client) if llm_client is not None else None

    agent = Phase8Agent(
        registry            = registry,
        intent_parser       = IntentParser(),
        intent_confirmer    = intent_confirmer,
        plan_builder        = LogicalPlanBuilder(registry),
        optimizer           = HybridOptimizer(
            registry           = registry,
            template_matcher   = TemplateMatcher(templates=CYPHER_TEMPLATES),
            schema_generator   = schema_generator,
            grounded_generator = grounded_generator,   # Tier 2.5 — None if no LLM
        ),
        query_runner        = QueryRunner(loader),
        trace_builder       = TraceAdapter(),
        explainer           = explainer,
        query_logger        = QueryLogger(),
        ambiguity_resolver  = ambiguity_resolver,
    )

    return agent, loader, llm_client


# ---------------------------------------------------------------------------
# PID selection helper
# ---------------------------------------------------------------------------

def _select_pid(loader) -> str:
    """
    Query Neo4j for all available PIDs, then:
      - If exactly one → use it silently.
      - If multiple   → prompt the engineer to choose.
      - If none       → warn and return "UNKNOWN" so queries still run globally.
    Returns the active pid_id string.
    """
    try:
        with loader.driver.session(database=loader.database) as _sess:
            rows = _sess.run("MATCH (p:PID) RETURN p.pid_id AS pid_id ORDER BY p.pid_id")
            pid_ids = [r["pid_id"] for r in rows if r.get("pid_id")]
    except Exception:
        pid_ids = []

    if not pid_ids:
        print(
            "\nNote: No PID drawings found in the database. "
            "Queries will run across all available data.\n"
        )
        return "UNKNOWN"

    if len(pid_ids) == 1:
        print(f"Drawing: {pid_ids[0]}\n")
        return pid_ids[0]

    # Multiple PIDs — ask the engineer
    print(f"\nFound {len(pid_ids)} drawings in the database:\n")
    for i, pid in enumerate(pid_ids, start=1):
        print(f"  {i}. {pid}")
    print()

    while True:
        sel = input("Which drawing would you like to query? (enter number): ").strip()
        if sel.isdigit():
            n = int(sel)
            if 1 <= n <= len(pid_ids):
                chosen = pid_ids[n - 1]
                print(f"\nActive drawing: {chosen}\n")
                return chosen
        print(f"  Please enter a number between 1 and {len(pid_ids)}.")


# Sentinel returned when the user wants to switch drawing but didn't name one.
_SWITCH_REQUESTED = "__SWITCH_REQUESTED__"

def _detect_pid_switch(question: str, pid_ids: list) -> Optional[str]:
    """
    Detect drawing-switch intent.

    Returns:
        pid_id string   — switch to this specific drawing
        _SWITCH_REQUESTED — user wants to switch but gave no drawing name
                            (caller should re-prompt for selection)
        None            — not a switch command
    """
    q = question.lower()
    switch_words = ("switch", "change drawing", "change pid", "use drawing",
                    "use pid", "on pid", "on drawing", "swap drawing",
                    "different drawing", "other drawing", "another drawing")
    if not any(kw in q for kw in switch_words):
        return None
    # Try to find a specific PID in the question
    for pid in pid_ids:
        if pid.lower() in q or pid.replace("PID_", "").strip() in q:
            return pid
    # Switch intent detected but no specific drawing named — caller re-prompts
    return _SWITCH_REQUESTED



# ---------------------------------------------------------------------------
# Session state — tracks last result for follow-up resolution
# ---------------------------------------------------------------------------

_FOLLOWUP_PRONOUNS = {
    "them", "they", "these", "those", "it", "its",
    "list them", "show them", "list those", "show those",
    "show all", "list all",        # when no subject given
}

_LIST_TRIGGERS = {"list", "show", "display", "give", "get", "print"}


class _SessionState:
    """Minimal per-session context for follow-up resolution."""

    def __init__(self) -> None:
        self.last_intent:  Optional[str]              = None
        self.last_records: List[Dict[str, Any]]       = []
        self.last_question: str                       = ""

    def update(self, result: "AnswerResult") -> None:
        self.last_intent   = result["intent"].get("intent_type")
        self.last_records  = result.get("records", [])
        self.last_question = result["intent"].get("raw", "")

    def is_followup(self, question: str) -> bool:
        """
        True when the question is a pronoun-based follow-up to the previous
        result and there IS a previous result to follow up on.
        """
        if not self.last_records and not self.last_intent:
            return False
        q = question.strip().lower()
        # Short pure-pronoun inputs
        if q in _FOLLOWUP_PRONOUNS:
            return True
        # Short inputs that are just a list trigger + pronoun
        words = q.split()
        if len(words) <= 3:
            has_trigger = any(w in _LIST_TRIGGERS for w in words)
            has_pronoun = any(w in _FOLLOWUP_PRONOUNS for w in words)
            if has_trigger and has_pronoun:
                return True
        return False

    def followup_answer(self, question: str, simple_explainer: "SimpleExplainer") -> str:
        """
        Return a plain-English answer from the stored last_records without
        hitting Neo4j or the LLM chain again.
        """
        if not self.last_records:
            return "I don\'t have a previous result to expand on. Could you rephrase your question?"

        n = len(self.last_records)
        # Build a synthetic QueryEntry so SimpleExplainer can format it
        from agent.query_registry import QueryEntry
        from typing import cast
        synthetic = cast(QueryEntry, {
            "id":                "followup",
            "title":             self.last_intent or "previous result",
            "intent":            self.last_intent or "unknown_intent",
            "category":          "followup",
            "cypher_file":       "",
            "verified":          True,
            "target_entity":     "",
            "operation":         "list",
            "scope":             "global",
            "output_type":       "table",
            "required_keywords": [],
            "boost_keywords":    [],
            "exclude_keywords":  [],
        })
        return simple_explainer.explain(
            question    = question,
            query_entry = synthetic,
            intent      = {"intent_type": self.last_intent or ""},
            records     = self.last_records,
            traces      = [],
        )

# ---------------------------------------------------------------------------
# CLI loop
# ---------------------------------------------------------------------------

def _print_debug(result: AnswerResult) -> None:
    """Print Cypher query and strategy for verification."""
    strategy = result.get("strategy", "?")
    cypher   = result.get("cypher", "").strip()
    intent   = result.get("intent", {})
    print(f"\n  [DEBUG] strategy : {strategy}")
    print(f"  [DEBUG] intent   : {intent.get('intent_type','?')}  pid_id={intent.get('pid_id','?')}")
    print(f"  [DEBUG] cypher   :\n{_indent(cypher, 4)}\n")


def _indent(text: str, spaces: int) -> str:
    pad = " " * spaces
    return "\n".join(pad + line for line in text.splitlines())


def run_cli(agent: Phase8Agent, loader, llm_client: Optional[LLMClient], debug: bool = False) -> None:
    session   = _SessionState()
    _fallback = SimpleExplainer()
    print("PID Assistant ready. Ask me anything about your P&ID drawings.\n")
    print("  Examples:")
    print("    how many valves are there?")
    print("    show all pipe segments")
    print("    what is the flow direction on LP-042?")
    print("    how many dangling ends are there?")
    print("    list orphaned annotations\n")

    # ── Select active drawing at session start ──
    active_pid_id = _select_pid(loader)

    # Keep a live list for switch detection
    try:
        with loader.driver.session(database=loader.database) as _sess:
            all_rows = _sess.run("MATCH (p:PID) RETURN p.pid_id AS pid_id ORDER BY p.pid_id")
            all_pids = [r["pid_id"] for r in all_rows if r.get("pid_id")]
    except Exception:
        all_pids = []

    while True:
        try:
            question = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            break

        if not question:
            continue
        if question.lower() in {"exit", "quit", "bye", "goodbye"}:
            print("Goodbye.")
            break

        # ── Drawing switch command ──
        switched = _detect_pid_switch(question, all_pids)
        if switched == _SWITCH_REQUESTED:
            # User said "change drawing" but didn't name one — re-run the selector
            print()
            active_pid_id = _select_pid(loader)
            continue
        if switched and switched != active_pid_id:
            active_pid_id = switched
            print(f"\nAssistant: Switched to drawing {active_pid_id}. What would you like to know?\n")
            continue

        # ── Follow-up resolution (before conversational check) ──
        if session.is_followup(question):
            reply = session.followup_answer(question, _fallback)
            print(f"\nAssistant: {reply}\n")
            continue

        # ── Conversational / off-topic → LLM chat reply ──
        if _is_conversational(question):
            reply = _conversational_reply(question, llm_client)
            print(f"\nAssistant: {reply}\n")
            continue

        # ── P&ID query path ──
        try:
            result = agent.answer(question, pid_id=active_pid_id)
            session.update(result)          # store for potential follow-up
            print(f"\nAssistant: {result['answer']}\n")
            if debug:
                _print_debug(result)

        except AmbiguityError as exc:
            intent = agent.intent_parser.parse(question, pid_id=active_pid_id)
            if agent._logger:
                agent._logger.log_ambiguity(
                    question=question, intent=intent, candidates=exc.candidates
                )

            _present_ambiguity(exc.candidates)
            sel = input("You: ").strip()

            if not sel or not sel.isdigit():
                print("\nAssistant: No problem, feel free to rephrase.\n")
                continue

            idx = int(sel) - 1
            if idx < 0 or idx >= len(exc.candidates):
                print("\nAssistant: That number isn't on the list — try again.\n")
                continue

            try:
                result = agent.answer_with_query(question, exc.candidates[idx], pid_id=active_pid_id)
                session.update(result)
                print(f"\nAssistant: {result['answer']}\n")
                if debug:
                    _print_debug(result)
            except Exception as e:
                print(f"\nAssistant: I ran into a problem retrieving that — {e}\n")

        except NotImplementedError:
            # Schema generator has no rule for this intent
            reply = _conversational_reply(
                f"I can't answer '{question}' yet. What can you help with?",
                llm_client,
            )
            print(f"\nAssistant: {reply}\n")

        except RuntimeError as exc:
            msg = str(exc)
            if "No verified query matches" in msg or "unknown_intent" in msg:
                print(
                    "\nAssistant: I'm not sure how to look that up. "
                    "Try asking about valves, instruments, pipe segments, "
                    "dangling ends, or flow direction.\n"
                )
            else:
                print(f"\nAssistant: Something went wrong — {exc}\n")

        except Exception as exc:
            err_str = str(exc).lower()
            if any(k in err_str for k in ("rate_limit", "429", "all fallback models exhausted", "all groq models failed", "tpd")):
                print("\nAssistant: Groq rate limit reached on ALL models "
                      "(even the weaker fallback ones).")
                print("   → Please wait ~30–60 minutes or upgrade to Dev Tier:")
                print("     https://console.groq.com/settings/billing")
                print("The assistant will continue using non-LLM fallbacks "
                      "(SimpleExplainer + Cypher templates) for now.\n")
            else:
                intent = None
                try:
                    intent = agent.intent_parser.parse(question, pid_id=active_pid_id)
                except Exception:
                    pass
                if agent._logger:
                    agent._logger.log_error(question=question, intent=intent, error=exc)
                print(
                    "\nAssistant: I ran into an unexpected problem. "
                    "Please try again or rephrase your question.\n"
                )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="PID Assistant CLI")
    parser.add_argument(
        "--debug", "-d",
        action  = "store_true",
        help    = "Print the Cypher query and strategy after each answer.",
    )
    args = parser.parse_args()

    print("========== PID Assistant ==========\n")
    loader: Optional[Neo4jLoader] = None
    try:
        agent, loader, llm_client = build_agent()
        run_cli(agent, loader, llm_client, debug=args.debug)
    except Exception as exc:
        print(f"\n[FATAL] {type(exc).__name__}: {exc}")
        if "neo4j" in str(exc).lower() or "uri" in str(exc).lower() or "config" in str(exc).lower():
            print(
                "\nTo fix: add a \"neo4j\" block to config.json:\n"
                "{\n"
                "  \"neo4j\": {\n"
                "    \"uri\": \"bolt://localhost:7687\",\n"
                "    \"user\": \"neo4j\",\n"
                "    \"password\": \"your-password\",\n"
                "    \"database\": \"chatbot\"\n"
                "  }\n"
                "}"
            )
    finally:
        if loader is not None:
            loader.close()


if __name__ == "__main__":
    main()