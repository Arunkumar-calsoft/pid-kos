# engine/phase2_flow/symbol_dictionary.py
#
# Symbol Dictionary for P&ID interpretation.
#
# IMPORTANT:
#   - Contains NO inference logic
#   - Defines ONLY symbolic priors
#   - Nothing here is enforced as truth

SYMBOL_DICTIONARY = {

    # ── Flow Direction Symbols ────────────────────────────────────────────
    "arrow": {
        "aliases": ["arrow", "flow_arrow", "direction"],
        "confidence": 0.90,
        "meaning": "flow_direction",
    },

    # ── Equipment ─────────────────────────────────────────────────────────
    "pump": {
        "aliases": ["pump", "centrifugal_pump"],
        "implies_flow": True,
        "default_direction": "OUTLET",
        "confidence": 0.80,
    },

    "tank": {
        "aliases": ["tank", "vessel", "drum"],
        "implies_flow": False,
        "confidence": 0.60,
    },

    # ── Valves ────────────────────────────────────────────────────────────
    "manual_valve": {
        "aliases": ["valve", "gate_valve", "ball_valve"],
        "inline": True,
        "confidence": 0.65,
    },

    "control_valve": {
        "aliases": ["cv", "control_valve"],
        "inline": True,
        "confidence": 0.75,
    },

    # ── Line Types ────────────────────────────────────────────────────────
    "process_line": {
        "aliases": ["solid"],
        "is_process_flow": True,
        "confidence": 0.90,
    },

    "signal_line": {
        "aliases": ["dashed", "signal"],
        "is_process_flow": False,
        "confidence": 0.90,
    },
}