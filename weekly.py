"""
The weekly routine: after a class, put its answers back into the deck.

    python3 weekly.py --repo ~/dev/sd2112-teaching --week week01 \
                      --on 2026-09-04 --from-html ~/Downloads/activities.html

Reads the activity ids off a saved ClassPoint dashboard page, fetches each
activity with `reports.py`, matches them to the questions in the deck, and
writes two files into the course repo:

  deck/<week>-reports.json   the mapping deckgen's attach_reports() reads
  ANSWERS.md                 one link per line, for anyone not opening slides

Then `deckgen build`, commit, open a PR. Both files are rewritten in place, so
running it twice is the same as running it once.

Three things make this safe to run unattended:

* **Order is the contract.** ClassPoint mints an activity id the first time the
  activity runs, so one class's activities sort chronologically into exactly
  the order their slides appear in. Nothing here needs slide numbers.
* **The deck is parsed, not guessed.** `ast` walks `deck/<week>.py` for
  `question(...)` calls and anything carrying a `cp=`, in source order, and
  writes each question's text into the mapping. deckgen checks that text again
  at build time, so a question rewritten later fails the build instead of
  quietly pointing students at the wrong answers.
* **Anonymous activities are withheld.** ClassPoint's page honours
  `isNamesHidden`, but the payload behind it still carries `participantName`
  for every response. Linking an activity the room was told was anonymous
  would hand out a way to undo that, so those are recorded with a null id and
  no link. `--link-anonymous` overrides, and says so on the way past.

Stdlib only, same as reports.py.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from datetime import datetime
from pathlib import Path

import reports

ANSWERS = 'ANSWERS.md'
CP_LAYOUTS = {'question', 'content', 'cards', 'figure_slide', 'activity', 'code_panel'}


def deck_questions(deck_path: Path) -> list[str]:
    """The question text of every ClassPoint slide in a deck module, in source
    order. A `question(kind, text, …)` call, or any layout given a `cp=`."""
    tree = ast.parse(deck_path.read_text(encoding='utf-8'), str(deck_path))
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        name = node.func.id
        has_cp = any(k.arg == 'cp' and not _is_none(k.value) for k in node.keywords)
        if name == 'question':
            args = node.args[1:]
        elif name in CP_LAYOUTS and has_cp:
            args = node.args[1:2] or node.args[:1]   # eyebrow first, then title
        else:
            continue
        text = next((a.value for a in args if isinstance(a, ast.Constant) and isinstance(a.value, str)), None)
        found.append((node.lineno, text))
    return [t for _, t in sorted(found)]


def _is_none(node) -> bool:
    return isinstance(node, ast.Constant) and node.value is None


def collect(refs, *, on=None, link_anonymous=False) -> list[dict]:
    """Fetch each activity and turn it into a mapping entry, oldest first."""
    if on:
        cut = on.replace('-', '')
        refs = [r for r in refs if r[2:10] == cut]
    refs = sorted(dict.fromkeys(refs), key=lambda r: r[2:19])
    entries = []
    for a in reports.fetch_many(refs):
        hidden = bool(a.raw.get('isNamesHidden'))
        ran = reports.id_timestamp(a.id)
        entry = {
            'activity': a.id,
            'question': None,
            'type': a.type,
            'ran': ran.isoformat().replace('+00:00', 'Z') if ran else a.created,
            'responses': len(a.responses),
        }
        if hidden and not link_anonymous:
            entry['activity'] = None
            entry['withheld'] = 'names hidden — the public payload still carries participantName'
            print(f'  withheld {a.id}: run with names hidden', file=sys.stderr)
        entries.append(entry)
    return entries


def prior_questions(mapping: Path) -> dict[str, str]:
    """Question text already recorded in a mapping file, by activity id."""
    if not mapping.exists():
        return {}
    return {e['activity']: e['question'] for e in json.loads(mapping.read_text(encoding='utf-8'))
            if e.get('activity') and e.get('question')}


def label(entry) -> str:
    if entry.get('question'):
        return entry['question']
    when = (entry.get('ran') or '')[11:16]
    return f'{entry.get("type", "Activity")}{f" at {when}" if when else ""}'


def answers_md(week: str, entries: list[dict]) -> str:
    """One link per line. Withheld activities are listed and not linked, so
    the record stays complete even where the link cannot be published."""
    out = [f'## {week}', '']
    for e in entries:
        n = e.get('responses')
        count = f' — {n} responses' if n else ''
        if e.get('activity'):
            out.append(f'- [{label(e)}]({reports.ACTIVITY_URL.format(e["activity"])}){count}')
        else:
            out.append(f'- {label(e)} — not published ({e.get("withheld", "withheld")})')
    return '\n'.join(out) + '\n'


def splice(path: Path, week: str, section: str, header: str) -> str:
    """Replace this week's section of ANSWERS.md, or add it in week order."""
    if not path.exists():
        return header + '\n' + section
    text = path.read_text(encoding='utf-8')
    blocks = re.split(r'(?m)^(?=## )', text)
    head, sections = blocks[0], [b for b in blocks[1:] if not b.startswith(f'## {week}\n')]
    sections.append(section)
    sections.sort(key=lambda b: b.split('\n', 1)[0])
    return head.rstrip('\n') + '\n\n' + '\n'.join(s.rstrip('\n') + '\n' for s in sections)


HEADER = """# Answers

Every ClassPoint activity this course has run, one link per line. The pages are public —
no login — and each one shows what the room submitted. The same links are on the question
slides themselves.

Written by [classpoint.py](https://github.com/venetanji/classpoint.py)'s `weekly.py`.
"""


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    p.add_argument('activities', nargs='*', metavar='ID_OR_URL')
    p.add_argument('--repo', required=True, type=Path, help='course repo root')
    p.add_argument('--week', required=True, help='deck name, e.g. week01')
    p.add_argument('--from-html', metavar='FILE', action='append', default=[],
                   help='saved /cp/reports/activities page (repeatable)')
    p.add_argument('--on', metavar='YYYY-MM-DD', help='keep only activities run on this date')
    p.add_argument('--link-anonymous', action='store_true',
                   help='link activities run with names hidden anyway (read weekly.py first)')
    p.add_argument('--dry-run', action='store_true')
    args = p.parse_args(argv)

    refs = [reports.activity_id(a) for a in args.activities]
    for f in args.from_html:
        refs.extend(reports.from_list_html(Path(f)))
    if not refs:
        p.error('nothing to fetch — pass activity ids or --from-html')

    entries = collect(refs, on=args.on, link_anonymous=args.link_anonymous)
    if not entries:
        print('no activities matched', file=sys.stderr)
        return 1

    mapping = args.repo / 'deck' / f'{args.week}-reports.json'
    deck = args.repo / 'deck' / f'{args.week}.py'
    if deck.exists():
        questions = deck_questions(deck)
        if len(questions) == len(entries):
            for e, q in zip(entries, questions):
                e['question'] = q
        else:
            print(f'! {deck.name} has {len(questions)} ClassPoint slides but {len(entries)} '
                  f'activities ran — leaving the questions blank. Check the date filter, and '
                  f'that nothing was launched twice.', file=sys.stderr)
    else:
        print(f'! no {deck} — a week delivered before the deck existed. Write the questions '
              f'into {mapping.name} by hand and they will survive from here on.', file=sys.stderr)

    # Anything already recorded against this activity wins over a blank, so a
    # question typed in by hand is not lost the next time this runs.
    for e in entries:
        if not e['question'] and e['activity']:
            e['question'] = prior_questions(mapping).get(e['activity'])

    answers = args.repo / ANSWERS
    body = json.dumps(entries, indent=2, ensure_ascii=False) + '\n'
    md = splice(answers, args.week, answers_md(args.week, entries), HEADER)

    for path, content in ((mapping, body), (answers, md)):
        print(f'{"would write" if args.dry_run else "wrote"} {path}', file=sys.stderr)
        if not args.dry_run:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding='utf-8')
    if args.dry_run:
        print(body)

    linked = sum(1 for e in entries if e['activity'])
    print(f'\n{linked} of {len(entries)} activities linked. Next: deckgen build, then commit '
          f'both files.', file=sys.stderr)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
