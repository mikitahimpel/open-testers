from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from dataclasses import dataclass, asdict
from datetime import datetime, timezone

DEFAULT_PATH = Path("open-testers.memory.json")
MAX_MEMORIES = 100
VALID_CATEGORIES = ("site_structure", "test_insights", "user_preferences")
VALID_IMPORTANCES = ("high", "medium", "low")

_IMPORTANCE_RANK = {"high": 0, "medium": 1, "low": 2}


@dataclass
class Memory:
    id: str
    category: str
    title: str
    content: str
    importance: str
    createdAt: str
    updatedAt: str


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class MemoryStore:
    def __init__(self, path: Path = DEFAULT_PATH):
        self.path = Path(path)

    def _load(self) -> list[dict]:
        if not self.path.exists():
            self._save([])
            return []
        try:
            with self.path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            raise RuntimeError(f"memory store corrupted at {self.path}") from e
        if not isinstance(data, dict) or "memories" not in data \
                or not isinstance(data["memories"], list):
            raise RuntimeError(f"memory store corrupted at {self.path}")
        return data["memories"]

    def _save(self, memories: list[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "memories": memories}
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        with tmp_path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        os.replace(tmp_path, self.path)

    def _sorted(self, memories: list[dict]) -> list[dict]:
        return sorted(
            memories,
            key=lambda m: (
                _IMPORTANCE_RANK.get(m.get("importance", "low"), 3),
                m.get("createdAt", ""),
            ),
        )

    def list(self) -> list[Memory]:
        raw = self._sorted(self._load())
        return [Memory(**m) for m in raw]

    def add(
        self,
        category: str,
        title: str,
        content: str,
        importance: str = "medium",
    ) -> Memory:
        if category not in VALID_CATEGORIES:
            raise ValueError(f"category must be one of {VALID_CATEGORIES}")
        if importance not in VALID_IMPORTANCES:
            raise ValueError(f"importance must be one of {VALID_IMPORTANCES}")
        if not title or not title.strip():
            raise ValueError("title must be non-empty")
        if not content or not content.strip():
            raise ValueError("content must be non-empty")

        memories = self._load()
        if len(memories) >= MAX_MEMORIES:
            raise ValueError("memory cap reached (100); delete some first")

        now = _now_iso()
        memory = Memory(
            id=str(uuid.uuid4()),
            category=category,
            title=title,
            content=content,
            importance=importance,
            createdAt=now,
            updatedAt=now,
        )
        memories.append(asdict(memory))
        self._save(memories)
        return memory

    def remove(self, memory_id: str) -> bool:
        memories = self._load()
        kept = [m for m in memories if m.get("id") != memory_id]
        if len(kept) == len(memories):
            return False
        self._save(kept)
        return True

    def to_llm_context(self, limit: int = 20) -> list[dict]:
        ordered = self._sorted(self._load())[:limit]
        return [
            {
                "category": m["category"],
                "title": m["title"],
                "content": m["content"],
                "importance": m["importance"],
            }
            for m in ordered
        ]

    def render_text(self, limit: int = 20) -> str:
        ctx = self.to_llm_context(limit=limit)
        if not ctx:
            return ""
        lines = ["## Project memory"]
        for category in VALID_CATEGORIES:
            bucket = [m for m in ctx if m["category"] == category]
            if not bucket:
                continue
            lines.append(f"### {category}")
            for m in bucket:
                lines.append(f"- [{m['importance']}] {m['title']}: {m['content']}")
        return "\n".join(lines)
