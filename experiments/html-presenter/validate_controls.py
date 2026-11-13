"""Loopback-only integration checks for controller, projected answers and stars."""
import asyncio
import tempfile
from pathlib import Path

from aiohttp import web
from playwright.async_api import async_playwright

from deck import render_deck
from presenter import BRIDGE, create_app, installed_chromium
from validate import MockClassPoint, MockProfile, free_port, serve


async def main():
    mock = MockClassPoint()
    remote = web.Application()
    remote.router.add_get('/classsession', mock.hub)
    remote.router.add_put('/slides/{filename}', mock.upload)
    remote_runner, remote_url = await serve(remote)
    profile = MockProfile({'userId': 'synthetic', 'email': 'test@example.test'},
                          {'classLimit': 100}, 'cpcs-11', remote_url, 'sp=w&sig=SENSITIVE-SECRET')
    profile.mock_url = remote_url
    try:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'course/deck').mkdir(parents=True)
            (root / 'course/deckgen.toml').write_text('[course]\ncode="TEST"\nname="Controller rehearsal"\ndecks=["week01"]\n')
            (root / 'course/deck/week01.py').write_text(
                'from deckgen.layouts import question, finalize\n'
                'DECK={"title":"Controller rehearsal","console":False,"slides":finalize(['
                'question("short_answer","What should we test?"),'
                'question("short_answer","A second question")],"TEST")}\n')
            deck = render_deck(root / 'site', root / 'course', 'week01')
            port = free_port()
            app = create_app(profile, deck, port)
            runner, url = await serve(app, port)
            try:
                async with async_playwright() as pw:
                    browser = await pw.chromium.launch(executable_path=installed_chromium())
                    context = await browser.new_context(viewport={'width': 1440, 'height': 1000})
                    await context.add_init_script('''
                      window.testPad = {index:0,id:'Synthetic standard controller',mapping:'standard',connected:true,
                        buttons:Array.from({length:17},()=>({pressed:false})),axes:[0,0]};
                      Object.defineProperty(navigator,'getGamepads',{value:()=>[null,window.testPad]});
                    ''')
                    errors = []
                    await context.route('**/*', lambda route: route.continue_() if route.request.url.startswith((url, remote_url, 'data:', 'about:')) else route.abort())
                    page = await context.new_page()
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    await page.goto(url)
                    await page.wait_for_function("!document.querySelector('#start').disabled")
                    assert await page.locator('#answers-toggle').count() == 0, 'Use the existing slide button instead of an extra answer control'
                    async def press(index):
                        await page.bring_to_front()
                        await page.evaluate('(i)=>{testPad.buttons[i].pressed=true}', index)
                        await page.wait_for_timeout(200)
                        await page.evaluate('(i)=>{testPad.buttons[i].pressed=false}', index)
                        await page.wait_for_timeout(200)
                    await press(1)
                    await page.wait_for_function("document.querySelector('#slide-position').textContent.startsWith('2 /')")
                    await page.evaluate('testPad.buttons[2].pressed=true')
                    await page.wait_for_timeout(800)
                    assert (await page.locator('#slide-position').inner_text()).startswith('1 /')
                    await page.evaluate('testPad.buttons[2].pressed=false')
                    await page.wait_for_timeout(100)
                    assert not mock.commands, 'Controller navigation must not start a class'
                    badge = page.frame_locator('#deck').locator('[data-classpoint]').first
                    await badge.click()
                    await page.wait_for_function("document.querySelector('#start').textContent === 'Question open'")
                    await page.locator('.answer-panel').wait_for()
                    for i in range(35):
                        await mock.event('ParticipantSubmittedResponse', {
                            'activityId':mock.activity,'responseId':f'synthetic-{i}', 'participantId':f'participant-{i // 2}',
                            'responseData':f'<p>Synthetic response {i}: Safe &amp; readable. ' + ('Useful detail. ' * 15) + '</p>'})
                    await page.wait_for_function("document.querySelector('#response-count').textContent === '35 responses'")
                    await press(3)
                    await page.wait_for_function("document.querySelector('.answer-panel').hidden")
                    await badge.focus()
                    await page.keyboard.press('Enter')
                    await page.locator('.answer-panel').wait_for()
                    assert await page.locator('.answer-row').count() == 35
                    assert sum(c['target']=='PresenterStartActivity' for c in mock.commands) == 1, 'Reopening answers must reuse the existing question'
                    async with page.expect_popup() as popup:
                        await page.locator('#audience').click()
                    audience = await popup.value
                    await audience.locator('.answer-row').nth(34).wait_for(state='attached')
                    assert await audience.locator('.answer-footer button').count() == 0
                    await press(13)
                    assert await page.locator('.answer-list').evaluate('(el)=>el.scrollTop') > 0
                    await audience.wait_for_function("document.querySelector('.answer-list').scrollTop > 0")
                    assert (await page.locator('#slide-position').inner_text()).startswith('1 /')
                    await page.locator('#fullscreen').click()
                    await page.wait_for_function('Boolean(document.fullscreenElement)')
                    assert await page.locator('.answer-panel').is_visible()
                    assert await page.locator('#finish-question').is_visible()
                    shots = Path('/tmp/classpoint-controls-validation')
                    shots.mkdir(exist_ok=True)
                    await page.screenshot(path=str(shots / 'fullscreen.png'))
                    await page.evaluate('document.exitFullscreen()')
                    await page.locator('#finish-question').click()
                    await page.wait_for_function("document.querySelector('#finish-question').textContent.includes('18 respondents')")
                    assert sum(c['target']=='GivePointsToParticipants' for c in mock.commands) == 1
                    await press(0)
                    await badge.click()
                    await page.locator('.answer-panel').wait_for()
                    assert await page.locator('#finish-question').is_disabled()
                    assert sum(c['target']=='PresenterStartActivity' for c in mock.commands) == 1, 'Closed-question answers must reopen without restarting the activity'
                    await page.screenshot(path=str(shots / 'desktop.png'))
                    await audience.screenshot(path=str(shots / 'audience.png'))
                    await page.set_viewport_size({'width': 390, 'height': 844})
                    await page.screenshot(path=str(shots / 'mobile.png'))
                    assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    await press(0)
                    await audience.wait_for_function("document.querySelector('.answer-panel').hidden")
                    await press(1)
                    await page.wait_for_function("document.querySelector('#slide-position').textContent.startsWith('2 /')")
                    await page.wait_for_function("!document.querySelector('#start').disabled")
                    await page.frame_locator('#deck').locator('[data-classpoint]').nth(1).click()
                    await page.locator('.answer-panel').wait_for()
                    await page.wait_for_function("document.querySelector('.answer-count').textContent === '0 answers'")
                    close_empty = page.locator('.answer-footer button').first
                    assert await close_empty.is_enabled(), 'An empty open question must be closable'
                    assert await page.locator('#finish-question').is_enabled()
                    assert await page.locator('#finish-question').inner_text() == 'Close submissions'
                    await page.locator('#finish-question').click()
                    await page.wait_for_function("document.querySelector('#connection-label').textContent === 'Live / submissions closed'")
                    assert await close_empty.inner_text() == 'Submissions closed'
                    assert await page.locator('#close').inner_text() == 'Submissions closed'
                    assert await page.locator('.answer-empty').inner_text() == 'No answers for this question.'
                    assert await page.locator('#finish-question').is_disabled()
                    assert await page.locator('#finish-question').inner_text() == 'No respondents to award'
                    assert sum(c['target']=='GivePointsToParticipants' for c in mock.commands) == 1, 'Closing an empty question must not award stars'
                    await press(0)
                    await page.wait_for_function("document.querySelector('.answer-panel').hidden")
                    await page.locator('#start').click()
                    await page.wait_for_function("document.querySelector('#start').textContent === 'Question open'")
                    await page.frame_locator('#deck').locator('[data-classpoint]').nth(1).click()
                    await page.locator('.answer-panel').wait_for()
                    await page.wait_for_function("document.querySelector('#finish-question').textContent === 'Close submissions'")
                    empty_state = app[BRIDGE].state()
                    assert empty_state['respondents'] == 0
                    # Deliver an answer to the bridge before the next browser poll.
                    async def freeze_empty_state(route):
                        await route.fulfill(json=empty_state)
                    await page.route('**/api/state', freeze_empty_state)
                    try:
                        await mock.event('ParticipantSubmittedResponse', {
                            'activityId': mock.activity, 'responseId': 'synthetic-late',
                            'participantId': 'participant-late', 'responseData': '<p>A late synthetic answer</p>'})
                        async def wait_for_late_answer():
                            while app[BRIDGE].state()['respondents'] != 1:
                                await asyncio.sleep(0.01)
                        await asyncio.wait_for(wait_for_late_answer(), timeout=5)
                        assert await page.locator('#finish-question').inner_text() == 'Close submissions'
                        await page.locator('#finish-question').click()
                        await page.wait_for_function("document.querySelector('#connection-label').textContent === 'Live / submissions closed'")
                        assert app[BRIDGE].state()['stars_status'] == 'ready'
                        assert sum(c['target']=='GivePointsToParticipants' for c in mock.commands) == 1, 'A close-only button must not award a response received before the next UI poll'
                    finally:
                        await page.unroute('**/api/state', freeze_empty_state)
                    await press(0)
                    await page.wait_for_function("document.querySelector('.answer-panel').hidden")
                    await page.locator('#end').click()
                    await page.wait_for_function("document.querySelector('#connection-label').textContent === 'Class ended'")
                    assert not errors, errors
                    await browser.close()
                    print('PASS: controller navigation, held-button protection, 35 answers, scroll sync, fullscreen, mobile, 18 unique star recipients, empty-question close and late-answer close without stars')
                    print(f'Screenshots: {shots}')
            finally:
                await runner.cleanup()
    finally:
        await remote_runner.cleanup()


if __name__ == '__main__':
    asyncio.run(main())
