from collections import deque
from copy import deepcopy
from threading import RLock
from time import monotonic
from typing import Any, Callable

from app.config import (
    CONVERSATION_MAX_SESSIONS,
    CONVERSATION_MAX_TURNS,
    CONVERSATION_TTL_SECONDS,
)

ConversationKey = tuple[int, int, str]


class InMemoryConversationStore:
    def __init__(
        self,
        *,
        max_turns: int = 10,
        ttl_seconds: int = 3600,
        max_conversations: int = 1000,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self._max_turns = max_turns
        self._ttl_seconds = ttl_seconds
        self._max_conversations = max_conversations
        self._clock = clock
        self._lock = RLock()
        self._turns: dict[ConversationKey, deque[dict[str, Any]]] = {}
        self._expires_at: dict[ConversationKey, float] = {}

    def _remove_expired(self, now: float) -> None:
        expired_keys = [
            key
            for key, expires_at in self._expires_at.items()
            if expires_at <= now
        ]
        for key in expired_keys:
            self._turns.pop(key, None)
            self._expires_at.pop(key, None)

    def _remove_oldest_conversation(self) -> None:
        if not self._expires_at:
            return
        oldest_key = min(self._expires_at, key=self._expires_at.get)
        self._turns.pop(oldest_key, None)
        self._expires_at.pop(oldest_key, None)

    def get(self, key: ConversationKey) -> list[dict[str, Any]]:
        with self._lock:
            now = self._clock()
            self._remove_expired(now)
            turns = self._turns.get(key)
            if turns is None:
                return []
            self._expires_at[key] = now + self._ttl_seconds
            return deepcopy(list(turns))

    def append(self, key: ConversationKey, turn: dict[str, Any]) -> None:
        with self._lock:
            now = self._clock()
            self._remove_expired(now)
            if key not in self._turns and len(self._turns) >= self._max_conversations:
                self._remove_oldest_conversation()
            turns = self._turns.setdefault(
                key,
                deque(maxlen=self._max_turns),
            )
            turns.append(deepcopy(turn))
            self._expires_at[key] = now + self._ttl_seconds

    def clear(self, key: ConversationKey) -> None:
        with self._lock:
            self._turns.pop(key, None)
            self._expires_at.pop(key, None)


conversation_store = InMemoryConversationStore(
    max_turns=CONVERSATION_MAX_TURNS,
    ttl_seconds=CONVERSATION_TTL_SECONDS,
    max_conversations=CONVERSATION_MAX_SESSIONS,
)
