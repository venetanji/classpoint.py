"""
Everything here runs offline.

    python3 tests.py

The network half — that app.classpoint.io still returns what reports.py expects
— cannot be faked usefully, so it is not faked: run `python3 reports.py <id>`
against a real activity when the site changes under you.
"""
import json
import pathlib
import sys
import tempfile

import reports
import weekly

fails = []


def check(name, ok):
    print(('  ok  ' if ok else '  FAIL ') + name)
    if not ok:
        fails.append(name)


# ── ids ──────────────────────────────────────────────────────────────────────
AID = 'sa20260904033646383JAAW'
check('a bare id', reports.activity_id(AID) == AID)
check('a public url', reports.activity_id(f'https://app.classpoint.io/activity/{AID}') == AID)
check('a dashboard link', reports.activity_id(f'/cp/reports/activity?aId={AID}&fr=activities_all') == AID)
check('the id carries its own timestamp', str(reports.id_timestamp(AID)).startswith('2026-09-04 03:36:46'))
check('and its own type', reports.id_type(AID) == 'Short Answer' and reports.id_type('wc' + AID[2:]) == 'Word Cloud')
try:
    reports.activity_id('not an activity')
    check('nonsense is rejected', False)
except ValueError:
    check('nonsense is rejected', True)

# ── the dashboard page ───────────────────────────────────────────────────────
IDS = ['iu20260101010101001AAAA', 'mc20260101020202002BBBB', 'sa20260101030303003CCCC']
page = '<div>' + ''.join(
    f'<div class="card"><a href="/cp/reports/activity?aId={i}&amp;fr=activities_all">'
    f'<img src="https://cpfile11.blob.core.windows.net/user/{i}.jpg"></a>'
    f'<div class="flex w-fit">Whatever</div><div>42</div></div>' for i in IDS) + '</div>'
check('ids come off a saved dashboard in page order', reports.from_list_html(page) == IDS)
check('each id appears once however many times it is linked', reports.from_list_html(page + page) == IDS)
check('a page with no cards falls back to any id it can see',
      reports.from_list_html(f'go and read {IDS[1]} please') == [IDS[1]])

# ── response shapes ──────────────────────────────────────────────────────────
split = reports._split_response
check('short answer is html', split('Short Answer', '<p>Two <b>lines</b><br>here</p>') == ('Two lines\nhere', []))
check('an entity is unescaped', split('Short Answer', '<p>it&rsquo;s &amp; more</p>')[0] == 'it’s & more')
check('word cloud is a bare word', split('Word Cloud', 'game') == ('game', []))
check('multiple choice is a json list', split('Multiple Choice', '["C"]') == ('C', []))
check('a multi-select keeps both', split('Multiple Choice', '["A","C"]') == ('A, C', []))
check('image upload splits url from caption',
      split('Image Upload', json.dumps(['https://x/y.png', 'a cup'])) == ('a cup', ['https://x/y.png']))
check('an unparseable body is kept as text', split('Slide Drawing', '[not json') == ('[not json', []))
check('an empty response is empty, not a crash', split('Short Answer', None) == ('', []))

# ── reading the deck ─────────────────────────────────────────────────────────
DECK = '''
S = []
S.append(title('SD0000 · WEEK 01', 'Hello'))
S.append(question('word_cloud', 'One word for this?', hint='Just one.'))
S.append(content('01 · A', 'No activity here', ['body']))
S.append(question('multiple_choice', 'Which one?', ['A', 'B']))
S.append(content('02 · B', 'An activity on a content slide', ['body'], cp={'type': 'short_answer'}))
S.append(content('03 · C', 'Explicitly none', ['body'], cp=None))
'''
with tempfile.TemporaryDirectory() as d:
    deck = pathlib.Path(d) / 'week01.py'
    deck.write_text(DECK)
    got = weekly.deck_questions(deck)
    check('every ClassPoint slide is found, in source order',
          got == ['One word for this?', 'Which one?', 'An activity on a content slide'])
    check('a slide with cp=None is not one of them', 'Explicitly none' not in got)

# ── what gets written ────────────────────────────────────────────────────────
ENTRIES = [{'activity': IDS[0], 'question': 'One word for this?', 'type': 'Image Upload',
            'ran': '2026-01-01T01:01:01Z', 'responses': 42},
           {'activity': None, 'question': 'One hope and one worry.', 'type': 'Short Answer',
            'ran': '2026-01-01T02:02:02Z', 'responses': 95, 'withheld': 'names hidden'}]
md = weekly.answers_md('week01', ENTRIES)
check('one link per line', md.count('\n- ') + md.startswith('- ') == 2)
check('the link is the public page', f'](https://app.classpoint.io/activity/{IDS[0]})' in md)
check('a withheld activity is still listed', 'One hope and one worry.' in md)
check('but not linked', 'not published (names hidden)' in md)
check('a question we do not know falls back to type and time',
      weekly.label({'type': 'Word Cloud', 'ran': '2026-01-01T02:02:02Z'}) == 'Word Cloud at 02:02')

with tempfile.TemporaryDirectory() as d:
    ans = pathlib.Path(d) / 'ANSWERS.md'
    ans.write_text(weekly.splice(ans, 'week01', md, weekly.HEADER))
    once = ans.read_text()
    ans.write_text(weekly.splice(ans, 'week01', md, weekly.HEADER))
    check('rerunning a week rewrites it in place', ans.read_text() == once)
    check('and does not repeat the header', once.count('# Answers') == 1)
    ans.write_text(weekly.splice(ans, 'week03', weekly.answers_md('week03', ENTRIES[:1]), weekly.HEADER))
    ans.write_text(weekly.splice(ans, 'week02', weekly.answers_md('week02', ENTRIES[:1]), weekly.HEADER))
    order = [l for l in ans.read_text().splitlines() if l.startswith('## ')]
    check('weeks stay in week order however they arrive', order == ['## week01', '## week02', '## week03'])

with tempfile.TemporaryDirectory() as d:
    m = pathlib.Path(d) / 'week01-reports.json'
    check('nothing recorded yet is not an error', weekly.prior_questions(m) == {})
    m.write_text(json.dumps([{'activity': IDS[0], 'question': 'Typed in by hand'},
                             {'activity': None, 'question': 'Withheld, no id to key on'},
                             {'activity': IDS[1], 'question': None}]))
    check('a question typed in by hand survives the next run',
          weekly.prior_questions(m) == {IDS[0]: 'Typed in by hand'})

print(f'\n{len(fails)} FAILED: {fails}' if fails else '\nall checks passed')
sys.exit(1 if fails else 0)
