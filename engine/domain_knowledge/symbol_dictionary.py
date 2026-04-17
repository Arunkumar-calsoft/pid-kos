# engine/domain_knowledge/symbol_dictionary.py
#
# Hierarchical Symbol Dictionary for P&ID Engineering Validation
#
# GAP-4 FIX (non_return/check labels):
#   'non_return' and 'check' added to UNIVERSAL_EQUIPMENT with
#   function='backflow_prevention', matching the existing check_valve/nrv entries.
#   get_check_valve_labels() iterates UNIVERSAL_EQUIPMENT for function==backflow_prevention,
#   so these labels are now correctly included in CHECK_VALVE_LABELS in equipment_flow.py.
#
# NEW-A FIX (pump rules for condensate tank nodes):
#   SKID_CONTEXT['CONDENSATE'] now has a 'tank' sub-key that mirrors the 'pump'
#   rules for small tank nodes (width < 100px).  Phase 1 classify_equipment.py
#   stamps functional_label='pump' on these nodes so engineering_rules.py looks
#   them up as 'pump', but the symbol_dictionary 'tank' entry is kept consistent
#   so any code that looks up 'tank' directly still gets pump-level validation rules.

import copy
from typing import Any, Dict, List, Optional


UNIVERSAL_EQUIPMENT: Dict[str, Dict[str, Any]] = {

    # ── Active rotating equipment ─────────────────────────────────────────────
    "pump": {
        "function": "pressure_increase",
        "description": "Rotating equipment that adds energy to the fluid to move it through the system.",
        "why_needed": "Required wherever the process fluid must overcome resistance (pipe friction, elevation, back-pressure) to reach the next section of the system.",
        "typical_location": "Suction side draws from a vessel or collection point; discharge side feeds the process header.",
        "creates_flow": True,
        "flow_direction": "unidirectional",
        "active_equipment": True,
        "universal_requirements": [
            {
                "equipment": "check_valve",
                "max_hops": 10,
                "reason": "backflow_prevention",
                "severity": "CRITICAL",
                "exception_conditions": ["deadhead_test_service"],
            },
        ],
        "expected_degree": {
            "inlet_connections": [1, 1],
            "outlet_connections": [1, 1],
            "auxiliary": [0, 2],
        },
        "provides_flow_evidence": True,
        "evidence_confidence": 0.80,
        "evidence_type": "equipment_semantics",
        "outlet_identification_method": "dominant_axis",
        "min_axis_separation": 5.0,
        "safety_critical": True,
        "failure_mode": "no_flow_or_reverse_flow",
        "protection_required": ["backflow", "deadhead", "cavitation"],
        "corpus_parameters": {
            "typical_check_valve_distance": None,
            "recirculation_frequency": None,
            "common_upstream_equipment": [],
            "common_downstream_equipment": [],
        },
    },

    "centrifugal_pump": {
        "function": "centrifugal_pressure_increase",
        "creates_flow": True,
        "flow_direction": "unidirectional",
        "active_equipment": True,
        "universal_requirements": [
            {
                "equipment": "check_valve",
                "max_hops": 10,
                "reason": "backflow_prevention_centrifugal",
                "severity": "CRITICAL",
            },
            {
                "equipment": "suction_strainer",
                "max_hops": 3,
                "reason": "impeller_protection",
                "severity": "HIGH",
                "exception_conditions": ["clean_service"],
            },
        ],
        "expected_degree": {"inlet_connections": [1, 1], "outlet_connections": [1, 1], "auxiliary": [0, 2]},
        "provides_flow_evidence": True,
        "evidence_confidence": 0.80,
        "safety_critical": True,
    },

    "compressor": {
        "function": "gas_pressure_increase",
        "creates_flow": True,
        "flow_direction": "unidirectional",
        "active_equipment": True,
        "universal_requirements": [
            {"equipment": "check_valve", "max_hops": 8, "reason": "backflow_prevention_gas", "severity": "CRITICAL"},
            {"equipment": "inlet_filter", "max_hops": 3, "reason": "compressor_protection", "severity": "HIGH"},
        ],
        "expected_degree": {"inlet_connections": [1, 1], "outlet_connections": [1, 1], "auxiliary": [0, 3]},
        "provides_flow_evidence": True,
        "evidence_confidence": 0.80,
        "safety_critical": True,
    },

    "ejector": {
        "function": "vacuum_generation_or_mixing",
        "creates_flow": True,
        "flow_direction": "unidirectional",
        "active_equipment": True,
        "universal_requirements": [],
        "expected_degree": {"inlet_connections": [2, 2], "outlet_connections": [1, 1], "auxiliary": [0, 1]},
        "provides_flow_evidence": True,
        "evidence_confidence": 0.75,
        "safety_critical": False,
    },

    "blower": {
        "function": "air_movement",
        "creates_flow": True,
        "flow_direction": "unidirectional",
        "active_equipment": True,
        "universal_requirements": [],
        "expected_degree": {"inlet_connections": [1, 1], "outlet_connections": [1, 1], "auxiliary": [0, 1]},
        "provides_flow_evidence": True,
        "evidence_confidence": 0.75,
        "safety_critical": False,
    },

    "fan": {
        "function": "air_circulation",
        "creates_flow": True,
        "flow_direction": "unidirectional",
        "active_equipment": True,
        "universal_requirements": [],
        "expected_degree": {"inlet_connections": [1, 1], "outlet_connections": [1, 1], "auxiliary": [0, 1]},
        "provides_flow_evidence": True,
        "evidence_confidence": 0.70,
        "safety_critical": False,
    },

    # ── Storage vessels ───────────────────────────────────────────────────────
    "tank": {
        "function": "storage",
        "description": "Process vessel used to collect, buffer, or store fluid between process steps.",
        "why_needed": "Provides surge capacity, decouples upstream and downstream process rates, and acts as a suction source for pumps.",
        "typical_location": "Typically gravity-fed from upstream condensers or return lines; feeds pump suctions on the outlet side.",
        "creates_flow": False,
        "flow_direction": "bidirectional",
        "active_equipment": False,
        "universal_requirements": [
            {
                "equipment_category": "pressure_protection",
                "max_hops": 5,
                "reason": "overpressure_or_vacuum_protection",
                "severity": "CRITICAL",
                "exception_conditions": [],
            },
        ],
        "expected_degree": {
            "inlet_connections": [1, 5],
            "outlet_connections": [1, 5],
            "auxiliary": [1, 10],
        },
        "spatial_constraints": {
            "vent_position": "above_tank_top",
            "drain_position": "below_tank_bottom",
        },
        "provides_flow_evidence": False,
        "safety_critical": True,
        "failure_mode": "overpressure_or_vacuum",
        "protection_required": ["overpressure_relief", "vacuum_break"],
        "bbox_width_threshold": 100.0,  # small tanks treated as pumps in equipment_flow.py
        "corpus_parameters": {
            "typical_vent_distance": None,
            "typical_auxiliary_count": None,
        },
    },

    # ── Check valves / backflow prevention ────────────────────────────────────
    "check_valve": {
        "function": "backflow_prevention",
        "description": "Passive one-way valve that opens on forward flow and slams shut to block reverse flow.",
        "why_needed": "Placed on pump discharge to prevent reverse flow that could spin the pump backwards, cause water hammer, or contaminate the suction source.",
        "typical_location": "Immediately downstream of a pump discharge, before the isolation valve, within 5-10 pipe hops.",
        "creates_flow": False,
        "flow_direction": "unidirectional",
        "active_equipment": False,
        "universal_requirements": [],
        "expected_degree": {"inlet_connections": [1, 1], "outlet_connections": [1, 1], "auxiliary": [0, 0]},
        "provides_flow_evidence": True,
        "evidence_confidence": 0.85,
        "evidence_type": "check_valve_semantics",
        "safety_critical": True,
        "failure_mode": "allows_backflow",
    },

    "inferred_inline_equipment": {
        "function": "inline_flow_component",
        "description": "In-line process component (strainer, filter, orifice, or similar) inferred from drawing geometry.",
        "why_needed": "Provides flow conditioning, measurement, or protection at that specific pipe location.",
        "typical_location": "Inline on pipe runs, typically near pumps (suction strainer) or measurement points.",
        "creates_flow": False,
        "flow_direction": "unidirectional",
        "active_equipment": False,
        "universal_requirements": [],
        "expected_degree": {"inlet_connections": [1, 1], "outlet_connections": [1, 1], "auxiliary": [0, 1]},
        "provides_flow_evidence": False,
        "safety_critical": False,
    },

    "nrv": {
        "function": "backflow_prevention",
        "creates_flow": False,
        "flow_direction": "unidirectional",
        "active_equipment": False,
        "universal_requirements": [],
        "expected_degree": {"inlet_connections": [1, 1], "outlet_connections": [1, 1], "auxiliary": [0, 0]},
        "provides_flow_evidence": True,
        "evidence_confidence": 0.85,
        "safety_critical": True,
    },

    "non_return_valve": {
        "function": "backflow_prevention",
        "creates_flow": False,
        "flow_direction": "unidirectional",
        "active_equipment": False,
        "universal_requirements": [],
        "expected_degree": {"inlet_connections": [1, 1], "outlet_connections": [1, 1], "auxiliary": [0, 0]},
        "provides_flow_evidence": True,
        "evidence_confidence": 0.85,
        "safety_critical": True,
    },

    # GAP-4 FIX: 'non_return' and 'check' added
    "non_return": {
        "function": "backflow_prevention",
        "creates_flow": False,
        "flow_direction": "unidirectional",
        "active_equipment": False,
        "universal_requirements": [],
        "expected_degree": {"inlet_connections": [1, 1], "outlet_connections": [1, 1], "auxiliary": [0, 0]},
        "provides_flow_evidence": True,
        "evidence_confidence": 0.85,
        "safety_critical": True,
    },

    "check": {
        "function": "backflow_prevention",
        "creates_flow": False,
        "flow_direction": "unidirectional",
        "active_equipment": False,
        "universal_requirements": [],
        "expected_degree": {"inlet_connections": [1, 1], "outlet_connections": [1, 1], "auxiliary": [0, 0]},
        "provides_flow_evidence": True,
        "evidence_confidence": 0.80,
        "safety_critical": True,
    },

    # NEW-B: inferred check valve from Phase 1 classify_equipment
    "inferred_check_valve": {
        "function": "backflow_prevention",
        "description": "Check valve whose presence was inferred by Phase 1 from drawing geometry rather than an explicit symbol label.",
        "why_needed": "Prevents backflow on pump discharge. Labelled as inferred — requires site verification to confirm it is a check valve and not a different inline component.",
        "typical_location": "On pump discharge lines, typically within 5 pipe hops of the pump outlet.",
        "creates_flow": False,
        "flow_direction": "unidirectional",
        "active_equipment": False,
        "universal_requirements": [],
        "expected_degree": {"inlet_connections": [1, 1], "outlet_connections": [1, 1], "auxiliary": [0, 0]},
        "provides_flow_evidence": True,
        "evidence_confidence": 0.70,  # lower confidence — label was inferred
        "evidence_type": "check_valve_semantics",
        "safety_critical": True,
        "failure_mode": "allows_backflow",
    },

    # ── Isolation / control valves ────────────────────────────────────────────
    "valve": {
        "function": "flow_isolation",
        "description": "Manual or actuated device that can stop, start, or divert flow in a pipe.",
        "why_needed": "Required for maintenance isolation (shut down equipment without draining the system), process control (regulate flow rate), and emergency shutdown (close off hazardous flow).",
        "typical_location": "On both the inlet and outlet of major equipment (pumps, tanks, exchangers) and at branch-off points in headers.",
        "creates_flow": False,
        "flow_direction": "bidirectional",
        "active_equipment": False,
        "universal_requirements": [],
        "expected_degree": {"inlet_connections": [1, 1], "outlet_connections": [1, 1], "auxiliary": [0, 0]},
        "provides_flow_evidence": False,
        "safety_critical": False,
    },

    "instrumentation": {
        "function": "measurement_and_monitoring",
        "description": "Instrument symbol representing a measurement device (pressure, temperature, flow, level) or control element.",
        "why_needed": "Provides the process data needed for control, alarm, and safety interlock systems. Without instruments, operators cannot monitor process conditions or detect hazardous deviations.",
        "typical_location": "Attached to pipe runs, vessel nozzles, or equipment connections. Process variable instruments are typically within 2 pipe hops of the equipment they monitor.",
        "creates_flow": False,
        "flow_direction": None,
        "active_equipment": False,
        "universal_requirements": [],
        "expected_degree": {"connections": [1, 2], "auxiliary": [0, 1]},
        "provides_flow_evidence": False,
        "safety_critical": True,  # Instruments can be part of safety instrumented systems
        "failure_mode": "no_process_visibility_or_loss_of_control",
    },

    "general": {
        "function": "unclassified_process_symbol",
        "description": "Unclassified P&ID symbol — could be a nozzle, reducer, fitting, inline component, or symbol not recognised by the classifier.",
        "why_needed": "Represents a physical component whose type could not be definitively determined from the drawing geometry. Requires engineer review to confirm function.",
        "typical_location": "Varies — appears wherever the drawing contains a symbol shape not matching a known equipment template.",
        "creates_flow": False,
        "flow_direction": "context_dependent",
        "active_equipment": False,
        "universal_requirements": [],
        "expected_degree": {"connections": [1, 4], "auxiliary": [0, 2]},
        "provides_flow_evidence": False,
        "safety_critical": False,
    },

    "crossing": {
        "function": "pipe_crossing_junction",
        "description": "Represents a point where two or more pipe runs cross or branch, forming a junction topology node.",
        "why_needed": "Created automatically from the drawing topology when pipe paths share a common node. Not a physical component — it represents a routing junction in the pipe network.",
        "typical_location": "Wherever the P&ID shows a pipe intersection, T-junction, or branch-off from a header.",
        "creates_flow": False,
        "flow_direction": "bidirectional",
        "active_equipment": False,
        "universal_requirements": [],
        "expected_degree": {"connections": [3, 6]},
        "provides_flow_evidence": False,
        "safety_critical": False,
    },

    "arrow": {
        "function": "flow_direction_indicator",
        "description": "Drawing symbol indicating the intended flow direction on a pipe run. Used as primary evidence for flow direction analysis.",
        "why_needed": "Required by drafting standards on long pipe runs and wherever flow direction is not obvious. Provides the seed data for the flow propagation algorithm.",
        "typical_location": "Inline on pipe runs, typically mid-span. Always has exactly 2 pipe connections (inlet and outlet).",
        "creates_flow": False,
        "flow_direction": "unidirectional",
        "active_equipment": False,
        "universal_requirements": [],
        "expected_degree": {"connections": [2, 2]},
        "provides_flow_evidence": True,
        "evidence_confidence": 0.90,
        "evidence_type": "explicit_direction_arrow",
        "safety_critical": False,
    },

    "control_valve": {
        "function": "flow_regulation",
        "description": "Automatically actuated valve that modulates flow rate in response to a control signal (pressure, level, flow, or temperature controller output).",
        "why_needed": "Required wherever continuous flow rate adjustment is needed for process control — e.g., maintaining level in a tank, controlling discharge pressure, or throttling recirculation.",
        "typical_location": "On main process streams leaving/entering controlled vessels; on recirculation bypass lines.",
        "creates_flow": False,
        "flow_direction": "unidirectional",
        "active_equipment": False,
        "universal_requirements": [],
        "expected_degree": {"inlet_connections": [1, 1], "outlet_connections": [1, 1], "auxiliary": [0, 1]},
        "provides_flow_evidence": False,
        "safety_critical": False,
    },

    "orifice_plate": {
        "function": "flow_measurement",
        "creates_flow": False,
        "flow_direction": "unidirectional",
        "active_equipment": False,
        "universal_requirements": [
            {
                "equipment": "control_valve",
                "directional": "REVERSE",
                "max_hops": 3,
                "reason": "valve_downstream_disturbs_measurement",
                "severity": "HIGH",
            },
        ],
        "expected_degree": {"inlet_connections": [1, 1], "outlet_connections": [1, 1], "auxiliary": [1, 2]},
        "provides_flow_evidence": False,
        "safety_critical": False,
    },

    "inlet/outlet": {
        "function": "system_boundary",
        "description": "External system interface — represents a pipe that enters or leaves the drawing boundary, connecting to another P&ID or external system.",
        "why_needed": "Every P&ID is a section of a larger plant; inlet/outlet nodes define where this drawing's pipe network connects to the rest of the plant. Always degree=1 by design.",
        "typical_location": "At the drawing border (edge of the P&ID sheet). Feeds or receives from adjacent drawings.",
        "creates_flow": False,
        "flow_direction": "context_dependent",
        "active_equipment": False,
        "universal_requirements": [],
        "expected_degree": {"connections": [1, 1], "auxiliary": [0, 0]},
        "provides_flow_evidence": True,
        "safety_critical": False,
    },
}


SKID_CONTEXT: Dict[str, Dict[str, Any]] = {

    "CONDENSATE": {
        "description": "Atmospheric pressure condensate collection and return",

        "pump": {
            "required_downstream": [
                {
                    "equipment": "check_valve",
                    "max_hops": 5,
                    "typical_hops": None,
                    "reason": "backflow_prevention",
                    "severity": "CRITICAL",
                },
                {
                    "equipment": "isolation_valve",
                    "max_hops": 8,
                    "typical_hops": None,
                    "reason": "maintenance_isolation",
                    "severity": "HIGH",
                },
            ],
            "required_upstream": [
                {
                    "equipment": "suction_strainer",
                    "max_hops": 3,
                    "reason": "debris_protection",
                    "severity": "MEDIUM",
                    "exception_conditions": ["clean_condensate_service"],
                },
            ],
            "typical_head": [10, 50],
            "recirculation_frequency": None,
        },

        # NEW-A FIX: 'tank' entry with pump rules for small tank nodes.
        # Small 'tank' nodes (width < 100px) are condensate pump units.
        # Phase 1 stamps functional_label='pump' on them, so engineering_rules.py
        # will look them up as 'pump' (above).  This 'tank' entry ensures that
        # any fallback code using raw label 'tank' for rule lookup also sees
        # pump-level validation requirements rather than the universal storage
        # vessel requirements.
        "tank": {
            "required_downstream": [
                {
                    "equipment": "check_valve",
                    "max_hops": 5,
                    "reason": "backflow_prevention",
                    "severity": "CRITICAL",
                },
                {
                    "equipment": "isolation_valve",
                    "max_hops": 8,
                    "reason": "maintenance_isolation",
                    "severity": "HIGH",
                },
            ],
            "required_upstream": [
                {
                    "equipment": "suction_strainer",
                    "max_hops": 3,
                    "reason": "debris_protection",
                    "severity": "MEDIUM",
                    "exception_conditions": ["clean_condensate_service"],
                },
            ],
            "required_connections": [
                {
                    "connection_type": "vent",
                    "spatial_constraint": "highest_point",
                    "max_distance_from_top": 50,
                    "reason": "atmospheric_pressure_equalization",
                    "severity": "HIGH",
                },
                {
                    "connection_type": "drain",
                    "spatial_constraint": "lowest_point",
                    "max_distance_from_bottom": 50,
                    "reason": "complete_drainage",
                    "severity": "MEDIUM",
                },
                {
                    "connection_type": "level_instrument",
                    "max_hops": 2,
                    "reason": "level_monitoring_pump_protection",
                    "severity": "MEDIUM",
                },
            ],
        },
    },

    "STEAM": {
        "description": "High-pressure steam generation and distribution",

        "pump": {
            "required_downstream": [
                {"equipment": "check_valve", "max_hops": 5, "reason": "backflow_prevention", "severity": "CRITICAL"},
            ],
            "typical_head": [20, 100],
        },

        "tank": {
            "tank_type": "pressure_vessel",
            "required_connections": [
                {
                    "connection_type": "safety_relief_valve",
                    "spatial_constraint": "highest_point",
                    "max_distance_from_top": 30,
                    "reason": "overpressure_protection",
                    "severity": "CRITICAL",
                },
                {
                    "connection_type": "pressure_gauge",
                    "max_hops": 2,
                    "reason": "pressure_monitoring",
                    "severity": "HIGH",
                },
                {
                    "connection_type": "level_instrument",
                    "max_hops": 2,
                    "reason": "steam_drum_level_control",
                    "severity": "CRITICAL",
                },
            ],
        },
    },

    "CHEMICAL_REACTOR": {
        "description": "High-pressure chemical processing systems",

        "pump": {
            "required_downstream": [
                {"equipment": "check_valve",           "max_hops": 3, "reason": "backflow_prevention_high_pressure", "severity": "CRITICAL"},
                {"equipment": "pressure_relief_valve", "max_hops": 5, "reason": "overpressure_protection",           "severity": "CRITICAL"},
                {"equipment": "pressure_gauge",        "max_hops": 3, "reason": "pressure_monitoring",               "severity": "HIGH"},
            ],
            "required_upstream": [
                {"equipment": "strainer", "max_hops": 2, "reason": "catalyst_protection", "severity": "CRITICAL"},
            ],
            "typical_head": [50, 200],
        },

        "tank": {
            "tank_type": "pressure_vessel",
            "required_connections": [
                {
                    "connection_type": "pressure_relief_valve",
                    "spatial_constraint": "highest_point",
                    "max_distance_from_top": 30,
                    "reason": "ASME_Section_VIII_compliance",
                    "severity": "CRITICAL",
                },
                {"connection_type": "pressure_gauge", "max_hops": 2, "reason": "pressure_monitoring", "severity": "CRITICAL"},
                {"connection_type": "rupture_disk",   "max_hops": 3, "reason": "catastrophic_overpressure_protection", "severity": "CRITICAL",
                 "exception_conditions": ["low_pressure_service"]},
            ],
        },
    },

    "COOLING_WATER": {
        "description": "Recirculating cooling water systems",

        "pump": {
            "required_downstream": [
                {"equipment": "check_valve", "max_hops": 4, "reason": "backflow_prevention", "severity": "HIGH"},
            ],
            "recirculation_frequency": None,
        },

        "tank": {
            "required_connections": [
                {"connection_type": "overflow",     "max_hops": 2, "reason": "surge_capacity_management",  "severity": "HIGH"},
                {"connection_type": "makeup_water", "max_hops": 3, "reason": "evaporation_compensation",   "severity": "MEDIUM"},
            ],
        },
    },
}


PROCESS_CONTEXT: Dict[str, Dict[str, Any]] = {

    "CRYOGENIC": {
        "description": "Low-temperature service (<-100°C)",
        "applies_to_skid_types": ["CHEMICAL_REACTOR", "CONDENSATE"],
        "overrides": {
            "pump": {
                "additional_requirements": [
                    {"equipment": "warming_coil", "max_hops": 2, "reason": "prevent_ice_formation_in_seals", "severity": "CRITICAL"},
                ],
            },
            "tank": {
                "required_connections": [
                    {"connection_type": "pressure_building_coil", "reason": "maintain_tank_pressure_at_low_temp", "severity": "CRITICAL"},
                ],
            },
        },
    },

    "HIGH_TEMPERATURE": {
        "description": "High-temperature service (>300°C)",
        "applies_to_skid_types": ["CHEMICAL_REACTOR", "STEAM"],
        "overrides": {
            "pump": {
                "additional_requirements": [
                    {"equipment": "cooling_jacket", "max_hops": 1, "reason": "bearing_protection_high_temp", "severity": "CRITICAL"},
                ],
            },
        },
    },

    "CORROSIVE": {
        "description": "Corrosive fluid service",
        "applies_to_skid_types": ["CHEMICAL_REACTOR"],
        "overrides": {
            "pump": {
                "additional_requirements": [
                    {"equipment": "flushing_connection", "max_hops": 2, "reason": "seal_flush_corrosive_service", "severity": "HIGH"},
                ],
            },
        },
    },
}


def get_equipment_rules(
    equipment_label: str,
    skid_type: str,
    process_conditions: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Resolve equipment rules with full context inheritance.
    Universal → Skid → Process.
    """
    rules = copy.deepcopy(UNIVERSAL_EQUIPMENT.get(equipment_label, {}))

    if skid_type in SKID_CONTEXT:
        skid_rules = SKID_CONTEXT[skid_type].get(equipment_label, {})
        rules = _merge_rules(rules, skid_rules)

    if process_conditions:
        for condition in process_conditions:
            if condition in PROCESS_CONTEXT:
                process_spec = PROCESS_CONTEXT[condition]
                if skid_type in process_spec.get("applies_to_skid_types", []):
                    overrides = process_spec["overrides"].get(equipment_label, {})
                    rules = _merge_rules(rules, overrides)

    return rules


def _merge_rules(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """
    Deep merge with intelligent list concatenation for requirements.
    """
    result = copy.deepcopy(base)

    for key, value in override.items():
        if key in ("required_downstream", "required_upstream", "required_connections"):
            result[key] = result.get(key, []) + value
        elif key == "additional_requirements":
            result["required_downstream"] = result.get("required_downstream", []) + value
        elif isinstance(value, dict) and key in result and isinstance(result[key], dict):
            result[key] = _merge_rules(result[key], value)
        else:
            result[key] = value

    return result


def get_all_equipment_labels() -> List[str]:
    """Return all equipment labels defined in UNIVERSAL_EQUIPMENT."""
    return list(UNIVERSAL_EQUIPMENT.keys())


def get_equipment_flow_labels() -> Dict[str, Dict[str, Any]]:
    """
    Return equipment labels in the format expected by equipment_flow.py.
    Maps UNIVERSAL_EQUIPMENT to the legacy EQUIPMENT_LABELS structure.
    Only includes equipment with provides_flow_evidence=True.
    """
    result = {}
    for label, spec in UNIVERSAL_EQUIPMENT.items():
        if spec.get("provides_flow_evidence", False) and spec.get("active_equipment", False):
            result[label] = {
                "confidence": spec.get("evidence_confidence", 0.70),
                "category":   "active",
            }
            if label == "tank" and "bbox_width_threshold" in spec:
                result[label]["bbox_width_max"] = spec["bbox_width_threshold"]
    return result


def get_check_valve_labels() -> Dict[str, float]:
    """
    Return check valve labels in the format expected by equipment_flow.py.
    GAP-4 FIX: Now includes 'non_return' and 'check' since they are in
    UNIVERSAL_EQUIPMENT with function='backflow_prevention'.
    """
    result = {}
    for label, spec in UNIVERSAL_EQUIPMENT.items():
        if spec.get("function") == "backflow_prevention":
            result[label] = spec.get("evidence_confidence", 0.85)
    return result