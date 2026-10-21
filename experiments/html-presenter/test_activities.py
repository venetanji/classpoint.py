"""Synthetic, browser-free tests. Never contacts ClassPoint."""
import unittest
from activities import activity_options, start_message, normalize_response

class ActivitiesTest(unittest.TestCase):
    def test_image_options_and_wire(self):
        config = activity_options({'type': 'image_upload', 'multiple': False, 'hide_names': True, 'caption_required': True})
        wire = start_message(config, 'teacher@example.test', 'iuTEST', 'https://storage.example.test/slides/test.jpg', now=123)
        self.assertEqual(wire, {'email':'teacher@example.test','activityId':'iuTEST','activityType':'Image Upload','activitySlideUrl':'https://storage.example.test/slides/test.jpg','activityStartTime':123,'countdown':0,'numOfSubmissionsAllowed':1,'isNamesHidden':True,'isCaptionRequired':True})
    def test_options_are_typed(self):
        for options in ({'type':'image_upload','caption_required':'false'}, {'type':'image_upload','multiple':3}, {'type':'video_upload'}):
            with self.assertRaises(ValueError): activity_options(options)
    def test_image_response(self):
        self.assertEqual(normalize_response('image_upload', '["https://media.example.test/a.png","こんにちは <script>x</script>"]', []), {'image_url':'https://media.example.test/a.png','caption':'こんにちは <script>x</script>'})
        self.assertEqual(normalize_response('image_upload', '["https://media.example.test/a.png",""]', [])['caption'], '')
    def test_bad_responses(self):
        for value in ('bad', '{}', '[]', '["javascript:alert(1)", "x"]', '["http://localhost/x", ""]', '["https://127.0.0.1/x", ""]', '["https://user:pass@example.test/x", ""]', '["https://example.test/a", 1]'):
            self.assertIsNone(normalize_response('image_upload', value, []))
    def test_multiple_choice_unchanged(self):
        self.assertEqual(normalize_response('multiple_choice', '["B","B","bad"]', ['A','B']), ['B'])
        options=activity_options({'type':'multiple_choice','choices':['A','B']})
        self.assertEqual(start_message(options,'e','mcID','https://example.test/s',now=1)['mcChoices'], ['A','B'])


class SafetyTest(unittest.TestCase):
    def test_preview_origin(self):
        from activities import preview_url
        good = 'https://cpfile11.blob.core.windows.net/user/test.png'
        self.assertEqual(preview_url(good), good)
        for url in ('https://cpfile11.blob.core.windows.net.evil.test/user/x', good+'?sig=secret', 'https://internal.example.test/user/a', 'https://cpfile12.blob.core.windows.net/user/a', 'https://cpfile11.blob.core.windows.net./user/a', 'https://cpfile11.blob.core.windows.net/slides/a'):
            self.assertIsNone(preview_url(url))
    def test_short_answer(self):
        self.assertEqual(normalize_response('short_answer', '<p>Hello &amp; world<br>two</p>', []), {'text':'Hello & world\ntwo'})
        self.assertIsNone(normalize_response('short_answer', 'x'*8193, []))
    def test_nested_json(self):
        self.assertIsNone(normalize_response('image_upload', '['*2000+']'*2000, []))
    def test_image_multiple_is_not_silently_ignored(self):
        with self.assertRaises(ValueError): activity_options({'type':'image_upload','multiple':True})

class ResponseBoundsTest(unittest.IsolatedAsyncioTestCase):
    async def test_capacity_updates_and_privacy(self):
        from bridge import Bridge, MAX_RESPONSES
        from capture import Profile
        profile = Profile({'email':'private@example.test'}, {}, 'cpcs-11', 'https://cpblob11.blob.core.windows.net', 'sig=SECRET')
        bridge = Bridge(profile, None)
        bridge.activity_type = 'image_upload'
        bridge.active_activity = 'iuTEST'
        bridge.responses = {str(i): {'image_url':None, 'caption':'old'} for i in range(MAX_RESPONSES)}
        async def send(identifier, url, caption):
            import json
            await bridge.handle_message({'target':'ParticipantSubmittedResponse','arguments':[{'activityId':'iuTEST','responseId':identifier,'responseData':json.dumps([url,caption])}]})
        await send('overflow','https://cpfile11.blob.core.windows.net/user/a','new')
        self.assertEqual(len(bridge.responses), MAX_RESPONSES)
        self.assertNotIn('overflow',bridge.responses)
        self.assertTrue(bridge.state()['responses_limited'])
        await send('0','https://cpfile11.blob.core.windows.net/user/a?sig=SECRET','updated')
        self.assertEqual(bridge.responses['0'], {'image_url':None,'caption':'updated'})
        import json
        self.assertNotIn('SECRET',json.dumps(bridge.state()))
        await bridge.handle_message({'target':'ParticipantSubmittedResponse','arguments':[{'activityId':'old','responseId':'0','responseData':'[]'}]})
        self.assertEqual(bridge.responses['0']['caption'],'updated')

if __name__ == '__main__': unittest.main()
