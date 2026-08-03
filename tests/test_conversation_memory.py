import unittest

from app.conversation_memory import InMemoryConversationStore


class ConversationMemoryStoreTest(unittest.TestCase):
    def test_store_keeps_only_latest_ten_turns(self):
        store = InMemoryConversationStore(max_turns=10)
        key = (7, 41, "conversation-a")

        for index in range(12):
            store.append(key, {"turn": index})

        turns = store.get(key)
        self.assertEqual(len(turns), 10)
        self.assertEqual(turns[0]["turn"], 2)
        self.assertEqual(turns[-1]["turn"], 11)

    def test_store_isolates_user_company_and_conversation(self):
        store = InMemoryConversationStore()
        store.append((7, 41, "conversation-a"), {"value": "allowed"})

        self.assertEqual(
            store.get((7, 41, "conversation-a")),
            [{"value": "allowed"}],
        )
        self.assertEqual(store.get((8, 41, "conversation-a")), [])
        self.assertEqual(store.get((7, 42, "conversation-a")), [])
        self.assertEqual(store.get((7, 41, "conversation-b")), [])

    def test_store_expires_inactive_conversation(self):
        now = [100.0]
        store = InMemoryConversationStore(
            ttl_seconds=60,
            clock=lambda: now[0],
        )
        key = (7, 41, "conversation-a")
        store.append(key, {"value": "temporary"})

        now[0] = 161.0

        self.assertEqual(store.get(key), [])


if __name__ == "__main__":
    unittest.main()
