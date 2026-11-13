"""Run the presenter against loopback ClassPoint mocks for controller practice."""
from __future__ import annotations

import argparse
import asyncio
import tempfile
from pathlib import Path

from aiohttp import web

from deck import render_deck
from presenter import ROOT, create_app
from validate import MockClassPoint, MockProfile, serve


@web.middleware
async def rehearsal_banner(request, handler):
    if request.path == "/":
        html = (ROOT / "web/index.html").read_text(encoding="utf-8")
        html = html.replace("<body>", '<body><div class="toolbar" role="status"><strong>Offline rehearsal</strong><span>Answers and stars are simulated. No ClassPoint class or student data.</span></div>')
        return web.Response(text=html, content_type="text/html")
    return await handler(request)


async def main(port):
    mock = MockClassPoint()
    remote = web.Application()
    remote.router.add_get("/classsession", mock.hub)
    remote.router.add_put("/slides/{filename}", mock.upload)
    remote_runner, remote_url = await serve(remote)
    profile = MockProfile(
        {"userId": "rehearsal", "email": "rehearsal@example.test"},
        {"classCode": "PRACTICE", "classLimit": 100}, "cpcs-11", remote_url,
        "sp=w&sig=SENSITIVE-SECRET",
    )
    profile.mock_url = remote_url

    async def seed_answers():
        seeded = None
        while True:
            if mock.activity and mock.activity != seeded and mock.socket and not mock.socket.closed:
                seeded = mock.activity
                for index in range(24):
                    await mock.event("ParticipantSubmittedResponse", {
                        "activityId": seeded, "responseId": f"practice-{index}",
                        "participantId": f"practice-participant-{index // 2}",
                        "responseData": f"<p>Sample answer {index + 1}. "
                            "This is a simulated submission for trying the scrollable answer panel. "
                            "Use the D-pad or left stick to scroll, then close the question and try the simulated star award.</p>",
                    })
            await asyncio.sleep(0.1)

    task = None
    runner = None
    try:
        with tempfile.TemporaryDirectory(prefix="classpoint-rehearsal-") as temporary:
            directory = Path(temporary)
            course = directory / "course"
            (course / "deck").mkdir(parents=True)
            (course / "deckgen.toml").write_text('[course]\ncode="PRACTICE"\nname="Offline controller rehearsal"\ndecks=["practice"]\n')
            (course / "deck/practice.py").write_text(
                'from deckgen.layouts import question, content, finalize\n'
                'DECK={"title":"Offline controller rehearsal","console":False,"slides":finalize(['
                'content("PRACTICE","Try your controller",["Circle / R1 / D-pad right: forward.","Square / L1 / D-pad left: back.","Next: open the practice question; answers and stars are simulated."]),'
                'question("short_answer","Try the answer overlay",hint="Open this practice question, then press triangle. All responses are simulated."),'
                'question("short_answer","Try another question",hint="Practice opening a new question after awarding stars.")],"PRACTICE")}\n')
            deck = render_deck(directory / "site", course, "practice")
            deck.initial_slide = 0
            app = create_app(profile, deck, port)
            app.middlewares.append(rehearsal_banner)
            runner, url = await serve(app, port)
            task = asyncio.create_task(seed_answers())
            print(f"Offline controller rehearsal: {url} (no remote ClassPoint requests)", flush=True)
            await asyncio.Event().wait()
    finally:
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        if runner:
            await runner.cleanup()
        await remote_runner.cleanup()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("Choose a port between 1 and 65535.")
    try:
        asyncio.run(main(args.port))
    except KeyboardInterrupt:
        pass
