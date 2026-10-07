from __future__ import annotations

import argparse
import asyncio
import os
import secrets
import sys
import tempfile
from pathlib import Path

import aiohttp
from aiohttp import web
from playwright.async_api import Error as BrowserError
from playwright.async_api import async_playwright

from bridge import Bridge
from capture import Profile, load_profile
from deck import Deck, render_deck


ROOT = Path(__file__).parent
BRIDGE = web.AppKey("bridge", Bridge)
CLIENT = web.AppKey("client", aiohttp.ClientSession)
TOKEN = web.AppKey("token", str)
DECK = web.AppKey("deck", Deck)
LOCAL_URL = web.AppKey("local_url", str)
SNAPSHOTTER = web.AppKey("snapshotter", object)
ALLOWED_HOSTS = web.AppKey("allowed_hosts", set)


def installed_chromium() -> str | None:
    override = os.environ.get("CLASSPOINT_CHROMIUM")
    if override:
        if not Path(override).is_file():
            raise RuntimeError("CLASSPOINT_CHROMIUM does not point to an executable.")
        return override
    cache = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".cache")) / "ms-playwright"
    candidates = sorted(
        cache.glob("chromium-*/**/chrome.exe"),
        key=lambda path: int(path.relative_to(cache).parts[0].split("-")[-1]),
        reverse=True,
    )
    return str(candidates[0]) if candidates else None


class Snapshotter:
    def __init__(self, url: str):
        self.url = url
        self.runtime = None
        self.browser = None
        self.lock = asyncio.Lock()

    async def capture(self, config: dict) -> bytes:
        async with self.lock:
            if not self.runtime:
                self.runtime = await async_playwright().start()
            if not self.browser:
                self.browser = await self.runtime.chromium.launch(executable_path=installed_chromium())
            context = await self.browser.new_context(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)
            try:
                await context.add_init_script("localStorage.setItem('deckgen.view', 'deck');")
                page = await context.new_page()
                await page.goto(self.url, wait_until="load", timeout=30000)
                await page.wait_for_function("window.Reveal && Reveal.isReady()", timeout=15000)
                await page.evaluate("document.fonts.ready")
                await page.evaluate(
                    "selection => { Reveal.slide(selection.slide_index, 0, selection.fragment_index); Reveal.layout(); }",
                    config,
                )
                await page.add_style_tag(content=".cp,.controls,.progress,#ho-open,#ho-deck { visibility:hidden!important; }")
                await page.wait_for_timeout(180)
                await page.evaluate("Promise.all(Array.from(document.images).map(image => image.decode().catch(() => {})))")
                return await page.screenshot(type="jpeg", quality=88, animations="disabled")
            finally:
                await context.close()

    async def close(self) -> None:
        if self.browser:
            await self.browser.close()
        if self.runtime:
            await self.runtime.stop()


@web.middleware
async def local_only(request: web.Request, handler):
    if request.host not in request.app[ALLOWED_HOSTS]:
        raise web.HTTPForbidden(text="Use the local presenter URL printed in the terminal.")
    origin = request.headers.get("Origin")
    if origin and origin not in {f"http://{host}" for host in request.app[ALLOWED_HOSTS]}:
        raise web.HTTPForbidden(text="Cross-origin requests are not allowed.")
    if request.method not in {"GET", "HEAD"} and not secrets.compare_digest(
        request.headers.get("X-Presenter-Token", ""), request.app[TOKEN],
    ):
        raise web.HTTPForbidden(text="Reload the local presenter before sending a command.")
    response = await handler(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


async def index(request: web.Request) -> web.Response:
    return web.FileResponse(ROOT / "web" / "index.html")


async def bootstrap(request: web.Request) -> web.Response:
    deck = request.app[DECK]
    return web.json_response({
        "token": request.app[TOKEN],
        "deck_url": deck.url,
        "title": deck.title,
        "slides": deck.slides,
        "initial_slide": deck.initial_slide,
        "state": request.app[BRIDGE].state(),
    })


async def state(request: web.Request) -> web.Response:
    return web.json_response(request.app[BRIDGE].state())


async def command(request: web.Request) -> web.Response:
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError("The command body must be a JSON object.")
        action = request.match_info["action"]
        bridge = request.app[BRIDGE]
        if action in {"start", "activity", "sync"}:
            config = request.app[DECK].selection(body, require_activity=action != "sync")
            snapshot = lambda: request.app[SNAPSHOTTER].capture(config)
            if action == "start":
                result = await bridge.start(config, snapshot)
            elif action == "activity":
                result = await bridge.open_activity(config, snapshot)
            else:
                result = await bridge.sync_slide(config, snapshot)
        elif action == "close":
            result = await bridge.close_submissions()
        elif action == "end":
            result = await bridge.end()
        else:
            raise web.HTTPNotFound()
        return web.json_response(result)
    except (ValueError, RuntimeError) as error:
        return web.json_response({"error": str(error)}, status=400)
    except BrowserError:
        return web.json_response({"error": "Could not capture the deck. Install Chromium with 'uv run playwright install chromium', or set CLASSPOINT_CHROMIUM."}, status=502)
    except (aiohttp.ClientError, asyncio.TimeoutError):
        return web.json_response({"error": "ClassPoint did not respond. Check your connection, account permissions, and captured upload settings."}, status=502)


def create_app(profile: Profile, deck: Deck, port: int = 8765) -> web.Application:
    app = web.Application(middlewares=[local_only], client_max_size=16 * 1024)
    app[TOKEN] = secrets.token_urlsafe(32)
    app[DECK] = deck
    app[LOCAL_URL] = f"http://127.0.0.1:{port}"
    app[ALLOWED_HOSTS] = {f"127.0.0.1:{port}", f"localhost:{port}"}

    async def resources(application):
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=35)) as session:
            application[CLIENT] = session
            application[BRIDGE] = Bridge(profile, session)
            application[SNAPSHOTTER] = Snapshotter(application[LOCAL_URL] + deck.url)
            yield
            try:
                if application[BRIDGE].class_started:
                    await asyncio.wait_for(application[BRIDGE].end(), timeout=15)
            except (RuntimeError, aiohttp.ClientError, asyncio.TimeoutError):
                print("Could not confirm class cleanup. The ClassPoint class may still be active.", file=sys.stderr)
            finally:
                await application[BRIDGE].disconnect()
                await application[SNAPSHOTTER].close()

    app.cleanup_ctx.append(resources)
    app.router.add_get("/", index)
    app.router.add_get("/api/bootstrap", bootstrap)
    app.router.add_get("/api/state", state)
    app.router.add_post("/api/{action:start|activity|sync|close|end}", command)
    app.router.add_static("/assets/", ROOT / "web")
    app.router.add_static("/deck/", deck.site)
    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Present a deckgen HTML deck with live ClassPoint multiple choice, without PowerPoint.")
    captures = sorted(ROOT.glob("*.pcapng"), key=lambda path: path.stat().st_mtime, reverse=True)
    parser.add_argument("--capture", type=Path, default=captures[0] if captures else None)
    parser.add_argument("--key-log", type=Path, default=Path(tempfile.gettempdir()) / "classpoint-tls-keys.log")
    parser.add_argument("--project", type=Path, help="Existing course repo containing deckgen.toml")
    parser.add_argument("--deck", help="Deck module name in that course's deck/ directory")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if not args.capture:
        parser.error("Pass --capture with your own ClassPoint test capture.")
    if not 1 <= args.port <= 65535:
        parser.error("Choose a port between 1 and 65535.")
    try:
        profile = load_profile(args.capture.resolve(), args.key_log.resolve())
        with tempfile.TemporaryDirectory(prefix="classpoint-deckgen-") as temporary:
            deck = render_deck(Path(temporary), args.project, args.deck)
            app = create_app(profile, deck, args.port)
            print(f"Deckgen HTML presenter: http://127.0.0.1:{args.port}")
            print("Close PowerPoint first. No ClassPoint connection opens until you click Start.")
            print("Instructor identity and upload signature stay in this process, not in the served HTML.")
            web.run_app(app, host="127.0.0.1", port=args.port, access_log=None, print=None)
    except (ValueError, FileNotFoundError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
