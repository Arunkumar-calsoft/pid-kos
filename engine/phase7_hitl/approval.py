# engine/phase7_hitl/approval.py
#
# Phase 7: Human-in-the-Loop Approval
#
# DIAGRAM COMPONENT: "Phase 7 — Human Approval" (p7)
# DIAGRAM FLOWS:
#   Phase 6 → Phase 7  (C11): trace logs + violations → human queue
#   Phase 7 → Global Registry (C12): approved changes → graph update
#
# PURPOSE:
#   Builds a queue of items requiring human review from:
#     1. Engineering rule violations (Phase 3.5) — severity HIGH or CRITICAL
#     2. KAV rarity annotations with hitl_severity HIGH or CRITICAL
#     3. Phase 8 enrichment queue candidates (LLM-generated queries)
#
#   Each item can be:
#     - APPROVED → stamps reviewed_by, reviewed_at on the source Annotation
#     - REJECTED → stamps rejected_by, rejected_at, rejection_reason
#     - DEFERRED → remains in queue for later review
#
#   On approval, Phase 7 feeds back to the Global Registry by updating
#   the PID's Annotation nodes with human-verified status.

from __future__ import annotations

from typing import List, Dict, Optional


class HitlItem:
    """A single item in the HITL review queue."""

    __slots__ = (
        "item_id", "pid_id", "source", "pattern_type", "severity",
        "description", "annotation_id", "status", "reviewer",
        "review_note", "reviewed_at",
    )

    def __init__(
        self,
        item_id: str,
        pid_id: str,
        source: str,
        pattern_type: str,
        severity: str,
        description: str,
        annotation_id: str,
    ):
        self.item_id = item_id
        self.pid_id = pid_id
        self.source = source
        self.pattern_type = pattern_type
        self.severity = severity
        self.description = description
        self.annotation_id = annotation_id
        self.status = "PENDING"
        self.reviewer: Optional[str] = None
        self.review_note: Optional[str] = None
        self.reviewed_at: Optional[str] = None

    def to_dict(self) -> Dict:
        return {
            "item_id": self.item_id,
            "pid_id": self.pid_id,
            "source": self.source,
            "pattern_type": self.pattern_type,
            "severity": self.severity,
            "description": self.description,
            "annotation_id": self.annotation_id,
            "status": self.status,
            "reviewer": self.reviewer,
            "review_note": self.review_note,
            "reviewed_at": self.reviewed_at,
        }


class Phase7HumanApproval:
    """
    Phase 7: Human Approval with Neo4j integration.

    Builds HITL queue from graph data, supports approve/reject,
    and writes review decisions back to the Global Registry (Neo4j).
    """

    def __init__(self, session, pid_id: str):
        self.session = session
        self.pid_id = pid_id
        self.queue: List[HitlItem] = []

    def build_queue(self) -> int:
        """
        Populate the review queue from Neo4j: engineering violations +
        high-severity KAV rarity annotations.

        Returns the number of items added to the queue.
        """
        self.queue.clear()

        # Source 1: Engineering rule violations (Phase 3.5)
        violations = self.session.run(
            """
            MATCH (a:Annotation {pid_id: $pid_id, type: 'engineering_rule_violation'})
            RETURN a.id                       AS ann_id,
                   a.pattern_type             AS pattern_type,
                   a.explanation              AS explanation,
                   properties(a).hitl_status  AS hitl_status
            """,
            pid_id=self.pid_id,
        ).data()

        for v in violations:
            if v.get("hitl_status") in {"APPROVED", "REJECTED"}:
                continue
            item = HitlItem(
                item_id=f"hitl_violation_{v['ann_id']}",
                pid_id=self.pid_id,
                source="phase3_engineering_rules",
                pattern_type=v["pattern_type"],
                severity="CRITICAL",
                description=v.get("explanation") or v["pattern_type"],
                annotation_id=v["ann_id"],
            )
            self.queue.append(item)

        # Source 2: KAV rarity with HIGH/CRITICAL severity
        rarities = self.session.run(
            """
            MATCH (a:Annotation {
                pid_id: $pid_id,
                type: 'structural_pattern_rarity',
                category: 'KAV'
            })
            WHERE a.hitl_severity IN ['HIGH', 'CRITICAL']
              AND properties(a).hitl_status IS NULL
            RETURN a.id             AS ann_id,
                   a.pattern_type   AS pattern_type,
                   a.hitl_severity  AS severity,
                   a.rarity_label   AS rarity_label
            """,
            pid_id=self.pid_id,
        ).data()

        for r in rarities:
            item = HitlItem(
                item_id=f"hitl_rarity_{r['ann_id']}",
                pid_id=self.pid_id,
                source="phase3_structural_rarity",
                pattern_type=r["pattern_type"],
                severity=r["severity"],
                description=f"{r['pattern_type']} — {r.get('rarity_label', 'unknown')}",
                annotation_id=r["ann_id"],
            )
            self.queue.append(item)

        return len(self.queue)

    def approve(self, item: HitlItem, reviewer: str = "system",
                note: str = "") -> None:
        """Approve an item and write the decision back to Neo4j."""
        item.status = "APPROVED"
        item.reviewer = reviewer
        item.review_note = note

        self.session.run(
            """
            MATCH (a:Annotation {id: $ann_id})
            SET a.hitl_status    = 'APPROVED',
                a.reviewed_by    = $reviewer,
                a.review_note    = $note,
                a.reviewed_at    = datetime()
            """,
            ann_id=item.annotation_id,
            reviewer=reviewer,
            note=note,
        )

    def reject(self, item: HitlItem, reviewer: str = "system",
               reason: str = "") -> None:
        """Reject an item and write the decision back to Neo4j."""
        item.status = "REJECTED"
        item.reviewer = reviewer
        item.review_note = reason

        self.session.run(
            """
            MATCH (a:Annotation {id: $ann_id})
            SET a.hitl_status      = 'REJECTED',
                a.reviewed_by      = $reviewer,
                a.rejection_reason = $reason,
                a.reviewed_at      = datetime()
            """,
            ann_id=item.annotation_id,
            reviewer=reviewer,
            reason=reason,
        )

    def auto_approve_all(self, reviewer: str = "auto_approve") -> int:
        """Approve all pending items. Returns count of approvals."""
        count = 0
        for item in self.queue:
            if item.status == "PENDING":
                self.approve(item, reviewer=reviewer,
                             note="Auto-approved by Phase 7 orchestrator")
                count += 1
        return count

    def get_summary(self) -> Dict:
        """Return a summary of the current queue state."""
        by_status = {}
        by_severity = {}
        for item in self.queue:
            by_status[item.status] = by_status.get(item.status, 0) + 1
            by_severity[item.severity] = by_severity.get(item.severity, 0) + 1
        return {
            "pid_id": self.pid_id,
            "total": len(self.queue),
            "by_status": by_status,
            "by_severity": by_severity,
        }
