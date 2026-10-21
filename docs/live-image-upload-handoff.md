# Live image upload and short answer: cloud-session handoff

Status: investigation and implementation brief, 21 October 2026. This document
does not implement either activity or claim a successful live test.

## Problem and desired behavior

The HTML presenter can show a deck containing `image_upload` and `short_answer`
metadata, but it can open only multiple-choice activities. A presenter should be
able to open an image activity, let students submit through the existing
ClassPoint student app, and review images and captions locally. Short-answer
activities should similarly collect and display text. Existing multiple-choice,
class cleanup, audience-screen and join-code behavior must keep working.

The immediate example is [SD5913 teaching PR #10](https://github.com/sd5913/teaching/pull/10),
head `c8cc10dee5b1ddcac7b6e0f05a76bfe576358ae4`, for 22 October 2026:

- Slide 23: `short_answer`, multiple submissions allowed, AMA inbox.
- Slide 31: `short_answer`, one submission, team idea.
- Slide 32: `image_upload`, team project mock-up.

All three are rejected by the current selection guard. The deck has no
multiple-choice activity, so the current UI also has no supported activity from
which to start the class. Its paired [PFAD PR #10](https://github.com/sd5913/pfad/pull/10)
contains matching student instructions. Use synthetic content for automated
coverage; neither course repository nor student submissions should be required.

## Starting point and ownership

Check out this handoff PR branch, based on this repository's `main`. The reviewed baseline is
`a3cef33c3844346bdf721dc7641d83ff4fecd748`, which merged the working POC in
[PR #2](https://github.com/venetanji/classpoint.py/pull/2). Read
[the POC README](../experiments/html-presenter/README.md) and
[the existing two-PR integration plan](live-presenter-plan.md) first.

The protocol implementation currently lives in
`experiments/html-presenter/bridge.py`. Keep protocol work in this repository;
deckgen owns slide rendering and its eventual presenter adapter. The extraction
of a reusable live client and the packaged deckgen presenter remain separate
work described in [deckgen PR #11](https://github.com/ait4x/deckgen/pull/11).
Do not duplicate the live protocol in deckgen or require a broad extraction just
to investigate these activity types. If extraction lands first, extend its client
and adapt this file map to the new locations.

The course uses deckgen pinned to `v0.11.2`, commit
`9990546c01865807e6aaac5aaa50977b4b6b916a`; the POC pins that same commit.
No dependency upgrade is needed to investigate this gap. There is no shipped
`deckgen present --classpoint` command to assume in setup instructions.

## What the source already establishes

| Location | Current behavior | Work needed |
| --- | --- | --- |
| `experiments/html-presenter/deck.py`, `Deck.selection()` | Rejects every type except `multiple_choice`; requires 2-6 choices; discards other type-specific options. | Validate and pass a typed activity specification. Require choices only for multiple choice. |
| `experiments/html-presenter/deck.py`, `render_deck()` | Selects the first multiple-choice slide, otherwise slide zero. | Select the first supported activity even when the deck contains only image/text activities. |
| `experiments/html-presenter/web/presenter.js` | `canOpenQuestion()`, badge wiring, labels and response display assume multiple choice. | Enable supported types and render their appropriate controls/results. Preserve passive audience behavior. |
| `experiments/html-presenter/bridge.py`, `activity_id()` | Generates an `mc` prefix for every new activity. | Verify and generate the appropriate ID for each supported type. |
| `experiments/html-presenter/bridge.py`, `start()` and `start_activity()` | Both construct a Multiple Choice start message with `mcChoices` and related fields. | Share verified type-aware message construction across initial startup and activity switching. |
| `experiments/html-presenter/bridge.py`, `handle_message()` and `state()` | Parses response lists and filters values against the current choices; state exposes lists for vote tallies. | Normalize text and image submissions without losing captions, media or response identity. |
| `experiments/html-presenter/validate.py` | Uses synthetic profiles, a loopback hub/upload mock and real browser rendering. | Extend these existing protocol and browser acceptance cases. |

Deckgen already renders the Image Upload badge and writes the corresponding PPTX
activity model. See its pinned
[ClassPoint exporter](https://github.com/ait4x/deckgen/blob/9990546c01865807e6aaac5aaa50977b4b6b916a/src/deckgen/classpoint/__init__.py#L258):
`ImageUpload`, numeric `ActivityType` 4, and options for multiple submissions,
hidden names and required captions. Those are PPTX serialization facts; they do
not by themselves establish the live hub request schema.

This repository's `reports.py`, `_split_response()`, already handles report-side
image responses shaped as JSON `[url, caption]` and short answers containing HTML.
Its offline tests provide useful synthetic examples. Report data is a starting
point, not proof that live events have an identical shape.

`Bridge.upload_slide()` uploads the instructor's question screenshot. Student
image submission is a different flow. Do not add a public upload endpoint or
increase the local command-body limit to implement this feature by assumption.

## Protocol questions to resolve before enabling the UI

1. Verify the image and short-answer `PresenterStartActivity` messages: exact
   activity type strings, IDs, required/optional fields and submission options.
   Check initial startup and switching from an already active activity. Do not
   derive the wire message solely from the PPTX model or just rename the MC type.
2. Verify live response envelopes, response IDs, media URL/caption representation,
   short-answer content, duplicate delivery and any submission-update behavior.
   Establish whether student uploads require any additional presenter command.
3. Confirm close-submissions, end-activity and end-class behavior for these types,
   including rejected starts and uncertain cleanup.

Use legitimately available, authorized evidence. If a cloud session lacks the
necessary capture or account access, record the exact missing protocol evidence
and continue with offline investigation. Do not silently label a guessed schema
as verified. A later local capture or explicitly started live test can resolve
that gap; credentials and real responses must stay outside this repository.

## Proposed implementation sequence

1. Document verified protocol fields and provenance without publishing raw
   captures. Add minimal synthetic fixtures derived from the confirmed shapes.
2. Add a typed activity selection/validation path. Preserve `multiple`,
   `hide_names`, `caption_required` where applicable, plus existing MC options.
   Keep unsupported types rejected before any remote action.
3. Implement shared start-message/ID construction and per-type response
   normalization in the bridge or extracted live client. Preserve deduplication
   and existing lifecycle/error handling; keep MC behavior compatible.
4. Wire local presenter badges, initial selection and operator results. Show
   text submissions and image thumbnails/captions with submission counts. Treat
   captions as text, handle invalid/unavailable images without breaking controls,
   and validate media URLs before any fetch or display. Keep credentials out of
   state, HTML, logs and errors. Honor the verified name-hiding behavior without
   promising server-side anonymity.
5. Extend offline protocol/browser tests, then document an explicit local live
   acceptance procedure and the remaining limitations.

Image upload is the primary deliverable. Short answer addresses the companion
Week 7 blockers and should be tracked/tested separately, so image support can be
reviewed independently. Stars, grading, report persistence, reconnect, countdown
support, new login flows, live sketch/video snapshots and other activity types
remain outside this scope.

## Acceptance checks

- [ ] Image-only and text-only synthetic decks can start their first supported
  activity. Badges and keyboard controls work; existing report links and
  published decks remain passive.
- [ ] Mock tests assert verified type-specific outgoing messages and options
  for initial start and switching; MC-only fields do not leak into other types.
- [ ] Image responses retain media and captions, including empty/Unicode
  captions; text responses display safely. Duplicate response events do not
  inflate counts, and malformed submissions do not break the session.
- [ ] The operator can review images and text; the audience stays read-only.
  Broken media does not disable close/end controls.
- [ ] Existing MC voting, slide/fragment synchronization, audience reload,
  configured join-code verification and cleanup/retry checks still pass.
- [ ] Tests cover rejected activity starts, closing submissions, switching and
  ending, including failure paths. Unsupported types make no remote request.
- [ ] Importing, rendering, opening a page and automated tests start no real
  class. Existing account capacity is preserved. No raw captures, TLS keys,
  signed URLs, account profiles or real student data enter fixtures or PR logs.
- [ ] A separate, explicitly initiated local test confirms students can join,
  submit an image and caption, and see submissions close; the operator receives
  the submission and ends the class. Repeat for short answer if implemented.
  Record actual results and limitations rather than treating mock success as
  live compatibility.

## Cloud-safe baseline commands

From the repository root:

```bash
uv run --no-project --python 3.12 python tests.py
cd experiments/html-presenter
uv sync --locked
uv run playwright install chromium
uv run python validate.py
```

On a supported Linux runner, Playwright may require
`uv run playwright install --with-deps chromium`. The validator uses loopback
services and synthetic identities; no capture, instructor login or live class is
required. Dependency/browser installation requires network access. Run the
baseline before editing, then extend the same checks for the new activities.

The follow-up implementation PR should report which protocol facts were verified,
the offline test results and any live test still pending. This handoff alone
does not establish classroom readiness.
