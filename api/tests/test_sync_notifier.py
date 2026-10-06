from __future__ import annotations

import asyncio
import unittest

from api.app.modules.sync.notifier import SyncNotifier


class _Socket:
    def __init__(self, fail: bool = False):
        self.sent: list[dict] = []
        self.fail = fail

    async def send_json(self, payload: dict) -> None:
        if self.fail:
            raise RuntimeError("conexao morta")
        self.sent.append(payload)


class SyncNotifierTests(unittest.TestCase):
    def test_burst_of_commits_becomes_one_notice_with_the_highest_seq(self):
        async def scenario():
            notifier = SyncNotifier(debounce_seconds=0.02)
            socket = _Socket()
            notifier.register(socket)
            for seq in (3, 5, 4):
                notifier.notify_committed(seq)
            await asyncio.sleep(0.1)
            return socket.sent

        self.assertEqual(asyncio.run(scenario()), [{"type": "sync.head", "seq": 5}])

    def test_commit_after_the_notice_sends_another_one(self):
        async def scenario():
            notifier = SyncNotifier(debounce_seconds=0.02)
            socket = _Socket()
            notifier.register(socket)
            notifier.notify_committed(1)
            await asyncio.sleep(0.08)
            notifier.notify_committed(2)
            await asyncio.sleep(0.08)
            return [payload["seq"] for payload in socket.sent]

        self.assertEqual(asyncio.run(scenario()), [1, 2])

    def test_commit_during_the_send_is_not_lost(self):
        async def scenario():
            notifier = SyncNotifier(debounce_seconds=0.02)

            class _Slow(_Socket):
                async def send_json(self, payload):
                    await super().send_json(payload)
                    if payload["seq"] == 1:
                        notifier.notify_committed(2)

            socket = _Slow()
            notifier.register(socket)
            notifier.notify_committed(1)
            await asyncio.sleep(0.15)
            return [payload["seq"] for payload in socket.sent]

        self.assertEqual(asyncio.run(scenario()), [1, 2])

    def test_dead_connection_is_dropped_and_others_still_receive(self):
        async def scenario():
            notifier = SyncNotifier(debounce_seconds=0.01)
            dead, alive = _Socket(fail=True), _Socket()
            notifier.register(dead)
            notifier.register(alive)
            notifier.notify_committed(7)
            await asyncio.sleep(0.08)
            return notifier.connection_count(), alive.sent

        self.assertEqual(asyncio.run(scenario()), (1, [{"type": "sync.head", "seq": 7}]))

    def test_seq_committed_with_nobody_listening_is_not_replayed_later(self):
        async def scenario():
            notifier = SyncNotifier(debounce_seconds=0.01)
            notifier.notify_committed(50)
            socket = _Socket()
            notifier.register(socket)
            notifier.notify_committed(3)  # ex.: banco restaurado, seq voltou atras
            await asyncio.sleep(0.08)
            return [payload["seq"] for payload in socket.sent]

        self.assertEqual(asyncio.run(scenario()), [3])

    def test_no_connections_or_no_event_loop_is_harmless(self):
        notifier = SyncNotifier()
        notifier.notify_committed(1)
        notifier.register(_Socket())
        notifier.notify_committed(2)  # sem event loop rodando: nao levanta


if __name__ == "__main__":
    unittest.main()
