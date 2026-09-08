# classpoint.py

Put working **[ClassPoint](https://www.classpoint.io/) activity buttons into a `.pptx` from
Python** — Word Cloud, Short Answer, Multiple Choice — so a generated deck arrives with its
interactive questions already live, instead of you clicking through the add-in ribbon afterwards.

And read the answers back out afterwards, so a class's activities can be linked from the
slides they were asked on. Not affiliated with Inknoe. Written by reading the file format,
and the wire.

```python
import classpoint as cp

# your build step places a picture named cp.SHAPE_NAME on each slide, then:
cp.inject('deck.pptx', {
    2: cp.word_cloud(submissions=5),
    5: cp.short_answer(hide_names=True),
    9: cp.multiple_choice(['A', 'B', 'C', 'D'], select_multiple=True),
})

cp.verify('deck.pptx')   # always — see below
```

`example.py` builds a three-question deck end to end.

## Get the button artwork

The buttons belong to Inknoe, so they are not shipped here. Pull them out of any deck of your
own that already has ClassPoint activities on it:

```python
cp.extract_buttons('some-deck-with-activities.pptx')   # fills assets/
```

## How ClassPoint stores an activity

An activity is **a shape, not slide metadata**. That is the part that surprises. Four pieces
have to line up, and if any one is missing PowerPoint ignores the whole thing *silently*:

1. **`ppt/tags/tagN.xml`** — a `<p:tagLst>` holding one `<p:tag name="ACTIVITYMODEL" val="…"/>`
   whose value is the activity as HTML-escaped JSON, typed for .NET deserialisation
   (`"$type": "ClassPoint2.Core.Model.Activity, ClassPoint2.Core"`).
2. **A relationship** in `ppt/slides/_rels/slideN.xml.rels` of type
   `…/officeDocument/2006/relationships/tags`, pointing at that part.
3. **A `<p:pic>`** on the slide carrying the button artwork, named `btnInknoeActivityCp2`, with
   `<p:custDataLst><p:tags r:id="rIdX"/></p:custDataLst>` inside its `<p:nvPr>` — so the tag
   hangs off the *picture*, not the slide.
4. **An `<Override>`** in `[Content_Types].xml` for the tag part.

`activityId` may be `null`; ClassPoint mints one the first time the activity runs.

Native button size is **2222048 × 581015 EMU** (`cp.BUTTON_W_EMU`, `cp.BUTTON_H_EMU`).

## Activity types

| Helper | `Name` | `ActivityType` | Options |
|---|---|---|---|
| `word_cloud()` | `WordCloud` | 2 | `submissions`, `countdown` |
| `short_answer()` | `ShortAnswers` | 1 | `multiple`, `hide_names`, `countdown` |
| `multiple_choice([…])` | `MultipleChoice` | 0 | `select_multiple`, `countdown` |

Slide Drawing, Image Upload, Fill in the Blanks and Video Upload are **not implemented** — they
were not in the deck this was reverse-engineered from. To add one: insert it by hand in
PowerPoint once, save, and `verify()` will read its JSON straight back out for you to copy.

## Always call `verify()`

A malformed tag looks fine on disk, opens without error, and simply does nothing when you click
it — in front of a room. `verify()` reads the activities back out of the saved file and reports
which slide each is bound to.

## Reading the answers back — `reports.py`

The other direction: after the class, pull out what the room actually submitted.

```bash
python3 reports.py sa20260904033646383JAAW              # one activity, to stdout
python3 reports.py --from-html activities.html \
        --csv answers.csv --json answers.json --media media/
```

Stdlib only — `reports.py` needs no `python-pptx` and no network library.

Every activity has a **public** page at `app.classpoint.io/activity/<activityId>`. The
reports dashboard it is linked from needs a login; the activity page does not, and it is
server-rendered, so all of the responses arrive in the first response — no pagination, no
session, no token. Sending `RSC: 1` returns just the React Server Component payload
(~36 KB rather than ~140 KB of markup); if that header ever stops being honoured, the same
JSON is unescaped out of the page's flight scripts instead.

`/cp/reports/activities` **is** behind the login, so there is no way to enumerate. Save
that page — devtools, copy the cards element — and `--from-html` scrapes the `aId=` links
out of it. Ids are self-describing, so filtering costs no requests: the two-letter prefix
is the type (`sa` `mc` `wc` `iu`, and `sd` `fb` `vu` `ar` unconfirmed) and the next 17
digits are the UTC timestamp. Hence `--type sa --since 2026-09-04`.

| Type | `responseData` | normalised to |
|---|---|---|
| Short Answer | `<p>…</p>` html | `text` |
| Word Cloud | bare word | `text` |
| Multiple Choice | `["C"]` | `text` |
| Image Upload | `[url, caption]` | `images` + `text` |

`Response.raw` keeps the original regardless. Slide Drawing, Fill in the Blanks, Video
Upload and Audio Record have not been seen — they take a generic path that will get text
out but may not recognise their media.

**The question is not in the payload.** Only `activitySlideSavedUrl`, a JPG of the slide it
was asked on; `--media` downloads it alongside any uploaded images. If your slides carry a
running footer, that picture is also the only thing that tells you which deck and week the
activity came from.

## The weekly routine — `weekly.py`

Puts the links back into the deck, so a student can find their own work weeks later.

```bash
python3 weekly.py --repo ~/dev/sd0000-teaching --week week01 \
        --on 2026-09-04 --from-html ~/Downloads/activities.html
```

Writes two files into the course repo and nothing else:

- **`deck/week01-reports.json`** — the mapping [`deckgen`](https://github.com/ait4x/deckgen)'s
  `attach_reports()` reads, which turns the eyebrow of each question slide into a link to
  that question's answers.
- **`ANSWERS.md`** — the same links, one per line, for anyone not opening the slides.

Then `deckgen build`, commit both, open a PR. Both files are rewritten in place, so running
it twice is the same as running it once.

Three things make it safe to run unattended:

- **Order is the contract.** ClassPoint mints an activity id the first time the activity
  runs, so one class's activities sort chronologically into exactly the order their slides
  appear in. Nothing needs slide numbers, and re-cutting a deck around its questions does
  not break the mapping.
- **The deck is parsed, not guessed.** `ast` walks `deck/week01.py` for `question(…)` calls
  and anything carrying a `cp=`, in source order, and writes each question's text into the
  mapping. deckgen checks that text again at build time, so a question rewritten later
  fails the build instead of quietly pointing students at the wrong answers.
- **Anonymous activities are withheld.** See below.

## ⚠️ Public means public

Anyone with an activity id can read every response on it, *and* the participant names. Two
consequences worth being deliberate about:

- Treat an activity id like the responses themselves. An exported `answers.csv` belongs
  wherever your roster lives, not in git.
- **`isNamesHidden` is not enforced in the payload.** ClassPoint's rendered page honours it,
  but the JSON behind that page still carries `participantName` for every response. An
  activity the room was told was anonymous can be de-anonymised by anyone who fetches it, so
  `weekly.py` records those with a null id and publishes no link. `--link-anonymous`
  overrides that, and you should have a reason.

## Tests

```bash
python3 tests.py        # everything offline: ids, dashboard scraping, response shapes,
                        # reading a deck, and what gets written
```

The network half — that `app.classpoint.io` still returns what `reports.py` expects — is
not faked, because a fake would only ever confirm itself. Run `python3 reports.py <id>`
against a real activity when the site changes under you.

## Caveats

- `inject()` needs the button picture to already exist on the slide, named `cp.SHAPE_NAME`.
- Requires `python-pptx`. Python 3.9+.
- Tested against ClassPoint 2 tags. If Inknoe changes the schema this will need re-reading —
  which takes about ten minutes with `verify()` and a deck saved from the add-in.

## Licence

Code: do what you like with it. The button PNGs, if you extract them, are Inknoe's.
