from __future__ import annotations

import asyncio
import json
import secrets
import string
from collections import deque
from datetime import datetime, timezone
from typing import Awaitable, Callable

import aiohttp

from capture import Profile


ORIGIN = "https://presenter.classpoint.app"


def activity_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")[:-3]
    suffix = "".join(secrets.choice(string.ascii_uppercase) for _index in range(4))
    return f"mc{stamp}{suffix}"


class Bridge:
    def __init__(self, profile: Profile, session: aiohttp.ClientSession):
        self.profile = profile
        self.session = session
        self.socket = None
        self.receiver = None
        self.heartbeat = None
        self.pending = {}
        self.sequence = 0
        self.lock = asyncio.Lock()
        self.class_ready = asyncio.Event()
        self.resync_tasks = set()
        self.participants = {}
        self.responses = {}
        self.slide_message = None
        self.active_activity = None
        self.active_slide = None
        self.activity_choices = []
        self.class_started = False
        self.activity_started = False
        self.disconnecting = False
        self.phase = "idle"
        self.class_code = None
        self.error = None
        self.entries = deque(maxlen=24)

    def log(self, message: str) -> None:
        self.entries.append({"time": datetime.now().strftime("%H:%M:%S"), "message": message})

    def state(self) -> dict:
        return {
            "phase": self.phase,
            "class_code": self.class_code,
            "participants": len(self.participants),
            "responses": [list(value) for value in self.responses.values()],
            "error": self.error,
            "log": list(self.entries),
            "region": self.profile.region,
            "connected": bool(self.socket and not self.socket.closed),
            "can_end": self.class_started,
            "active_slide": self.active_slide,
            "activity_choices": list(self.activity_choices),
        }

    async def connect(self) -> None:
        self.disconnecting = False
        self.socket = await self.session.ws_connect(
            self.profile.hub_url, origin=ORIGIN, autoping=True, max_msg_size=2 * 1024 * 1024,
        )
        await self.socket.send_str('{"protocol":"json","version":1}\x1e')
        response = await asyncio.wait_for(self.socket.receive(), timeout=15)
        if response.type != aiohttp.WSMsgType.TEXT:
            raise RuntimeError("The ClassPoint WebSocket did not complete its SignalR handshake.")
        chunks = response.data.split("\x1e")
        handshake = json.loads(chunks[0])
        if handshake.get("error"):
            raise RuntimeError("ClassPoint rejected the SignalR handshake.")
        for chunk in chunks[1:]:
            if chunk:
                await self.handle_message(json.loads(chunk))
        self.receiver = asyncio.create_task(self.receive())
        self.heartbeat = asyncio.create_task(self.keep_alive())
        self.log("Connected to ClassPoint's presenter hub.")

    async def invoke(self, target: str, *arguments) -> object:
        if not self.socket or self.socket.closed:
            raise RuntimeError("The presenter connection is closed. End or restart the local session.")
        self.sequence += 1
        invocation = str(self.sequence)
        future = asyncio.get_running_loop().create_future()
        self.pending[invocation] = future
        message = {"type": 1, "target": target, "arguments": list(arguments), "invocationId": invocation}
        try:
            await self.socket.send_str(json.dumps(message, separators=(",", ":")) + "\x1e")
            return await asyncio.wait_for(future, timeout=20)
        finally:
            self.pending.pop(invocation, None)

    async def receive(self) -> None:
        try:
            async for response in self.socket:
                if response.type == aiohttp.WSMsgType.TEXT:
                    for chunk in response.data.split("\x1e"):
                        if chunk:
                            await self.handle_message(json.loads(chunk))
                elif response.type == aiohttp.WSMsgType.ERROR:
                    break
        except (ValueError, RuntimeError, aiohttp.ClientError):
            self.error = "The presenter connection received an invalid message or disconnected."
        finally:
            for future in self.pending.values():
                if not future.done():
                    future.set_exception(RuntimeError("ClassPoint closed the presenter connection."))
            if not self.disconnecting and self.phase not in {"idle", "ended"}:
                self.phase = "error"
                self.error = self.error or "ClassPoint disconnected. Another presenter may have replaced this session."
            if self.socket and not self.socket.closed:
                await self.socket.close()

    async def keep_alive(self) -> None:
        try:
            while self.socket and not self.socket.closed:
                await asyncio.sleep(10)
                await self.socket.send_str('{"type":6}\x1e')
        except (aiohttp.ClientError, ConnectionError):
            return

    async def handle_message(self, message: dict) -> None:
        if message.get("type") == 7:
            raise RuntimeError("The SignalR server closed the connection.")
        if message.get("type") == 3:
            future = self.pending.get(message.get("invocationId"))
            if future and not future.done():
                if "error" in message:
                    future.set_exception(RuntimeError("ClassPoint rejected a presenter command. Check your account/session permissions."))
                else:
                    future.set_result(message.get("result"))
            return
        target = message.get("target")
        if target in {"ClassTerminated", "StartActivityFailed", "GetClassCodeFailed", "LoadSavedClassFailed"}:
            self.error = f"ClassPoint reported {target}. Check for another presenter using this account."
            self.phase = "error"
            for future in self.pending.values():
                if not future.done():
                    future.set_exception(RuntimeError(self.error))
            if target == "ClassTerminated":
                self.class_started = False
                self.activity_started = False
                self.class_code = None
            return
        arguments = message.get("arguments", [])
        if not arguments:
            return
        value = arguments[0]
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except ValueError:
                return
        if target == "ClassSessionUpdated" and isinstance(value, dict):
            self.class_started = True
            self.class_code = value.get("classCode")
            self.participants = {
                participant["participantId"]: participant
                for participant in value.get("participantList", [])
                if participant.get("participantId") and not participant.get("left")
            }
            self.class_ready.set()
        elif target == "ExistingClassResumed":
            self.log("ClassPoint resumed the existing class for this account.")
        elif target in {"NewParticipantJoined", "ExistingParticipantRefreshed", "OfflineParticipantConnected"} and isinstance(value, dict):
            identifier = value.get("participantId")
            if identifier:
                self.participants[identifier] = value
            if self.slide_message and self.class_started:
                task = asyncio.create_task(self.resync_slide())
                self.resync_tasks.add(task)
                task.add_done_callback(self.resync_tasks.discard)
        elif target == "ParticipantGoesOffline" and isinstance(value, dict):
            self.participants.pop(value.get("participantId"), None)
        elif target in {"ParticipantSubmittedResponse", "SyncActivityResponsesOnRejoin"}:
            responses = value if isinstance(value, list) else [value]
            for response in responses:
                if not isinstance(response, dict) or response.get("activityId") != self.active_activity:
                    continue
                answer = response.get("responseData", [])
                if isinstance(answer, str):
                    try:
                        answer = json.loads(answer)
                    except ValueError:
                        continue
                if isinstance(answer, list) and response.get("responseId"):
                    self.responses[response["responseId"]] = [
                        choice for choice in self.activity_choices if choice in answer
                    ]

    async def resync_slide(self) -> None:
        try:
            await self.invoke("PresenterGotoStep", self.slide_message)
        except (RuntimeError, asyncio.TimeoutError, aiohttp.ClientError):
            self.log("Could not resend the slide to a newly joined participant.")

    async def upload_slide(self, image: bytes, identifier: str) -> str:
        filename = f"poc-slide-{identifier}.jpg"
        image_url = f"{self.profile.storage_origin}/slides/{filename}"
        request_url = f"{image_url}?{self.profile.storage_query}"
        headers = {
            "Origin": ORIGIN,
            "Content-Type": "application/octet-stream",
            "x-ms-blob-type": "BlockBlob",
            "x-ms-blob-content-type": "image/jpeg",
            "x-ms-version": "2021-06-08",
        }
        async with self.session.put(request_url, data=image, headers=headers) as response:
            if response.status != 201:
                raise RuntimeError(f"Slide upload failed (HTTP {response.status}). Your captured upload permission may have expired.")
        self.log("Uploaded the HTML slide snapshot.")
        return image_url

    async def start(self, config: dict, snapshot: Callable[[], Awaitable[bytes]]) -> dict:
        async with self.lock:
            if self.class_started or self.phase == "starting":
                raise RuntimeError("End the current class before starting another one.")
            await self.disconnect()
            self.phase = "starting"
            self.error = None
            self.class_code = None
            self.class_ready.clear()
            self.participants.clear()
            self.responses.clear()
            self.entries.clear()
            self.slide_message = None
            self.active_activity = activity_id()
            self.activity_choices = list(config["choices"])
            self.active_slide = config["slide_index"]
            self.log("Rendering the HTML slide. No PowerPoint involved.")
            try:
                image = await snapshot()
                await self.connect()
                self.class_started = True
                await self.invoke(
                    "PresenterStartSlideshow", self.profile.presenter,
                    {"totalSlideCount": config["total_slides"], "isAudienceSlideViewerEnabled": True},
                    self.profile.class_options,
                )
                await asyncio.wait_for(self.class_ready.wait(), timeout=10)
                self.log("Class started. Students can join with the displayed code.")
                image_url = await self.upload_slide(image, self.active_activity)
                self.slide_message = {
                    "email": self.profile.presenter["email"],
                    "totalSlideCount": config["total_slides"],
                    "slideId": 256 + config["slide_index"],
                    "currentSlideIndex": config["slide_index"] + 1,
                    "currentStep": config["fragment_index"] + 1,
                    "imageUrl": image_url,
                }
                await self.invoke("PresenterGotoStep", self.slide_message)
                self.log("Sent the current HTML slide to ClassPoint's student viewer.")
                await self.invoke("PresenterStartActivity", {
                    "email": self.profile.presenter["email"],
                    "activityId": self.active_activity,
                    "activityType": "Multiple Choice",
                    "activitySlideUrl": image_url,
                    "activityStartTime": int(datetime.now(timezone.utc).timestamp() * 1000),
                    "countdown": 0,
                    "mcChoices": self.activity_choices,
                    "mcIsAllowSelectMultiple": config.get("select_multiple", False),
                    "mcCorrectAnswers": [],
                    "isQuizMode": False,
                })
                self.activity_started = True
                self.phase = "open"
                self.log("Multiple choice is open in the existing ClassPoint student app.")
                return self.state()
            except Exception:
                self.phase = "error"
                self.error = self.error or "Startup failed. Check the error shown by the Start button, then retry."
                if self.class_started:
                    try:
                        await self.invoke("PresenterEndSlideshow", {"email": self.profile.presenter["email"], "toolbarActions": None})
                        self.class_started = False
                        self.activity_started = False
                        self.class_code = None
                        self.log("Ended the incomplete class after startup failed.")
                    except (RuntimeError, asyncio.TimeoutError, aiohttp.ClientError):
                        self.log("Automatic cleanup failed; the class may still be active. Try End class.")
                await self.disconnect()
                raise

    async def open_activity(self, config: dict, snapshot: Callable[[], Awaitable[bytes]]) -> dict:
        async with self.lock:
            if not self.class_started or self.phase not in {"open", "closed"}:
                raise RuntimeError("Start the class first, or end the failed session before restarting.")
            try:
                was_open = self.phase == "open"
                self.phase = "starting"
                if was_open:
                    await self.invoke("PresenterCloseSubmission", {"email": self.profile.presenter["email"]})
                if self.activity_started:
                    await self.invoke("PresenterEndActivity", {"email": self.profile.presenter["email"]})
                    self.activity_started = False
                self.responses.clear()
                self.active_activity = activity_id()
                self.active_slide = config["slide_index"]
                self.activity_choices = list(config["choices"])
                await self.send_slide(config, snapshot)
                await self.invoke("PresenterStartActivity", {
                    "email": self.profile.presenter["email"],
                    "activityId": self.active_activity,
                    "activityType": "Multiple Choice",
                    "activitySlideUrl": self.slide_message["imageUrl"],
                    "activityStartTime": int(datetime.now(timezone.utc).timestamp() * 1000),
                    "countdown": 0,
                    "mcChoices": self.activity_choices,
                    "mcIsAllowSelectMultiple": config.get("select_multiple", False),
                    "mcCorrectAnswers": [],
                    "isQuizMode": False,
                })
                self.activity_started = True
                self.phase = "open"
                self.log("Opened this slide's multiple-choice activity.")
                return self.state()
            except Exception:
                self.phase = "error"
                self.error = self.error or "Could not open the question. Try End class before starting again."
                raise

    async def send_slide(self, config: dict, snapshot: Callable[[], Awaitable[bytes]]) -> None:
        image_url = await self.upload_slide(await snapshot(), activity_id())
        self.slide_message = {
            "email": self.profile.presenter["email"],
            "totalSlideCount": config["total_slides"],
            "slideId": 256 + config["slide_index"],
            "currentSlideIndex": config["slide_index"] + 1,
            "currentStep": config["fragment_index"] + 1,
            "imageUrl": image_url,
        }
        await self.invoke("PresenterGotoStep", self.slide_message)
        self.log(f"Sent HTML slide {config['slide_index'] + 1} to the student viewer.")

    async def sync_slide(self, config: dict, snapshot: Callable[[], Awaitable[bytes]]) -> dict:
        async with self.lock:
            if not self.class_started or self.phase not in {"open", "closed"}:
                raise RuntimeError("There is no active class to synchronize.")
            await self.send_slide(config, snapshot)
            return self.state()

    async def close_submissions(self) -> dict:
        async with self.lock:
            if self.phase != "open":
                raise RuntimeError("There is no open multiple-choice activity.")
            await self.invoke("PresenterCloseSubmission", {"email": self.profile.presenter["email"]})
            self.phase = "closed"
            self.log("Submissions closed. Responses remain visible here.")
            return self.state()

    async def end(self) -> dict:
        async with self.lock:
            if self.class_started:
                if not self.socket or self.socket.closed:
                    await self.disconnect()
                    await self.connect()
                    await self.invoke("PresenterRejoinClass", {"email": self.profile.presenter["email"]})
                if self.phase == "open":
                    await self.invoke("PresenterCloseSubmission", {"email": self.profile.presenter["email"]})
                if self.activity_started:
                    await self.invoke("PresenterEndActivity", {"email": self.profile.presenter["email"]})
                    self.activity_started = False
                await self.invoke("PresenterEndSlideshow", {"email": self.profile.presenter["email"], "toolbarActions": None})
                self.class_started = False
            self.phase = "ended"
            self.error = None
            self.class_code = None
            self.log("Class ended.")
            await self.disconnect()
            return self.state()

    async def disconnect(self) -> None:
        self.disconnecting = True
        tasks = [task for task in [self.receiver, self.heartbeat, *self.resync_tasks] if task]
        self.receiver = None
        self.heartbeat = None
        self.resync_tasks.clear()
        for task in tasks:
            task.cancel()
        if self.socket and not self.socket.closed:
            await self.socket.close()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self.socket = None
