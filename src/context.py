from __future__ import annotations

import collections
import logging

from src.config import settings

log = logging.getLogger("hrcc.context")

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

    def _max_messages(self) -> int:
        return getattr(settings, "context_history_limit", 8) * 2

    def add_user_message(self, user_id: int, content: str) -> None:
        history = self._ensure_slot(user_id)
        history.append({"role": "user", "content": content})
        limit = self._max_messages()
        if len(history) > limit:
            del history[: len(history) - limit]
        self._persist(user_id, "user", content)

    def add_assistant_message(self, user_id: int, content: str) -> None:
        history = self._ensure_slot(user_id)
        history.append({"role": "assistant", "content": content})
        limit = self._max_messages()
        if len(history) > limit:
            del history[: len(history) - limit]
        self._persist(user_id, "assistant", content)

    def get_history(self, user_id: int) -> list[dict[str, str]]:
        if user_id in self._store:
            self._store.move_to_end(user_id)
            return list(self._store[user_id][-self._max_messages():])
        return self._load_from_db(user_id)

    def clear(self, user_id: int) -> None:
        self._store.pop(user_id, None)

    def _persist(self, user_id: int, role: str, content: str) -> None:
        try:
            from src.db import save_conversation_turn
            save_conversation_turn(user_id, role, content)
        except Exception:
            log.debug("DB persistence unavailable, using in-memory only")

    def _load_from_db(self, user_id: int) -> list[dict[str, str]]:
        try:
            from src.db import get_conversation_turns
            turns = get_conversation_turns(user_id, limit=self._max_messages())
            if turns:
                self._store[user_id] = turns
                if len(self._store) > self._max_users:
                    self._store.popitem(last=False)
            return turns
        except Exception:
            log.debug("DB load unavailable, returning empty history")
            return []


memory = ConversationMemory()
