"""Exercise join-code recovery through SignalR without contacting ClassPoint."""

import asyncio
import json
import unittest
from types import SimpleNamespace

import aiohttp

from bridge import Bridge
from capture import Profile


class PresenterSocket:
    def __init__(self, returned_code, restarted_code, reject_restart=False):
        self.closed = False
        self.incoming = asyncio.Queue()
        self.commands = []
        self.returned_code = returned_code
        self.restarted_code = restarted_code
        self.reject_restart = reject_restart

    def deliver(self, message):
        self.incoming.put_nowait(SimpleNamespace(
            type=aiohttp.WSMsgType.TEXT, data=json.dumps(message) + "\x1e",
        ))

    async def send_str(self, data):
        message = json.loads(data.rstrip("\x1e"))
        if "protocol" in message:
            self.deliver({})
            return
        if message.get("type") == 6:
            return
        self.commands.append(message)
        target = message["target"]
        completion = {"type": 3, "invocationId": message["invocationId"]}
        if target == "PresenterRestartClass" and self.reject_restart:
            completion["error"] = "Synthetic rejection"
        elif target in {"PresenterStartSlideshow", "PresenterRestartClass"}:
            code = self.returned_code if target == "PresenterStartSlideshow" else self.restarted_code
            # The refreshed code may arrive after invocation completion.
            asyncio.get_running_loop().call_later(0.01, self.deliver, {
                "type": 1, "target": "ClassSessionUpdated",
                "arguments": [{"classCode": code, "participantList": [], "cpcsRegion": "cpcs-11"}],
            })
        self.deliver(completion)

    async def receive(self):
        return await self.incoming.get()

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.closed:
            raise StopAsyncIteration
        return await self.receive()

    async def close(self):
        self.closed = True


class UploadResponse:
    status = 201

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


class PresenterSession:
    def __init__(self, socket):
        self.socket = socket
        self.uploads = []

    async def ws_connect(self, *args, **kwargs):
        return self.socket

    def put(self, url, *, data, headers):
        self.uploads.append((url, data))
        self.socket.commands.append({"target": "upload"})
        return UploadResponse()


class JoinCodeTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.profile = Profile(
            {"email": "instructor@example.test"},
            {"classCode": "SD5913", "classLimit": 20, "savedClassId": None,
             "isAllowGuests": True, "platform": "vsto"},
            "cpcs-11", "https://storage.example.test", "sig=PRIVATE",
        )
        self.socket = PresenterSocket("OTHER01", "SD5913")
        self.session = PresenterSession(self.socket)
        self.bridge = Bridge(self.profile, self.session)
        self.config = {"slide_index": 0, "fragment_index": -1, "total_slides": 1,
                       "choices": ["A", "B"]}

    async def asyncTearDown(self):
        await self.bridge.disconnect()

    async def start(self):
        async def snapshot():
            return b"synthetic-jpeg"
        return await self.bridge.start(self.config, snapshot)

    def targets(self):
        return [message["target"] for message in self.socket.commands]

    async def test_restores_requested_code_before_uploading_or_opening_question(self):
        original_options = self.profile.class_options.copy()
        result = await self.start()
        self.assertEqual(result["class_code"], "SD5913")
        self.assertEqual(result["phase"], "open")
        self.assertEqual(self.targets(), [
            "PresenterStartSlideshow", "PresenterRestartClass", "upload",
            "PresenterGotoStep", "PresenterStartActivity",
        ])
        self.assertEqual(self.socket.commands[1]["arguments"], [
            {"email": "instructor@example.test", "toolbarActions": None},
            {"classCode": "SD5913", "classLimit": 20, "savedClassId": None,
             "isAllowGuests": True, "platform": "vsto", "isSaveGuests": False,
             "shouldResetStars": False},
        ])
        self.assertEqual(self.profile.class_options, original_options)
        for private in ("instructor@example.test", "sig=PRIVATE"):
            self.assertNotIn(private, json.dumps(result))

    async def test_matching_code_does_not_restart_class(self):
        self.socket.returned_code = "sd5913"
        result = await self.start()
        self.assertEqual(result["class_code"], "sd5913")
        self.assertNotIn("PresenterRestartClass", self.targets())

    async def test_class_only_start_verifies_code_without_opening_or_ending_an_activity(self):
        self.profile.class_options["classCode"] = "SD2112"
        self.socket.restarted_code = "SD2112"
        config = {"slide_index": 0, "fragment_index": -1, "total_slides": 1}
        async def snapshot():
            return b"synthetic-jpeg"
        result = await self.bridge.start(config, snapshot, open_question=False)
        self.assertEqual(result["class_code"], "SD2112")
        self.assertEqual(result["phase"], "closed")
        self.assertTrue(result["can_end"])
        self.assertIsNone(result["active_slide"])
        self.assertIsNone(result["activity_type"])
        self.assertIsNone(self.bridge.active_activity)
        self.assertFalse(self.bridge.activity_started)
        self.assertEqual(self.targets(), [
            "PresenterStartSlideshow", "PresenterRestartClass", "upload", "PresenterGotoStep",
        ])
        await self.bridge.end()
        self.assertEqual(self.targets(), [
            "PresenterStartSlideshow", "PresenterRestartClass", "upload", "PresenterGotoStep",
            "PresenterEndSlideshow",
        ])
        self.assertEqual(self.bridge.phase, "ended")

    async def test_unconfigured_code_accepts_returned_code_without_restart(self):
        self.profile.class_options["classCode"] = None
        result = await self.start()
        self.assertEqual(result["class_code"], "OTHER01")
        self.assertNotIn("PresenterRestartClass", self.targets())

    async def test_persistent_mismatch_ends_class_without_upload_or_activity(self):
        self.socket.restarted_code = "STILLWRONG"
        with self.assertRaisesRegex(RuntimeError, "join code"):
            await self.start()
        self.assertEqual(self.targets(), [
            "PresenterStartSlideshow", "PresenterRestartClass", "PresenterEndSlideshow",
        ])
        self.assertFalse(self.bridge.class_started)
        self.assertIsNone(self.bridge.class_code)
        self.assertEqual(self.session.uploads, [])

    async def test_rejected_restart_ends_class_without_upload_or_activity(self):
        self.socket.reject_restart = True
        with self.assertRaisesRegex(RuntimeError, "rejected"):
            await self.start()
        self.assertEqual(self.targets(), [
            "PresenterStartSlideshow", "PresenterRestartClass", "PresenterEndSlideshow",
        ])
        self.assertFalse(self.bridge.class_started)
        self.assertEqual(self.session.uploads, [])


if __name__ == "__main__":
    unittest.main()
