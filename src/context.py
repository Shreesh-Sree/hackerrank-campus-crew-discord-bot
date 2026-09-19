from __future__ import annotations

import collections
from typing import Any

from src.config import settings

_MAX_USERS = 1000


class ConversationMemory:
    def __init__(self, max_users: int = _MAX_USERS) -> None:
        self._store: collections.OrderedDict[int, list[dict[str, str]]] = collections.OrderedDict()
        self._max_users = max_users

    def _ensure_slot(self, user_id: int) -> list[dict[str, str]]:
        if user_id in self._store:
            self._store.move_to_end(user_id)
            return self._store[user_id]
        if len(self._store) >= self._max_users:
            self._store.popitem(last=False)
        self._store[user_id] = []
        return self._store[user_id]

    def _max_turns(self) -> int:
        return getattr(settings, "context_history_limit", 8)

    def add_user_message(self, user_id: int, content: str) -> None:
        history = self._ensure_slot(user_id)
        history.append({"role": "user", "content": content})
        limit = self._max_turns() * 2
        if len(history) > limit:
            del history[: len(history) - limit]

    def add_assistant_message(self, user_id: int, content: str) -> None:
        history = self._ensure_slot(user_id)
        history.append({"role": "assistant", "content": content})
        limit = self._max_turns() * 2
        if len(history) > limit:
            del history[: len(history) - limit]

    def get_history(self, user_id: int) -> list[dict[str, str]]:
        if user_id not in self._store:
            return []
        self._store.move_to_end(user_id)
        limit = self._max_turns() * 2
        return list(self._store[user_id][-limit:])

    def clear(self, user_id: int) -> None:
        self._store.pop(user_id, None)


memory = ConversationMemory()
