# classpoint.py

Put working **[ClassPoint](https://www.classpoint.io/) activity buttons into a `.pptx` from
Python** — Word Cloud, Short Answer, Multiple Choice — so a generated deck arrives with its
interactive questions already live, instead of you clicking through the add-in ribbon afterwards.

Not affiliated with Inknoe. Written by reading the file format.

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

## Caveats

- `inject()` needs the button picture to already exist on the slide, named `cp.SHAPE_NAME`.
- Requires `python-pptx`. Python 3.9+.
- Tested against ClassPoint 2 tags. If Inknoe changes the schema this will need re-reading —
  which takes about ten minutes with `verify()` and a deck saved from the add-in.

## Licence

Code: do what you like with it. The button PNGs, if you extract them, are Inknoe's.
