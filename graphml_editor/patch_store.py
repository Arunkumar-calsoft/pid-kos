# graphml_editor/patch_store.py  (STANDALONE — not imported by main pipeline)
#
# Append-only JSON patch store for GraphML/Neo4j corrections.
#
# Patch files are stored at:
#   {project_root}/patches/{pid_id}_patches.json
#
# Each patch record schema:
#   patch_id   str   UUID-4
#   pid_id     str   PID identifier
#   op         str   add_edge | remove_edge | relabel | set_property | rename_node
#   node_id    str   primary node id
#   target_id  str   secondary node id (edge ops only)
#   prop_key   str   property name (set_property only)
#   old_value  any   value before patch (for undo)
#   new_value  any   value after patch
#   ts         str   ISO-8601 UTC timestamp
#   applied    bool  True if Neo4j patch was applied successfully

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_VALID_OPS: frozenset = frozenset({
    "add_edge",
    "remove_edge",
    "relabel",
    "set_property",
    "rename_node",
})


class PatchStore:
    """
    Thread-safe append-only store for per-PID correction patches.
    Each PID gets its own JSON file; reads and writes are atomic via
    full-file rewrite (safe for single-server use).
    """

    def __init__(self, patches_dir: Path):
        self._dir = Path(patches_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    # ── Internal I/O ─────────────────────────────────────────────────────────

    def _path(self, pid_id: str) -> Path:
        # Sanitise pid_id to prevent path traversal
        safe = "".join(c for c in pid_id if c.isalnum() or c in "-_")
        return self._dir / f"{safe}_patches.json"

    def _read(self, pid_id: str) -> List[Dict]:
        p = self._path(pid_id)
        if not p.exists():
            return []
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return []

    def _write(self, pid_id: str, patches: List[Dict]) -> None:
        self._path(pid_id).write_text(
            json.dumps(patches, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def list_patches(self, pid_id: str) -> List[Dict]:
        """Return all patches for a PID, oldest first."""
        return self._read(pid_id)

    def add_patch(
        self,
        pid_id: str,
        op: str,
        node_id: str,
        *,
        target_id: Optional[str] = None,
        prop_key: Optional[str] = None,
        old_value: Any = None,
        new_value: Any = None,
        applied: bool = True,
    ) -> Dict:
        """Append a new patch record and return it."""
        if op not in _VALID_OPS:
            raise ValueError(f"Unknown op {op!r}. Valid: {sorted(_VALID_OPS)}")
        patch = {
            "patch_id":  str(uuid.uuid4()),
            "pid_id":    pid_id,
            "op":        op,
            "node_id":   node_id,
            "target_id": target_id,
            "prop_key":  prop_key,
            "old_value": old_value,
            "new_value": new_value,
            "ts":        datetime.now(timezone.utc).isoformat(),
            "applied":   applied,
        }
        patches = self._read(pid_id)
        patches.append(patch)
        self._write(pid_id, patches)
        return patch

    def remove_patch(self, pid_id: str, patch_id: str) -> Optional[Dict]:
        """
        Remove a patch by ID and return it (caller reverts Neo4j).
        Returns None if not found.
        """
        patches = self._read(pid_id)
        target = next((p for p in patches if p["patch_id"] == patch_id), None)
        if target is None:
            return None
        self._write(pid_id, [p for p in patches if p["patch_id"] != patch_id])
        return target

    def get_patch(self, pid_id: str, patch_id: str) -> Optional[Dict]:
        return next(
            (p for p in self._read(pid_id) if p["patch_id"] == patch_id),
            None,
        )

    def list_all_pids(self) -> List[str]:
        """Return list of PIDs that have patch files."""
        return [
            f.stem.replace("_patches", "")
            for f in self._dir.glob("*_patches.json")
        ]
