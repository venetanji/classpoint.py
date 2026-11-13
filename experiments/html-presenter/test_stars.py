import asyncio
import unittest

import aiohttp

from bridge import Bridge
from validate import MockClassPoint, MockProfile, serve
from aiohttp import web


class StarTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.mock = MockClassPoint()
        remote = web.Application()
        remote.router.add_get('/classsession', self.mock.hub)
        remote.router.add_put('/slides/{filename}', self.mock.upload)
        self.runner, url = await serve(remote)
        profile = MockProfile(
            {'userId': 'synthetic', 'email': 'test@example.test'},
            {'classLimit': 20}, 'cpcs-11', url, 'sp=w&sig=SENSITIVE-SECRET')
        profile.mock_url = url
        self.session = aiohttp.ClientSession()
        self.bridge = Bridge(profile, self.session)
        await self.bridge.start({'type': 'short_answer', 'choices': [], 'slide_index': 0,
                                 'fragment_index': -1, 'total_slides': 1}, self.snapshot)

    async def snapshot(self):
        return b'synthetic-jpeg'

    async def asyncTearDown(self):
        await self.bridge.end()
        await self.session.close()
        await self.runner.cleanup()

    async def answer(self, response_id, participant_id):
        await self.bridge.handle_message({'target': 'ParticipantSubmittedResponse', 'arguments': [{
            'activityId': self.bridge.active_activity, 'responseId': response_id,
            'participantId': participant_id, 'responseData': '<p>Synthetic answer</p>'}]})

    async def test_close_and_award_once_per_respondent(self):
        await self.answer('one', 'student-a')
        await self.answer('two', 'student-a')
        await self.answer('three', 'student-b')
        await self.bridge.finish_question()
        commands = self.mock.commands
        targets = [item['target'] for item in commands]
        self.assertLess(targets.index('PresenterCloseSubmission'), targets.index('GivePointsToParticipants'))
        award = next(item for item in commands if item['target'] == 'GivePointsToParticipants')
        self.assertEqual(award['arguments'], [{'email': 'test@example.test'}, [
            {'participantId': 'student-a', 'points': 1}, {'participantId': 'student-b', 'points': 1}]])
        self.assertEqual(self.bridge.state()['stars_status'], 'awarded')
        self.assertEqual(self.bridge.state()['stars_count'], 2)
        await self.bridge.finish_question()
        self.assertEqual(sum(item['target'] == 'GivePointsToParticipants' for item in commands), 1)
        self.assertNotIn('participantId', str(self.bridge.state()['responses']))

    async def test_empty_question_can_close_then_award_a_late_delivered_answer(self):
        await self.bridge.finish_question()
        self.assertEqual(self.bridge.phase, 'closed')
        self.assertFalse(any(item['target'] == 'GivePointsToParticipants' for item in self.mock.commands))
        await self.answer('one', 'student-a')
        await self.bridge.finish_question()
        self.assertEqual(self.bridge.state()['stars_count'], 1)

    async def test_uncertain_award_cannot_be_repeated(self):
        await self.answer('one', 'student-a')
        await self.bridge.close_submissions()
        invoke = self.bridge.invoke
        async def timeout(target, *args):
            if target == 'GivePointsToParticipants':
                raise asyncio.TimeoutError()
            return await invoke(target, *args)
        self.bridge.invoke = timeout
        with self.assertRaises(asyncio.TimeoutError):
            await self.bridge.finish_question()
        self.assertEqual(self.bridge.state()['stars_status'], 'uncertain')
        with self.assertRaisesRegex(RuntimeError, 'confirm|Check'):
            await self.bridge.finish_question()

    async def test_display_limit_does_not_exclude_later_respondents_from_stars(self):
        for index in range(513):
            await self.answer(f'response-{index}', f'participant-{index}')
        self.assertEqual(len(self.bridge.responses), 512)
        self.assertTrue(self.bridge.state()['responses_limited'])
        await self.bridge.finish_question()
        self.assertEqual(self.bridge.state()['stars_count'], 513)


if __name__ == '__main__':
    unittest.main()
