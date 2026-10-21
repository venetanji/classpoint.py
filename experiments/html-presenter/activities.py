"""Small typed boundary for the experimentally supported live activities.

Wire fields come from ClassPoint's public presenter/student apps; see
../../docs/live-image-upload-handoff.md. No remote requests happen here.
"""
from __future__ import annotations
import ipaddress
import json
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urlsplit

MEDIA_ORIGIN = 'https://cpfile11.blob.core.windows.net'

TYPES = {'multiple_choice': ('mc', 'Multiple Choice'), 'image_upload': ('iu', 'Image Upload'), 'short_answer': ('sa', 'Short Answer')}


def activity_options(activity: dict) -> dict:
    kind = activity.get('type', 'multiple_choice')
    if kind not in TYPES:
        raise ValueError('This activity type is not supported by the live presenter.')
    result = {'type': kind, 'choices': []}
    for name in ('select_multiple', 'multiple', 'hide_names', 'caption_required'):
        value = activity.get(name, False)
        if not isinstance(value, bool):
            raise ValueError(f'{name} must be true or false.')
        result[name] = value
    if kind == 'image_upload' and result['multiple']:
        raise ValueError('Live image upload currently supports one submission per participant; set multiple=False.')
    if kind == 'multiple_choice':
        choices = activity.get('choices', [])
        if (not isinstance(choices, list) or not 2 <= len(choices) <= 6
            or any(not isinstance(x, str) or not x or len(x) > 160 for x in choices)
            or len(set(choices)) != len(choices)):
            raise ValueError('The slide needs 2 to 6 distinct ClassPoint choices.')
        result['choices'] = list(choices)
    return result


def start_message(config: dict, email: str, identifier: str, image_url: str, *, now=None) -> dict:
    options = activity_options(config)
    kind = options['type']
    result = {'email': email, 'activityId': identifier, 'activityType': TYPES[kind][1],
              'activitySlideUrl': image_url, 'activityStartTime': now if now is not None else int(datetime.now(timezone.utc).timestamp()*1000), 'countdown': 0}
    if kind == 'multiple_choice':
        result.update(mcChoices=options['choices'], mcIsAllowSelectMultiple=options['select_multiple'], mcCorrectAnswers=[], isQuizMode=False)
    else:
        # Mirrors the official presenter's legacy boolean-to-count adapter:
        # multiple=True means three short answers, but ONE image submission.
        result.update(numOfSubmissionsAllowed=3 if kind == 'short_answer' and options['multiple'] else 1,
                      isNamesHidden=options['hide_names'])
        if kind == 'image_upload': result['isCaptionRequired'] = options['caption_required']
    return result


def safe_image_url(value) -> bool:
    if not isinstance(value, str) or len(value) > 4096 or any(ord(c) < 33 for c in value): return False
    try:
        url = urlsplit(value)
        if url.scheme != 'https' or not url.hostname or url.username or url.password or url.port not in (None, 443): return False
        if url.hostname in ('localhost',) or url.hostname.endswith(('.localhost', '.local')) or '.' not in url.hostname: return False
        try:
            if not ipaddress.ip_address(url.hostname).is_global: return False
        except ValueError: pass
        return True
    except ValueError: return False


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
    def handle_data(self, data): self.parts.append(data)
    def handle_starttag(self, tag, attrs):
        if tag in ('br', 'p', 'div'): self.parts.append('\n')


def normalize_response(kind: str, raw, choices: list):
    if kind == 'short_answer':
        if not isinstance(raw, str) or len(raw) > 8192: return None
        parser = PlainText()
        parser.feed(raw)
        return {'text': ''.join(parser.parts).strip()}
    if isinstance(raw, str):
        if len(raw) > 65536: return None
        try: raw = json.loads(raw)
        except (ValueError, RecursionError): return None
    if not isinstance(raw, list): return None
    if kind == 'multiple_choice': return [choice for choice in choices if choice in raw]
    if kind == 'image_upload' and len(raw) == 2 and safe_image_url(raw[0]) and isinstance(raw[1], str) and len(raw[1]) <= 4096:
        return {'image_url': raw[0], 'caption': raw[1]}
    return None


def preview_url(value, storage_origin=MEDIA_ORIGIN):
    """Only unsigned uploads at the student app's observed storage origin."""
    if not safe_image_url(value): return None
    candidate, origin = urlsplit(value), urlsplit(storage_origin)
    if (candidate.netloc == origin.netloc and origin.scheme == 'https'
        and candidate.path.startswith('/user/') and not candidate.query and not candidate.fragment):
        return value
    return None
