import asyncio
import io
import json
import socket
import sys
import tempfile
from pathlib import Path

import aiohttp
from aiohttp import web
from PIL import Image
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from bridge import Bridge
from capture import Profile
from deck import render_deck
from presenter import SNAPSHOTTER, create_app, installed_chromium


class MockProfile(Profile):
    @property
    def hub_url(self):
        return self.mock_url + "/classsession"


class MockClassPoint:
    def __init__(self):
        self.commands = []
        self.uploads = []
        self.socket = None
        self.reject = None
        self.fail_close = False
        self.activity = None
        self.code_override = None

    async def event(self, target, value):
        await self.socket.send_str(json.dumps({"type": 1, "target": target, "arguments": [value]}) + "\x1e")

    async def hub(self, request):
        assert request.headers["Origin"] == "https://presenter.classpoint.app"
        self.socket = web.WebSocketResponse()
        await self.socket.prepare(request)
        async for frame in self.socket:
            if frame.type != aiohttp.WSMsgType.TEXT:
                continue
            for chunk in frame.data.split("\x1e"):
                if not chunk:
                    continue
                message = json.loads(chunk)
                if message.get("protocol"):
                    assert message == {"protocol": "json", "version": 1}
                    await self.socket.send_str("{}\x1e")
                    continue
                if message.get("type") == 6:
                    continue
                target = message["target"]
                self.commands.append(message)
                if target == self.reject:
                    self.reject = None
                    await self.event("StartActivityFailed", {})
                elif target == "PresenterStartSlideshow":
                    assert len(message["arguments"]) == 3
                    await self.event("ClassSessionUpdated", {
                        "classCode": self.code_override or message["arguments"][2].get("classCode") or "MOCK01",
                        "participantList": [], "cpcsRegion": "cpcs-11",
                    })
                elif target == "PresenterStartActivity":
                    dto = message["arguments"][0]
                    assert dto["activityType"] in {"Multiple Choice", "Image Upload", "Short Answer"}
                    if dto["activityType"] == "Multiple Choice":
                        assert dto["mcChoices"] == ["A", "B", "C", "D"]
                    else:
                        assert not any(key.startswith("mc") or key == "isQuizMode" for key in dto)
                        assert dto["numOfSubmissionsAllowed"] in (1, 3)
                    self.activity = dto["activityId"]
                completion = {"type": 3, "invocationId": message["invocationId"]}
                if self.fail_close and target == "PresenterCloseSubmission":
                    self.fail_close = False
                    completion["error"] = "Private server error must not reach the UI"
                await self.socket.send_str(json.dumps(completion) + "\x1e")
        return self.socket

    async def upload(self, request):
        self.uploads.append((request.path, await request.read()))
        assert request.query["sig"] == "SENSITIVE-SECRET"
        assert request.headers["x-ms-blob-type"] == "BlockBlob"
        return web.Response(status=201)


async def serve(app, port=0):
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", port)
    await site.start()
    actual_port = site._server.sockets[0].getsockname()[1]
    return runner, f"http://127.0.0.1:{actual_port}"


def free_port():
    with socket.socket() as candidate:
        candidate.bind(("127.0.0.1", 0))
        return candidate.getsockname()[1]


async def eventually(check):
    for attempt in range(150):
        if check():
            return
        await asyncio.sleep(0.05)
    raise AssertionError("Expected local mock state did not arrive")


async def check_audience(browser, profile, directory, output):
    course = directory / "audience-course"
    (course / "deck").mkdir(parents=True)
    (course / "deckgen.toml").write_text('[course]\ncode="TEST"\nname="Audience fixture"\ndecks=["week01"]\n')
    (course / "deck/week01.py").write_text(
        'from deckgen.layouts import question, content, finalize\n'
        'DECK={"title":"Audience fixture","console":False,"slides":finalize(['
        'question("multiple_choice","Question",choices=["One","Two","Three","Four"]),'
        'content("DETAIL","Second slide",["First step","Second step"])],"TEST")}\n'
    )
    deck = render_deck(directory / "audience-site", course, "week01")
    # Keep the fixture fragment in the served HTML so audience reloads retain it.
    html_path = deck.site / "week01/index.html"
    first_slide, separator, remaining = html_path.read_text(encoding="utf-8").partition("</section>")
    assert separator and "</section>" in remaining
    html_path.write_text(first_slide + separator + remaining.replace(
        "</section>", '<span class="fragment">Fixture step</span></section>', 1,
    ), encoding="utf-8")
    port = free_port()
    runner, url = await serve(create_app(profile, deck, port), port)
    context = await browser.new_context(viewport={"width": 1440, "height": 900})
    try:
        external = []

        async def local_requests_only(route):
            if not route.request.url.startswith((url, profile.mock_url, "data:", "about:")):
                external.append(route.request.url)
                await route.abort()
            else:
                await route.continue_()

        await context.route("**/*", local_requests_only)
        page = await context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        await page.goto(url)
        await page.wait_for_function("!document.querySelector('#start').disabled")
        assert await page.locator("#audience").count() == 1, "The separate audience window control is missing"
        async with page.expect_popup() as popup:
            await page.locator("#audience").click()
        audience = await popup.value
        audience.on("pageerror", lambda error: errors.append(str(error)))
        await audience.wait_for_function("document.querySelector('#deck').contentWindow.Reveal?.isReady()")
        await page.locator("#deck").evaluate("el => el.contentWindow.Reveal.slide(1)")
        await audience.wait_for_function("document.querySelector('#deck').contentWindow.Reveal.getIndices().h === 1")
        await page.locator("#deck").evaluate("el => el.contentWindow.Reveal.nextFragment()")
        await audience.wait_for_function("document.querySelector('#deck').contentWindow.Reveal.getIndices().f === 0")
        await page.locator("#deck").evaluate("el => el.contentWindow.Reveal.togglePause(true)")
        await audience.wait_for_function("document.querySelector('#deck').contentWindow.Reveal.isPaused()")
        await page.locator("#deck").evaluate("el => el.contentWindow.Reveal.togglePause(false)")
        await page.locator("#deck").evaluate("el => el.contentWindow.Reveal.slide(0)")
        await page.locator("#start").click()
        await page.wait_for_function("!document.querySelector('#end').disabled")
        await audience.wait_for_function("document.querySelector('#join-code').textContent === 'MOCK01'")
        assert not await audience.locator("#join").is_hidden()
        assert await audience.locator("#start,#close,#end,#votes").count() == 0
        await audience.screenshot(path=str(output / "audience-live.png"))
        await page.locator("#deck").evaluate("el => { el.contentWindow.Reveal.slide(1, 0, 0); el.contentWindow.Reveal.togglePause(true); }")
        await audience.reload()
        await audience.wait_for_function("document.querySelector('#join-code').textContent === 'MOCK01'")
        await audience.wait_for_function("""() => {
            const reveal = document.querySelector('#deck').contentWindow.Reveal;
            const indices = reveal.getIndices();
            return indices.h === 1 && indices.f === 0 && reveal.isPaused();
        }""")
        assert await audience.locator("#deck").evaluate("el => !el.contentWindow.Reveal.getConfig().keyboard && !el.contentWindow.Reveal.getConfig().touch")
        await audience.keyboard.press("ArrowRight")
        assert await audience.locator("#deck").evaluate("el => el.contentWindow.Reveal.getIndices().h === 1 && el.contentWindow.Reveal.getIndices().f === 0")
        await page.locator("#end").click()
        await audience.wait_for_function("document.querySelector('#join').hidden")
        assert not errors, errors
        assert not external, "Generated audience fixture unexpectedly requested external assets"
        print("PASS: read-only audience follows slides, fragments and pause, shows the actual join code, and restores state after reload")
    finally:
        await context.close()
        await runner.cleanup()


async def check_typed_activities(browser, profile, mock, directory):
    course = directory / "typed-course"
    (course / "deck").mkdir(parents=True)
    (course / "deckgen.toml").write_text('[course]\ncode="TEST"\nname="Typed fixture"\ndecks=["week01"]\n')
    (course / "deck/week01.py").write_text(
        'from deckgen.layouts import question, finalize\n'
        'DECK={"title":"Typed fixture","console":False,"slides":finalize(['
        'question("image_upload","Upload a synthetic image"),'
        'question("multiple_choice","MC",choices=["One","Two","Three","Four"]),'
        'question("short_answer","Write a synthetic response")],"TEST")}\n'
    )
    deck = render_deck(directory / "typed-site", course, "week01")
    assert deck.initial_slide == 0 and deck.selection({})['type'] == 'image_upload'
    port = free_port()
    runner, url = await serve(create_app(profile, deck, port), port)
    context = await browser.new_context(viewport={"width": 1440, "height": 900})
    external, errors, media_requests = [], [], []
    image_url = 'https://cpfile11.blob.core.windows.net/user/synthetic.png'
    broken_url = 'https://cpfile11.blob.core.windows.net/user/broken.png'
    image_bytes = io.BytesIO()
    Image.new('RGB', (4, 4), 'green').save(image_bytes, format='PNG')
    async def local_requests_only(route):
        request_url = route.request.url
        if request_url == image_url:
            media_requests.append(request_url)
            await route.fulfill(status=200, content_type='image/png', body=image_bytes.getvalue())
        elif request_url == broken_url:
            media_requests.append(request_url)
            await route.fulfill(status=404, content_type='text/plain', body='Synthetic missing image')
        elif request_url.startswith((url, profile.mock_url, 'data:', 'about:')):
            await route.continue_()
        else:
            external.append(request_url)
            await route.abort()
    await context.route('**/*', local_requests_only)
    try:
        page = await context.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))
        await page.goto(url)
        await page.wait_for_function("!document.querySelector('#start').disabled")
        await page.frame_locator('#deck').locator('[data-classpoint]').first.focus()
        await page.keyboard.press('Enter')
        await page.wait_for_function("document.querySelector('#connection-label').textContent === 'Live / submissions open'")
        answer = {'activityId':mock.activity,'responseId':'image-ui','responseData':json.dumps([image_url,'<script>danger()</script> 🌱'])}
        await mock.event('ParticipantSubmittedResponse', answer)
        await mock.event('ParticipantSubmittedResponse', answer)
        await page.locator('.submission img').wait_for()
        await page.wait_for_function("document.querySelector('.submission img').naturalWidth === 4")
        assert await page.locator('.submission figcaption').inner_text() == '<script>danger()</script> 🌱'
        assert await page.locator('.submission').count() == 1
        async with page.expect_popup() as popup:
            await page.locator('#audience').click()
        audience = await popup.value
        await audience.wait_for_function("document.querySelector('#deck').contentWindow.Reveal?.isReady()")
        assert await audience.locator('.submission,#votes,#start,#close,#end').count() == 0
        await page.locator('#deck').evaluate('el => el.contentWindow.Reveal.slide(1)')
        await page.wait_for_function("document.querySelector('#slide-position').textContent.startsWith('2 /')")
        assert await page.locator('.submission').count() == 1
        assert await page.locator('.vote').count() == 0
        await page.locator('#start').click()
        await page.wait_for_function("document.querySelectorAll('.vote').length === 4")
        assert await page.locator('.submission').count() == 0
        await mock.event('ParticipantSubmittedResponse', {'activityId':mock.activity,'responseId':'mc-ui','responseData':'["B"]'})
        await page.wait_for_function("document.querySelectorAll('.vote-count')[1].textContent === '1'")
        await page.locator('#deck').evaluate('el => el.contentWindow.Reveal.slide(0)')
        await page.wait_for_function("document.querySelector('#slide-position').textContent.startsWith('1 /')")
        assert await page.locator('.vote-count').all_text_contents() == ['0','1','0','0']
        await page.locator('#deck').evaluate('el => el.contentWindow.Reveal.slide(2)')
        await page.wait_for_function("document.querySelector('#slide-position').textContent.startsWith('3 /')")
        assert await page.locator('.vote-count').all_text_contents() == ['0','1','0','0']
        await page.wait_for_function("!document.querySelector('#start').disabled")
        await page.locator('#start').click()
        await page.wait_for_function("document.querySelector('#start').textContent === 'Question open'")
        await mock.event('ParticipantSubmittedResponse', {'activityId':mock.activity,'responseId':'text-ui','responseData':'<p>Safe &amp; simple</p>'})
        await page.locator('.submission figcaption').filter(has_text='Safe & simple').wait_for()
        await page.locator('#deck').evaluate('el => el.contentWindow.Reveal.slide(1)')
        await page.wait_for_function("document.querySelector('#slide-position').textContent.startsWith('2 /')")
        assert await page.locator('.submission figcaption').inner_text() == 'Safe & simple'
        assert await audience.locator('.submission,#votes,#start,#close,#end').count() == 0
        assert await page.locator('.vote').count() == 0
        await page.locator('#deck').evaluate('el => el.contentWindow.Reveal.slide(0)')
        await page.wait_for_function("!document.querySelector('#start').disabled")
        await page.locator('#start').click()
        await page.wait_for_function("document.querySelector('#start').textContent === 'Question open'")
        await mock.event('ParticipantSubmittedResponse', {'activityId':mock.activity,'responseId':'blocked-ui','responseData':json.dumps(['https://private.example.test/user/x','Blocked media'])})
        await page.locator('.submission figcaption').filter(has_text='Blocked media').wait_for()
        assert await page.locator('.submission img,.submission a').count() == 0
        await mock.event('ParticipantSubmittedResponse', {'activityId':mock.activity,'responseId':'broken-ui','responseData':json.dumps([broken_url,'Broken thumbnail'])})
        await page.locator('.submission figcaption').filter(has_text='Broken thumbnail').wait_for()
        await page.wait_for_function("Array.from(document.querySelectorAll('.submission')).some(row => row.querySelector('figcaption').textContent === 'Broken thumbnail' && row.querySelector('img')?.hidden && !row.querySelector('p').hidden)")
        assert not await page.locator('#close').is_disabled()
        assert not await page.locator('#end').is_disabled()
        await page.locator('#close').click()
        await page.wait_for_function("document.querySelector('#connection-label').textContent === 'Live / submissions closed'")
        await page.locator('#end').click()
        await page.wait_for_function("document.querySelector('#connection-label').textContent === 'Class ended'")
        assert media_requests and not errors and not external, (errors, external)
        print('PASS: synthetic image gallery, safe captions, blocked external media, typed badges, MC/image/text mixed navigation and resets')
    finally:
        await context.close()
        await runner.cleanup()


async def main():
    mock = MockClassPoint()
    remote = web.Application()
    remote.router.add_get("/classsession", mock.hub)
    remote.router.add_put("/slides/{filename}", mock.upload)
    remote_runner, remote_url = await serve(remote)
    profile = MockProfile(
        {"userId": "private-user", "email": "sensitive@example.test", "name": "Instructor", "country": "HK"},
        {"classCode": None, "classLimit": 20, "savedClassId": None, "isAllowGuests": True, "platform": "vsto"},
        "cpcs-11", remote_url, "sp=w&sig=SENSITIVE-SECRET",
    )
    profile.mock_url = remote_url
    config = {"slide_index": 0, "fragment_index": -1, "total_slides": 1, "choices": ["A", "B", "C", "D"]}

    async def fake_snapshot():
        return b"mock-jpeg"

    try:
        async with aiohttp.ClientSession() as session:
            bridge = Bridge(profile, session)
            try:
                assert not mock.commands
                await bridge.start(config, fake_snapshot)
                assert bridge.phase == "open" and bridge.class_started
                assert [item["target"] for item in mock.commands] == [
                    "PresenterStartSlideshow", "PresenterGotoStep", "PresenterStartActivity",
                ]
                dto = mock.commands[1]["arguments"][0]
                assert dto["currentSlideIndex"] == 1 and dto["currentStep"] == 0
                await mock.event("NewParticipantJoined", {"participantId": "student-1"})
                await eventually(lambda: len(mock.commands) == 4)
                answer = {"responseId": "response-1", "activityId": bridge.active_activity, "responseData": '["B","B","invalid"]'}
                await mock.event("ParticipantSubmittedResponse", answer)
                await mock.event("ParticipantSubmittedResponse", answer)
                await eventually(lambda: len(bridge.responses) == 1)
                assert bridge.state()["responses"] == [["B"]]
                assert bridge.state()["participants"] == 1
                for secret in ["private-user", "sensitive@example.test", "SENSITIVE-SECRET"]:
                    assert secret not in json.dumps(bridge.state())
                await bridge.sync_slide({**config, "fragment_index": 2}, fake_snapshot)
                assert bridge.slide_message["currentStep"] == 3
                await bridge.close_submissions()
                assert bridge.phase == "closed" and len(bridge.responses) == 1
                await bridge.open_activity(config, fake_snapshot)
                assert bridge.phase == "open" and not bridge.responses
                mock.fail_close = True
                try:
                    await bridge.open_activity(config, fake_snapshot)
                    raise AssertionError("Close failure incorrectly reported success")
                except RuntimeError:
                    assert bridge.phase == "error" and bridge.class_started
                await bridge.end()
                assert bridge.phase == "ended" and not bridge.class_started
                mock.reject = "PresenterStartActivity"
                try:
                    await bridge.start(config, fake_snapshot)
                    raise AssertionError("Server event rejection incorrectly reported success")
                except RuntimeError:
                    assert bridge.phase == "error" and not bridge.class_started
                    assert "StartActivityFailed" in bridge.error
                await bridge.start(config, fake_snapshot)
                await mock.socket.send_str('{"type":7}\x1e')
                await eventually(lambda: bridge.socket.closed)
                assert bridge.phase == "error" and bridge.class_started
                await bridge.end()
                profile.class_options["classCode"] = "FIXED01"
                await bridge.start(config, fake_snapshot)
                assert bridge.state()["class_code"] == "FIXED01"
                await bridge.end()
                mock.code_override = "OTHER01"
                before = len(mock.commands)
                uploads_before = len(mock.uploads)
                try:
                    await bridge.start(config, fake_snapshot)
                    raise AssertionError("A different join code incorrectly opened the class question")
                except RuntimeError as error:
                    assert "join code" in str(error)
                    assert not bridge.class_started and bridge.class_code is None
                    assert not any(item["target"] == "PresenterStartActivity" for item in mock.commands[before:])
                    assert len(mock.uploads) == uploads_before
                mock.code_override = None
                profile.class_options["classCode"] = None
                image_config = {**config, "type": "image_upload", "choices": [], "caption_required": True, "hide_names": True}
                await bridge.start(image_config, fake_snapshot)
                assert bridge.active_activity.startswith("iu")
                dto = mock.commands[-1]["arguments"][0]
                assert dto["isCaptionRequired"] is True and dto["isNamesHidden"] is True
                assert dto["numOfSubmissionsAllowed"] == 1
                answer = {"responseId": "image-1", "activityId": bridge.active_activity,
                          "responseData": json.dumps(["https://cpfile11.blob.core.windows.net/user/mock.png", "こんにちは <script>x</script>"])}
                await mock.event("ParticipantSubmittedResponse", answer)
                await mock.event("ParticipantSubmittedResponse", answer)
                await eventually(lambda: len(bridge.responses) == 1)
                assert bridge.state()["responses"][0]["caption"] == "こんにちは <script>x</script>"
                assert bridge.state()["responses"][0]["image_url"] == "https://cpfile11.blob.core.windows.net/user/mock.png"
                await mock.event("ParticipantSubmittedResponse", {**answer, "responseId": "bad", "responseData": "{}"})
                await bridge.close_submissions()
                assert len(bridge.responses) == 1
                await bridge.open_activity({**config, "type": "short_answer", "multiple": True, "choices": []}, fake_snapshot)
                assert bridge.active_activity.startswith("sa") and not bridge.responses
                assert mock.commands[-1]["arguments"][0]["numOfSubmissionsAllowed"] == 3
                await mock.event("ParticipantSubmittedResponse", {"responseId": "text-1", "activityId": bridge.active_activity, "responseData": "<p>Hello &amp; world</p>"})
                await eventually(lambda: len(bridge.responses) == 1)
                assert bridge.state()["responses"] == [{"text": "Hello & world"}]
                await bridge.end()
                before = len(mock.commands)
                try:
                    await bridge.start({**config, "type": "video_upload"}, fake_snapshot)
                    raise AssertionError("Unsupported type accepted")
                except ValueError:
                    assert len(mock.commands) == before
                mock.reject = "PresenterStartActivity"
                try:
                    await bridge.start(image_config, fake_snapshot)
                    raise AssertionError("Image start failure reported success")
                except RuntimeError:
                    assert not bridge.class_started
                print("PASS: image/short-answer startup, exact typed messages, deduplication, safe responses, switching, cleanup and rejected start")
                print("PASS: configured join code, mismatch detection and cleanup before opening a question")
                print("PASS: mock SignalR lifecycle, answers, rejection, cleanup, retry, and privacy")
            finally:
                await bridge.disconnect()

        if "--protocol-only" in sys.argv:
            return
        mock.commands.clear()
        mock.uploads.clear()
        output = Path(tempfile.gettempdir()) / "classpoint-poc-validation"
        output.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="classpoint-validation-") as temporary:
            directory = Path(temporary)
            deck = render_deck(directory / "site")
            port = free_port()
            app = create_app(profile, deck, port)
            local_runner, local_url = await serve(app, port)
            try:
                async with aiohttp.ClientSession() as client:
                    async with client.get(local_url + "/api/bootstrap") as response:
                        bootstrap = await response.json()
                    for secret in ["private-user", "sensitive@example.test", "SENSITIVE-SECRET"]:
                        assert secret not in json.dumps(bootstrap)
                    headers = {"X-Presenter-Token": bootstrap["token"]}
                    async with client.post(local_url + "/api/start", json={}) as response:
                        assert response.status == 403
                    async with client.post(local_url + "/api/start", headers={**headers, "Origin": "https://untrusted.test"}, json={}) as response:
                        assert response.status == 403
                    async with client.get(local_url + "/api/state", headers={"Host": "untrusted.test"}) as response:
                        assert response.status == 403
                    async with client.post(local_url + "/api/start", headers=headers, json={"slide_index": 100}) as response:
                        assert response.status == 400
                    snapshot = await app[SNAPSHOTTER].capture(config)
                    image = Image.open(io.BytesIO(snapshot))
                    assert image.size == (1920, 1080)
                    (output / "student-slide.jpg").write_bytes(snapshot)
                    assert not mock.commands and not mock.uploads
                    print("PASS: local request guards, private bootstrap, and 1920x1080 real Reveal capture")

                async with async_playwright() as playwright:
                    browser = await playwright.chromium.launch(executable_path=installed_chromium())
                    try:
                        context = await browser.new_context(viewport={"width": 1440, "height": 1000})
                        page = await context.new_page()
                        errors = []
                        external = []
                        page.on("pageerror", lambda error: errors.append(str(error)))

                        async def local_requests_only(route):
                            if not route.request.url.startswith((local_url, remote_url, "data:", "about:")):
                                external.append(route.request.url)
                                await route.abort()
                            else:
                                await route.continue_()

                        await context.route("**/*", local_requests_only)
                        await page.goto(local_url)
                        await page.wait_for_function("!document.querySelector('#start').disabled")
                        assert not mock.commands and not mock.uploads
                        assert await page.locator("#start").inner_text() == "Start class + question"
                        await page.screenshot(path=str(output / "desktop-idle.png"), full_page=True)
                        frame = page.frame_locator("#deck")
                        await frame.locator("[data-classpoint]").click()
                        await page.wait_for_function("!document.querySelector('#end').disabled")
                        assert await page.locator("#connection-label").inner_text() == "Live / submissions open"
                        await mock.event("NewParticipantJoined", {"participantId": "student-1"})
                        await mock.event("ParticipantSubmittedResponse", {
                            "responseId": "response-1", "activityId": mock.activity, "responseData": '["B"]',
                        })
                        await page.locator("#response-count").filter(has_text="1 response").wait_for()
                        assert await page.locator(".vote-count").all_text_contents() == ["0", "1", "0", "0"]
                        assert Image.open(io.BytesIO(mock.uploads[0][1])).size == (1920, 1080)
                        await page.screenshot(path=str(output / "desktop-live.png"), full_page=True)
                        await page.set_viewport_size({"width": 390, "height": 844})
                        assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                        assert not await frame.locator("#ho-open").is_visible()
                        await page.screenshot(path=str(output / "mobile-live.png"), full_page=True)
                        await page.locator("#close").click()
                        await page.wait_for_function("document.querySelector('#connection-label').textContent === 'Live / submissions closed'")
                        await frame.locator("[data-classpoint]").focus()
                        await page.keyboard.press("Enter")
                        await page.wait_for_function("document.querySelector('#connection-label').textContent === 'Live / submissions open'")
                        await page.locator("#end").click()
                        await page.wait_for_function("document.querySelector('#connection-label').textContent === 'Class ended'")
                        mock.reject = "PresenterStartActivity"
                        await page.locator("#start").click()
                        await page.wait_for_function("document.querySelector('#start').textContent === 'Retry class + question'")
                        assert not await page.locator("#start").is_disabled()
                        assert await page.locator("#error").is_visible()
                        await page.locator("#start").click()
                        await page.wait_for_function("document.querySelector('#connection-label').textContent === 'Live / submissions open'")
                        await page.locator("#end").click()
                        await page.wait_for_function("document.querySelector('#connection-label').textContent === 'Class ended'")
                        assert not errors, errors
                        assert not external, "Generated demo unexpectedly requested external assets"
                        print("PASS: desktop/mobile, click and keyboard badges, tallies, error recovery, no page errors")
                        await check_audience(browser, profile, directory, output)
                        await check_typed_activities(browser, profile, mock, directory)
                    finally:
                        await browser.close()
            finally:
                await local_runner.cleanup()

            course = directory / "course"
            (course / "deck").mkdir(parents=True)
            (course / "deckgen.toml").write_text('[course]\ncode="TEST"\nname="Fixture"\ndecks=["week01"]\n')
            (course / "deck" / "week01.py").write_text((ROOT / "demo_deck.py").read_text())
            course_deck = render_deck(directory / "course-site", course, "week01")
            assert course_deck.url == "/deck/week01/index.html"
            assert course_deck.selection({})["choices"] == ["A", "B", "C", "D"]
            for body in [{"slide_index": True}, {"fragment_index": 101}, {"slide_index": -1}]:
                try:
                    course_deck.selection(body)
                    raise AssertionError("Invalid selection was accepted")
                except ValueError:
                    pass
            print("PASS: deckgen course loading and slide selection validation")
        print("Screenshots:", output)
    finally:
        await remote_runner.cleanup()


asyncio.run(main())
