# Live image upload and short answer

## Status

The experimental HTML presenter now supports **multiple choice, single image
upload, and short answer**. PR #3 originally contained only a handoff; it now
implements the activity selection, typed start messages, bounded response
normalization, and operator-only image/text results. It remains an unofficial
experimental integration. **Image upload has not been verified in a live class.**

Source inspection on 2026-10-21 found the exact outgoing builder in ClassPoint's
public presenter app and image/text submission formats in its public student
app. See [protocol evidence](live-protocol-evidence.md) for asset URLs, SHA256
hashes, field provenance, offsets and remaining uncertainty. These are better
than guessing from PPTX serialization, but are not a backend API contract.
No vendor bundle, embedded storage permission, capture, TLS key, instructor
identity, student submission or real join code is committed.

## What changed

- A shared typed activity boundary validates manifest options before any remote
  operation. Image-only and text-only decks can start a class. All three badge
  types work by click or keyboard; unsupported activities remain passive.
- Start and switch use the same payload builder. Image IDs use `iu`, text IDs
  use `sa`; MC keeps `mc`. Image/text messages contain no MC-only fields.
- Image responses are JSON `[URL, caption]`; text responses are HTML strings
  converted to plain text. Captions/text use DOM text nodes, never `innerHTML`.
  Names are not returned in the local UI state; `hide_names` is forwarded but
  is **not a promise of server-side anonymity**.
- Response IDs deduplicate within the active activity. At most 512 distinct
  responses are retained; existing IDs can still update at capacity. Raw text
  is limited to 8,192 characters and captions to 4,096 characters. Malformed/deeply nested
  response data is ignored. A visible limit indicator warns when new responses
  are omitted at capacity; existing IDs can still update. Capacity is a local memory guard, not an account
  quota or a claim about the server's limits.
- The gallery fetches only unsigned HTTPS `/user/` images from the **observed
  student storage host `cpfile11.blob.core.windows.net`**. This is distinct from
  instructor slide storage (`cpblob...`). Other-host images, signed URLs and
  unsupported paths are redacted to a placeholder while retaining captions.
  There is no server-side image proxy or arbitrary URL fetch. The operator
  page CSP restricts images to that origin and self, including redirects.
  External stock/search images and other storage regions are intentionally
  not previewed until explicitly validated. Broken media leaves controls usable.
- Navigating alone preserves the active activity's results even on a different
  activity-type slide. Opening another question clears the old results. The
  separate audience window remains read-only and never receives the gallery.

## Submission policy

The observed official presenter converts legacy `multiple=True` to three short
answers but **one image**. Rather than silently promise multiple image uploads,
this version rejects `image_upload` with `multiple=True`. Use `multiple=False`
(or omit it) for a single image; `caption_required` and `hide_names` are strict
booleans. Short answer supports one response by default or three with
`multiple=True`. There is no invented zero/minus-one unlimited mode. Countdown,
grading, rich text formatting, deletion synchronization and automatic reconnect
remain outside this change. Close/end use the existing explicit lifecycle and
failed-start cleanup.

## Reproduce offline

```sh
uv run --no-project --python 3.12 python tests.py
cd experiments/html-presenter
uv sync --locked
uv run python test_activities.py
uv run python validate.py --protocol-only
uv run playwright install --with-deps chromium
uv run python validate.py
```

Deckgen remains pinned to `9990546c01865807e6aaac5aaa50977b4b6b916a` (v0.11.2).
The new GitHub workflow runs on Ubuntu 24.04. All fixtures are synthetic, and
browser thumbnail requests are fulfilled locally with a four-pixel image;
unexpected external browser requests fail the check. Tests never open a real
class or upload to Azure. The full validator covers request guards, MC lifecycle,
image/text lifecycle, typed messages, deduplication, rejected starts, cleanup,
join-code checks, desktop/mobile UI and passive audience behavior, plus mixed
MC/image/text navigation, caption safety and blocked third-party images.

Local results in the cloud session: existing 35 checks pass; ten typed/safety
unit tests pass; mock SignalR image/text/MC lifecycle checks pass. JavaScript
syntax checks pass. Full browser execution is currently blocked locally:
Playwright's browser download returned an invalid archive; the installed
Chromium cannot create its process singleton socket in this sandbox. The browser
checks are therefore **not claimed as locally passed**; see the PR's exact-head
GitHub workflow result for browser evidence.

## Required instructor-run live acceptance

Use your own existing private capture/configuration locally; do not upload it,
TLS keys or signed URLs into a PR or chat. Close PowerPoint. Use a trusted demo
deck with an image-upload slide (single submission, caption required) and an MC
slide, plus a short-answer slide if testing that companion feature:

```sh
cd experiments/html-presenter
uv run python presenter.py --capture /private/path/test.pcapng \
  --key-log /private/path/classpoint-tls-keys.log \
  --project /path/to/trusted/deckgen/project --deck test
```

1. Loading the local page must not create a class. Explicitly click Start.
2. Check the expected join code. Join with your own test participant, not a
   student roster. Submit a harmless synthetic image and a non-sensitive caption
   through the existing ClassPoint student app.
3. Confirm one gallery item/caption, retry/update behavior, and Close stops new
   submissions. Navigate to MC without opening it: the image should remain.
4. Open MC, submit an answer and verify the histogram; switch back to image.
   If testing short answer, verify plain text and one/three-response limits.
5. End class explicitly and confirm the participant sees it end. On any error,
   use End class before retrying; forced process shutdown cannot assure cleanup.

Only after this check can the PR claim live student image upload works. Record
pass/fail and software/account conditions without publishing identities, real
codes, captions, screenshots of students or credential-bearing traffic. Uploaded
images may persist after a class ends. This change does not add deletion.

The later reusable client/deckgen extraction remains separate; see
[live presenter plan](live-presenter-plan.md). No `deckgen present --classpoint`
command is shipped by this POC.
