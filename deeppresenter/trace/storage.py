from __future__ import annotations

import json
from pathlib import Path

from .structures import ActionTraceEntry


class TraceStorage:
    """Persistent storage for action traces."""

    def __init__(self, storage_dir: Path | str | None = None):
        if storage_dir is None:
            storage_dir = Path.home() / ".pptagent" / "traces"
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._current_trace: list[ActionTraceEntry] = []
        self._trace_id: int = 0

    def start_trace(self, session_id: str) -> str:
        """Start a new trace session. Returns the trace ID."""
        self._trace_id += 1
        self._current_trace = []
        return f"trace_{session_id}_{self._trace_id}"

    def record(self, entry: ActionTraceEntry) -> str:
        """Record an action entry. Returns the entry's action_id."""
        self._current_trace.append(entry)
        return entry.action_id

    def get_trace(self) -> list[ActionTraceEntry]:
        """Get all entries in the current trace."""
        return list(self._current_trace)

    def get_action(self, action_id: str) -> ActionTraceEntry | None:
        """Get a single action by ID."""
        for entry in self._current_trace:
            if entry.action_id == action_id:
                return entry
        return None

    def save(self, trace_id: str) -> Path:
        """Save the current trace to a JSON file. Returns the file path."""
        path = self.storage_dir / f"{trace_id}.json"
        data = {
            "trace_id": trace_id,
            "entries": [e.to_dict() for e in self._current_trace],
            "stats": self._compute_stats(),
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return path

    def load(self, trace_id: str) -> list[ActionTraceEntry]:
        """Load a trace from a JSON file."""
        path = self.storage_dir / f"{trace_id}.json"
        if not path.exists():
            return []
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        entries = []
        for e in data.get("entries", []):
            entries.append(ActionTraceEntry(
                action_id=e["action_id"],
                action_type=e["action_type"],
                target_slide=e["target_slide"],
                pre_state=e.get("pre_state", {}),
                post_state=e.get("post_state", {}),
                parameters=e.get("parameters", {}),
                token_count=e.get("token_count", 0),
                verification_status=e.get("verification_status", "pending"),
                violations=e.get("violations", []),
            ))
        return entries

    def _compute_stats(self) -> dict:
        """Compute statistics for the current trace."""
        total_tokens = sum(e.token_count for e in self._current_trace)
        violations = sum(len(e.violations) for e in self._current_trace)
        status_counts: dict[str, int] = {}
        for e in self._current_trace:
            status_counts[e.verification_status] = status_counts.get(e.verification_status, 0) + 1
        return {
            "total_actions": len(self._current_trace),
            "total_tokens": total_tokens,
            "total_violations": violations,
            "verification_status": status_counts,
        }
