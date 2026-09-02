"""
Embed real ClassPoint activity buttons into a .pptx.

ClassPoint stores each activity as a slide *shape*, not slide metadata: the
button you click in class is a `<p:pic>` carrying the button artwork, and hung
off its `<p:nvPr>` is a `<p:custDataLst>` pointing at a `ppt/tags/tagN.xml`
part whose single `ACTIVITYMODEL` tag holds the activity as escaped JSON.

Everything here was read out of a real deck that had a working Short Answer,
Word Cloud and Multiple Choice on it — nothing is guessed.

The button artwork belongs to Inknoe, ClassPoint's authors, so it is not
redistributed here. `extract_buttons()` pulls it out of any deck of your own
that already has activities on it; run that once and `assets/` fills itself.

python-pptx does the parts it understands — slides, text, placing the picture
and wiring its media relationship. This module only adds what it cannot know
about: the tag part, its relationship, and the `custDataLst` that binds the
two. Run `verify()` on the result; a malformed tag fails silently in
PowerPoint, which is the worst way to find out.
"""

from __future__ import annotations

import html
import json
import re
import shutil
import zipfile
from pathlib import Path

ASSETS = Path(__file__).parent / 'assets'

# The name ClassPoint gives its own button shapes. Keeping it means the add-in
# recognises them, and it is how inject() finds the picture to bind a tag to.
SHAPE_NAME = 'btnInknoeActivityCp2'

# Native button size, straight off the reference deck. 2222048 x 581015 EMU.
BUTTON_W_EMU = 2222048
BUTTON_H_EMU = 581015

TAG_CONTENT_TYPE = 'application/vnd.openxmlformats-officedocument.presentationml.tags+xml'
TAG_REL_TYPE = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/tags'


def _activity(name: str, activity_type: int, base: dict) -> dict:
    return {
        '$type': 'ClassPoint2.Core.Model.Activity, ClassPoint2.Core',
        'ActivityId': None,
        'Name': name,
        'ActivityType': activity_type,
        'Width': 0.0,
        'Height': 0.0,
        'Graphics': None,
        # activityId stays null: ClassPoint mints one the first time the
        # activity is run. The reference deck has both null and populated ids.
        'ActivityBase': base,
        'IsLocked': False,
        'IsMappedFromCp1': False,
        'IsQuizMode': False,
    }


def word_cloud(*, submissions: int = 5, countdown: int = 0) -> dict:
    return _activity('WordCloud', 2, {
        '$type': 'ClassPoint2.Core.DTO.Activities.WordCloudActivity, ClassPoint2.Core',
        'numOfSubmissionsAllowed': submissions,
        'activityId': None,
        'activityType': 'Word Cloud',
        'countdown': countdown,
        'StartWithSlide': False,
        'CanMinimize': False,
        'CanCountDown': False,
    })


def short_answer(*, multiple: bool = False, hide_names: bool = False, countdown: int = 0) -> dict:
    return _activity('ShortAnswers', 1, {
        '$type': 'ClassPoint2.Core.DTO.Activities.ShortAnswerActivity, ClassPoint2.Core',
        'isMultipleSubmissionsAllowed': multiple,
        'isNamesHidden': hide_names,
        'gradingInstructions': None,
        'activityId': None,
        'activityType': 'Short Answer',
        'countdown': countdown,
        'StartWithSlide': False,
        'CanMinimize': False,
        'CanCountDown': False,
    })


def multiple_choice(choices: list[str], *, select_multiple: bool = False, countdown: int = 0) -> dict:
    strlist = 'System.Collections.Generic.List`1[[System.String, mscorlib]], mscorlib'
    return _activity('MultipleChoice', 0, {
        '$type': 'ClassPoint2.Core.DTO.Activities.MultipleChoiceActivity, ClassPoint2.Core',
        'mcChoices': {'$type': strlist, '$values': list(choices)},
        'mcIsAllowSelectMultiple': select_multiple,
        'mcCorrectAnswers': {'$type': strlist, '$values': []},
        'isQuizMode': False,
        'correctPoints': 0,
        'correctSpeedBonus': None,
        'HasCorrectAnswers': False,
        'activityId': None,
        'activityType': 'Multiple Choice',
        'countdown': countdown,
        'StartWithSlide': False,
        'CanMinimize': False,
        'CanCountDown': False,
    })


BUTTON_IMAGE = {
    'WordCloud': ASSETS / 'btn-word-cloud.png',
    'ShortAnswers': ASSETS / 'btn-short-answer.png',
    'MultipleChoice': ASSETS / 'btn-multiple-choice.png',
}

FILENAME_FOR = {
    'WordCloud': 'btn-word-cloud.png',
    'ShortAnswers': 'btn-short-answer.png',
    'MultipleChoice': 'btn-multiple-choice.png',
}


def extract_buttons(pptx_path: Path, out_dir: Path = ASSETS) -> dict[str, Path]:
    """Pull ClassPoint's button artwork out of a deck that already uses it.

    The images are Inknoe's, not ours, so they are not shipped with this
    module. Point this at any of your own decks with activities on it and the
    buttons it finds are written to `out_dir`, ready for build-time use.

    Returns {activity name: path written}.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written = {}

    with zipfile.ZipFile(pptx_path) as z:
        # tag part -> owning slide
        owner = {}
        for name in z.namelist():
            m = re.match(r'ppt/slides/_rels/(slide\d+)\.xml\.rels$', name)
            if not m:
                continue
            rels = z.read(name).decode('utf-8')
            for tag in re.findall(r'Target="\.\./tags/(tag\d+\.xml)"', rels):
                owner[tag] = m.group(1)

        for tag, slide in owner.items():
            xml = z.read(f'ppt/tags/{tag}').decode('utf-8')
            found = re.search(r'name="ACTIVITYMODEL" val="(.*?)"/>', xml, re.S)
            if not found:
                continue
            kind = json.loads(html.unescape(found.group(1)))['Name']
            if kind in written:
                continue

            slide_xml = z.read(f'ppt/slides/{slide}.xml').decode('utf-8')
            anchor = slide_xml.find(f'name="{SHAPE_NAME}"')
            if anchor < 0:
                continue
            pic = slide_xml[slide_xml.rindex('<p:pic>', 0, anchor):slide_xml.index('</p:pic>', anchor)]
            blip = re.search(r'<a:blip r:embed="(rId\d+)"', pic)
            if not blip:
                continue
            rels = z.read(f'ppt/slides/_rels/{slide}.xml.rels').decode('utf-8')
            target = re.search(rf'Id="{blip.group(1)}"[^>]*Target="([^"]+)"', rels)
            if not target:
                continue

            media = 'ppt/' + target.group(1).replace('../', '')
            path = out_dir / FILENAME_FOR.get(kind, f'btn-{kind.lower()}.png')
            path.write_bytes(z.read(media))
            written[kind] = path

    return written

_TAG_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n'
    '<p:tagLst xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
    ' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    ' xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
    '<p:tag name="ACTIVITYMODEL" val="{value}"/></p:tagLst>'
)


def inject(pptx_path: Path, activities: dict[int, dict]) -> None:
    """Bind an activity to the button picture already placed on each slide.

    `activities` maps a 1-based slide number to an activity dict. The slide
    must already carry a picture named SHAPE_NAME — build_deck() places it.
    """
    pptx_path = Path(pptx_path)
    tmp = pptx_path.with_suffix('.tmp.pptx')
    with zipfile.ZipFile(pptx_path) as src:
        parts = {n: src.read(n) for n in src.namelist()}

    existing = len([n for n in parts if n.startswith('ppt/tags/tag')])
    for offset, (slide_no, activity) in enumerate(sorted(activities.items()), start=existing + 1):
        slide_name = f'ppt/slides/slide{slide_no}.xml'
        if slide_name not in parts:
            raise KeyError(f'{slide_name} is not in {pptx_path.name}')

        tag_part = f'ppt/tags/tag{offset}.xml'
        payload = json.dumps(activity, separators=(',', ':'))
        parts[tag_part] = _TAG_XML.format(value=html.escape(payload, quote=True)).encode('utf-8')

        # Relationship from the slide to its new tag part.
        rels_name = f'ppt/slides/_rels/slide{slide_no}.xml.rels'
        rels = parts[rels_name].decode('utf-8')
        used = {int(m) for m in re.findall(r'Id="rId(\d+)"', rels)}
        rid = f'rId{max(used) + 1 if used else 1}'
        rels = rels.replace(
            '</Relationships>',
            f'<Relationship Id="{rid}" Type="{TAG_REL_TYPE}" Target="../tags/tag{offset}.xml"/></Relationships>',
        )
        parts[rels_name] = rels.encode('utf-8')

        # Bind it to the button picture. python-pptx leaves <p:nvPr/> empty and
        # self-closed on a plain picture, which is what we expand here.
        slide = parts[slide_name].decode('utf-8')
        anchor = slide.index(f'name="{SHAPE_NAME}"')
        nvpr = slide.index('<p:nvPr/>', anchor)
        slide = (
            slide[:nvpr]
            + f'<p:nvPr><p:custDataLst><p:tags r:id="{rid}"/></p:custDataLst></p:nvPr>'
            + slide[nvpr + len('<p:nvPr/>'):]
        )
        parts[slide_name] = slide.encode('utf-8')

        ct = parts['[Content_Types].xml'].decode('utf-8')
        ct = ct.replace('</Types>', f'<Override PartName="/{tag_part}" ContentType="{TAG_CONTENT_TYPE}"/></Types>')
        parts['[Content_Types].xml'] = ct.encode('utf-8')

    with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as out:
        for name, data in parts.items():
            out.writestr(name, data)
    shutil.move(tmp, pptx_path)


def verify(pptx_path: Path) -> list[dict]:
    """Read the activities back out. A tag PowerPoint cannot parse looks fine
    on disk, so always check the file you just wrote."""
    found = []
    with zipfile.ZipFile(pptx_path) as z:
        slide_of = {}
        for name in z.namelist():
            m = re.match(r'ppt/slides/_rels/slide(\d+)\.xml\.rels$', name)
            if not m:
                continue
            for tag in re.findall(r'Target="\.\./tags/(tag\d+\.xml)"', z.read(name).decode('utf-8')):
                slide_of[tag] = int(m.group(1))

        for tag, slide_no in sorted(slide_of.items(), key=lambda kv: kv[1]):
            xml = z.read(f'ppt/tags/{tag}').decode('utf-8')
            raw = re.search(r'name="ACTIVITYMODEL" val="(.*?)"/>', xml, re.S).group(1)
            model = json.loads(html.unescape(raw))
            slide_xml = z.read(f'ppt/slides/slide{slide_no}.xml').decode('utf-8')
            bound = f'name="{SHAPE_NAME}"' in slide_xml and '<p:custDataLst>' in slide_xml
            found.append({'slide': slide_no, 'name': model['Name'], 'bound': bound,
                          'choices': model['ActivityBase'].get('mcChoices', {}).get('$values')})
    return found
