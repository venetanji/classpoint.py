"""
Pull ClassPoint activity responses back out of the web app.

The other half of this project: `classpoint.py` puts activity buttons *into* a
deck, this reads the answers back *out* after class.

Every activity has a public page at `app.classpoint.io/activity/<activityId>`.
It needs no login — the reports dashboard it is linked from does, but the
activity page itself is world-readable and server-rendered, so all the answers
are in the first response. They arrive as a React Server Component payload: one
`{"activity":{...}}` JSON object with the full `activityResponses` list, not a
page of a hundred. Asking for it with the `RSC: 1` header returns that payload
alone (~36 KB) instead of the rendered page (~140 KB); if that ever stops
working `_fetch_payload` falls back to unescaping the flight pushes out of the
HTML, which is the same bytes the long way round.

Two things the payload does *not* have:

* **The question.** Only `activitySlideSavedUrl`, a JPG of the slide it was
  asked on. `--media` downloads it, and that is the only record you get.
* **A way to list activities.** `/cp/reports/activities` is behind the login,
  so `from_list_html()` scrapes activity ids out of a saved copy of that page —
  devtools, copy the cards element, paste into a file. Ids are self-describing
  anyway: the prefix is the type and the next 17 digits are the UTC timestamp.

Response shapes differ per type and are normalised into `Response.text` /
`Response.images`; `Response.raw` keeps the original either way. Verified
against Short Answer, Word Cloud, Multiple Choice and Image Upload. Slide
Drawing, Fill in the Blanks, Video Upload and Audio Record have not been seen,
so they fall through a generic path that will get the text out but may not
recognise their media.

Stdlib only, no dependencies:

    python3 reports.py sa20260904033646383JAAW
    python3 reports.py --from-html activities.html --csv answers.csv
"""

from __future__ import annotations

import argparse
import csv
import html as html_mod
import json
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

ACTIVITY_URL = 'https://app.classpoint.io/activity/{}'

# Chrome's, because a bare urllib UA gets a different render path often enough
# to matter and there is nothing to gain from being interesting.
USER_AGENT = ('Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'
              ' (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36')

# The two-letter id prefix is the activity type. sa/mc/wc/iu are confirmed
# against real activities; the rest are inferred from the component names in
# the page bundle and are only used for labelling before a fetch.
TYPE_PREFIX = {
    'sa': 'Short Answer',
    'mc': 'Multiple Choice',
    'wc': 'Word Cloud',
    'iu': 'Image Upload',
    'sd': 'Slide Drawing',
    'fb': 'Fill in the Blanks',
    'vu': 'Video Upload',
    'ar': 'Audio Record',
}

ID_RE = re.compile(r'\b([a-z]{2}\d{17}[A-Z0-9]{4})\b')
IMAGE_RE = re.compile(r'^https?://\S+\.(?:png|jpe?g|gif|webp|bmp)(?:\?\S*)?$', re.I)


# --------------------------------------------------------------------------
# ids


def activity_id(ref: str) -> str:
    """Accept a bare id, a public URL, or a `/cp/reports/activity?aId=` link."""
    m = ID_RE.search(ref.strip())
    if not m:
        raise ValueError(f'no ClassPoint activity id in {ref!r}')
    return m.group(1)


def id_timestamp(aid: str) -> datetime | None:
    """`sa20260904033646383JAAW` -> 2026-09-04 03:36:46.383 UTC."""
    try:
        return datetime.strptime(aid[2:19], '%Y%m%d%H%M%S%f').replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def id_type(aid: str) -> str:
    return TYPE_PREFIX.get(aid[:2], 'Unknown')


def from_list_html(source: str | Path) -> list[str]:
    """Activity ids out of a saved `/cp/reports/activities` page, in page order.

    Takes a path or the markup itself. Only the ids are read — the type and
    response count on each card come back from the fetch anyway, and reading
    them would tie this to the current card markup.
    """
    text = source
    if isinstance(source, Path) or (isinstance(source, str) and '\n' not in source and len(source) < 4096
                                    and Path(source).exists()):
        text = Path(source).read_text(encoding='utf-8', errors='replace')
    seen: dict[str, None] = {}
    for m in re.finditer(r'aId=([a-z]{2}\d{17}[A-Z0-9]{4})', text):
        seen.setdefault(m.group(1), None)
    if not seen:  # not a dashboard page; take any ids we can see
        for m in ID_RE.finditer(text):
            seen.setdefault(m.group(1), None)
    return list(seen)


# --------------------------------------------------------------------------
# fetching


def _get(url: str, headers: dict[str, str] | None = None, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _extract_activity(payload: str) -> dict:
    i = payload.find('{"activity":')
    if i == -1:
        raise ValueError('no activity object in payload')
    obj, _ = json.JSONDecoder().raw_decode(payload[i:])
    return obj['activity']


def _fetch_payload(aid: str, timeout: int = 30) -> dict:
    url = ACTIVITY_URL.format(aid)
    try:
        return _extract_activity(_get(url, {'RSC': '1'}, timeout).decode('utf-8', 'replace'))
    except (ValueError, KeyError):
        pass
    # Fallback: the same payload, escaped inside the flight scripts of the
    # rendered page.
    page = _get(url, timeout=timeout).decode('utf-8', 'replace')
    for chunk in re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', page, re.S):
        try:
            # The chunk is a JS string literal, so JSON is the right unescaper.
            # `unicode_escape` looks like it works and quietly mojibakes every
            # non-ASCII character, curly apostrophes included.
            return _extract_activity(json.loads(f'"{chunk}"'))
        except (ValueError, KeyError):
            continue
    raise ValueError(f'{aid}: no activity payload — moved, deleted, or the page changed')


# --------------------------------------------------------------------------
# normalising


def strip_html(s: str) -> str:
    s = re.sub(r'<br\s*/?>|</p>|</div>|</li>', '\n', s, flags=re.I)
    s = re.sub(r'<[^>]+>', '', s)
    return re.sub(r'[ \t]+', ' ', html_mod.unescape(s)).strip()


def _split_response(activity_type: str, data) -> tuple[str, list[str]]:
    """`responseData` -> (text, image urls). Shape depends on the type:
    Short Answer is HTML, Word Cloud a bare word, Multiple Choice a JSON list
    of letters, Image Upload a JSON `[url, caption]`."""
    if data is None:
        return '', []
    if isinstance(data, str):
        stripped = data.strip()
        if stripped[:1] in '[{':
            try:
                data = json.loads(stripped)
            except json.JSONDecodeError:
                return strip_html(data), []
        else:
            return strip_html(data), []
    if isinstance(data, dict):
        return json.dumps(data, ensure_ascii=False), []
    if isinstance(data, list):
        parts = [str(x) for x in data if x not in (None, '')]
        images = [p for p in parts if IMAGE_RE.match(p)]
        text = ', '.join(strip_html(p) for p in parts if p not in images)
        return text, images
    return str(data), []


@dataclass
class Response:
    name: str
    text: str
    images: list[str] = field(default_factory=list)
    submitted: str = ''
    points: int = 0
    participant_id: str = ''
    response_id: str = ''
    raw: str = ''


@dataclass
class Activity:
    id: str
    type: str
    created: str
    total: int
    slide_image: str
    responses: list[Response]
    raw: dict = field(repr=False, default_factory=dict)

    @property
    def url(self) -> str:
        return ACTIVITY_URL.format(self.id)

    @property
    def date(self) -> str:
        ts = id_timestamp(self.id)
        return (self.created or (ts.isoformat() if ts else ''))[:10]

    def to_dict(self) -> dict:
        return {
            'activityId': self.id,
            'activityType': self.type,
            'createdOn': self.created,
            'url': self.url,
            'slideImage': self.slide_image,
            'responseCount': self.total,
            'responses': [vars(r) for r in self.responses],
        }


def fetch(ref: str, *, timeout: int = 30) -> Activity:
    """One activity, by id or URL."""
    aid = activity_id(ref)
    a = _fetch_payload(aid, timeout)
    atype = a.get('activityType') or id_type(aid)
    responses = []
    for r in a.get('activityResponses') or []:
        text, images = _split_response(atype, r.get('responseData'))
        responses.append(Response(
            name=r.get('participantName') or '',
            text=text,
            images=images,
            submitted=r.get('responseSubmittedOn') or '',
            points=r.get('responsePoints') or 0,
            participant_id=r.get('participantId') or '',
            response_id=r.get('responseId') or '',
            raw=r.get('responseData') if isinstance(r.get('responseData'), str) else json.dumps(r.get('responseData')),
        ))
    responses.sort(key=lambda r: r.submitted)
    return Activity(
        id=a.get('activityId') or aid,
        type=atype,
        created=a.get('activityCreatedOn') or '',
        total=a.get('activityResponsesTotalCount', len(responses)),
        slide_image=a.get('activitySlideSavedUrl') or '',
        responses=responses,
        raw=a,
    )


def fetch_many(refs, *, timeout: int = 30, on_error='warn') -> list[Activity]:
    """Sequentially — a dozen activities is a dozen requests, and there is no
    reason to hammer someone else's server in parallel for that."""
    out = []
    for ref in refs:
        try:
            out.append(fetch(ref, timeout=timeout))
        except (urllib.error.URLError, ValueError, TimeoutError) as e:
            if on_error == 'raise':
                raise
            print(f'! {ref}: {e}', file=sys.stderr)
    return out


# --------------------------------------------------------------------------
# output


def download_media(activity: Activity, dest: Path) -> list[Path]:
    """The slide the question was asked on, plus any uploaded images. The
    slide is worth having: it is the only copy of the question."""
    out_dir = Path(dest) / activity.id
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    jobs = []
    if activity.slide_image:
        jobs.append((activity.slide_image, out_dir / f'slide{Path(activity.slide_image).suffix or ".jpg"}'))
    for r in activity.responses:
        for n, url in enumerate(r.images):
            stem = re.sub(r'[^\w.-]', '_', f'{r.name or "anon"}-{r.response_id[-8:]}')
            jobs.append((url, out_dir / f'{stem}{"" if n == 0 else f"-{n}"}{Path(url).suffix or ".png"}'))
    for url, path in jobs:
        if path.exists():
            written.append(path)
            continue
        try:
            path.write_bytes(_get(url))
            written.append(path)
        except (urllib.error.URLError, TimeoutError) as e:
            print(f'! {url}: {e}', file=sys.stderr)
    return written


def to_markdown(activities: list[Activity]) -> str:
    lines = []
    for a in activities:
        lines.append(f'## {a.type} — {a.date}  ({len(a.responses)}/{a.total} responses)')
        lines.append(f'{a.url}')
        if a.slide_image:
            lines.append(f'question slide: {a.slide_image}')
        lines.append('')
        for r in a.responses:
            body = r.text or ' '.join(r.images) or '(empty)'
            lines.append(f'- **{r.name or "anon"}** — {body.replace(chr(10), " / ")}')
            for url in r.images:
                lines.append(f'    {url}')
        lines.append('')
    return '\n'.join(lines)


def write_csv(activities: list[Activity], path: Path) -> None:
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['activity_id', 'activity_type', 'activity_date', 'participant_name',
                    'participant_id', 'submitted_on', 'points', 'text', 'images'])
        for a in activities:
            for r in a.responses:
                w.writerow([a.id, a.type, a.date, r.name, r.participant_id,
                            r.submitted, r.points, r.text, ' '.join(r.images)])


# --------------------------------------------------------------------------
# cli


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description='Fetch ClassPoint activity responses from their public activity pages.')
    p.add_argument('activities', nargs='*', metavar='ID_OR_URL',
                   help='activity id, https://app.classpoint.io/activity/<id>, or a ?aId= link')
    p.add_argument('--from-html', metavar='FILE', action='append', default=[],
                   help='saved /cp/reports/activities page to read ids from (repeatable)')
    p.add_argument('--json', metavar='FILE', help='write everything as JSON')
    p.add_argument('--csv', metavar='FILE', help='write one row per response')
    p.add_argument('--markdown', metavar='FILE', help='write the readable dump instead of stdout')
    p.add_argument('--media', metavar='DIR', help='download question slides and uploaded images')
    p.add_argument('--type', action='append', default=[], metavar='PREFIX',
                   help='only ids of this type: sa, mc, wc, iu (repeatable)')
    p.add_argument('--since', metavar='YYYY-MM-DD', help='only activities created on or after this date')
    p.add_argument('--timeout', type=int, default=30)
    p.add_argument('-q', '--quiet', action='store_true', help='no stdout dump')
    args = p.parse_args(argv)

    refs = [activity_id(a) for a in args.activities]
    for f in args.from_html:
        refs.extend(from_list_html(Path(f)))
    refs = list(dict.fromkeys(refs))

    if args.type:
        wanted = {t.lower() for t in args.type}
        refs = [r for r in refs if r[:2] in wanted]
    if args.since:
        cut = datetime.strptime(args.since, '%Y-%m-%d').replace(tzinfo=timezone.utc)
        refs = [r for r in refs if (id_timestamp(r) or cut) >= cut]

    if not refs:
        p.error('nothing to fetch — pass an activity id/URL or --from-html')

    print(f'fetching {len(refs)} activit{"y" if len(refs) == 1 else "ies"}…', file=sys.stderr)
    activities = fetch_many(refs, timeout=args.timeout)
    for a in activities:
        print(f'  {a.id}  {a.type:<16} {len(a.responses):>4} responses', file=sys.stderr)
    if not activities:
        return 1

    if args.json:
        Path(args.json).write_text(
            json.dumps([a.to_dict() for a in activities], indent=2, ensure_ascii=False), encoding='utf-8')
    if args.csv:
        write_csv(activities, Path(args.csv))
    if args.markdown:
        Path(args.markdown).write_text(to_markdown(activities), encoding='utf-8')
    if args.media:
        for a in activities:
            files = download_media(a, Path(args.media))
            print(f'  {a.id}: {len(files)} file(s) -> {Path(args.media) / a.id}', file=sys.stderr)
    if not args.quiet and not args.markdown:
        print(to_markdown(activities))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
