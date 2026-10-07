# Deckgen / ClassPoint HTML Presenter POC

Present a real **deckgen HTML deck**, start your ClassPoint class, send the current
slide, and open multiple choice. Students still join and submit in ClassPoint's
existing student app. PowerPoint is not required.

This is an unofficial protocol experiment, not an Inknoe-supported integration.
The POC imports the instructor identity and signed upload configuration from your
own decrypted test capture. The instructor confirmed that the POC worked in a
live test on 2026-10-04. It does not implement login or establish that the
server accepts every independently created presenter session.

This directory preserves the working POC for a cloud-session handoff. It is not
yet a stable library API. See `../../docs/live-presenter-plan.md` for the two-PR
split: a renderer-independent client here, followed by a deckgen presenter adapter.

## What the capture shows

The add-in is a client of a ClassPoint SignalR WebSocket hub. The observed flow is:

1. `PresenterStartSlideshow` supplies the instructor profile, slide count, and class settings.
2. `ClassSessionUpdated` returns the join code and participant list.
3. A signed Azure PUT uploads a slide image. PowerPoint does not send the slide's editable content.
4. `PresenterGotoStep` broadcasts the image URL, slide index, and animation step.
5. `PresenterStartActivity` opens multiple choice with an activity ID, image URL, and choice labels.
6. `ParticipantSubmittedResponse` delivers answers; `responseData` is a JSON-encoded string.

An HTML presenter can reproduce those messages using a rendered HTML-slide image.
The captured WebSocket handshake has no Authorization header or access-token query;
that does **not** establish that the backend skips authorization. The instructor
identity and signed upload permission are still private. One successful live test
does not establish a supported third-party authentication/authorization contract.

## Verification

Local validation uses synthetic presenter profiles and covers deckgen demo and course
loading, real 1920x1080 Reveal screenshots, request guards, and the full
SignalR/upload lifecycle against a local mock server. Browser checks cover desktop
and mobile layouts, activity badge click/keyboard access, answer tallies, class
shutdown, and retry after rejection. It also verifies configured join-code checks
and the audience window's slide, fragment, pause and reload behavior.
No live ClassPoint class is started by these checks.

### Cloud-safe validation

No capture, TLS key log, account, or ClassPoint access is needed for these checks:

```bash
cd experiments/html-presenter
uv sync --locked
uv run playwright install chromium
uv run python validate.py
```

On a Linux runner, Chromium may also need OS dependencies; use Playwright's
`install --with-deps chromium` where the environment permits it. The validation
starts mock ClassPoint/Azure services on loopback, exercises the real deckgen
renderer and browser controls, and writes mock screenshots under the OS temporary
directory. Browser checks block external asset requests. The pinned deckgen
dependency is installed from GitHub, so dependency installation needs network access.

Actual classroom use still needs your own private capture and matching TLS keys.
Neither is included in this repository or required by `validate.py`.

## Run the acceptance test

From this directory:

```powershell
uv run presenter.py
```

Open `http://127.0.0.1:8765`. The default slide is built with
`deckgen.layouts.question()` from `demo_deck.py`, using the real deckgen HTML
renderer, Reveal.js, fonts, and activity spec.

1. Close PowerPoint so it does not compete for the same presenter account.
2. Click **Start class + question**, or the multiple-choice badge in the slide.
3. On another device, open `https://www.classpoint.app/` and enter the displayed code.
4. Confirm the slide appears, choose **B**, and submit. The live B tally should increase.
5. Click **Close submissions**, then **End class**.

The start action creates/resumes the class, uploads a screenshot of the actual
deckgen HTML, sends `PresenterGotoStep`, and opens `PresenterStartActivity`.
There are no ClassPoint requests before an explicit Start action. Starting the
local server only decrypts your capture and builds local HTML.

The matching TLS key log defaults to `%TEMP%\classpoint-tls-keys.log`. The capture
defaults to the most recently modified `.pcapng` in this directory. Override both:

```powershell
uv run presenter.py `
  --capture "create class, submit multiplechoice, give stars.pcapng" `
  --key-log "$env:TEMP\classpoint-tls-keys.log"
```

Requirements: Python 3.11+, `uv`, Wireshark's `tshark` on PATH, your own capture with
the matching TLS keys, and Chromium. Dependencies are installed by `uv`.
The bridge uses an existing Playwright Chromium installation on Windows when available.
Otherwise:

```powershell
uv run playwright install chromium
```

`CLASSPOINT_CHROMIUM` can point to a specific Chromium executable.

## Use a course deck

The existing deckgen source spec remains the source of truth:

```powershell
uv run presenter.py --project "C:\path\to\your-course" --deck week01
```

The project must contain `deckgen.toml` and `deck/week01.py`. The presenter uses
deckgen's normal loader and HTML builder, with generated site files kept in a
temporary directory. It does not patch deckgen, your course sources, or classpoint.py.
As with a normal deckgen build, executing a trusted deck module can run its own
figure-generation/import code. Do not point `--project` at an untrusted course repo.

The first multiple-choice slide is selected initially. Reveal's arrows, fragments,
and notes still work. Click **Open this question** on another multiple-choice slide
to end the previous activity and start the new one in the same class. Slide changes
are debounced and synchronized to the student viewer while the class is active.
The existing `[data-classpoint]` badge is made keyboard/click actionable in the local
presenter only; published decks and report links are not modified.

## Audience Screen

Click **Open audience screen** to open a separate read-only window for the
projector. Keep the operator controls and response tallies on the laptop. The
audience follows the operator's current Reveal slide, fragments and pause state
over a local BroadcastChannel, and displays the join code returned by ClassPoint.
Press **F** in the audience window for fullscreen and Escape to exit.

Reloading the audience requests the current state from the operator. This is
local window recovery, not remote ClassPoint reconnection. If the operator goes
away, the audience displays a disconnected notice until it returns. Closing only
the audience window does not end the class. Use **End class** before stopping the
POC server.

## Configured Join Codes

Integrations can set `Profile.class_options["classCode"]` to request and verify a
selected join code. If ClassPoint returns a different code, startup fails before
uploading the slide or opening the question and attempts to end the incomplete
class. If cleanup cannot be confirmed, **End class** remains available for retry.
The UI always displays the returned code; it never substitutes the requested
value. Without an expected code, startup accepts and displays the returned code.

## Boundaries and Privacy

- Instructor identity and Azure SAS signatures stay in bridge memory. They are
  never embedded in generated HTML, returned by the UI API, or written to logs.
- The local server binds to `127.0.0.1`, rejects unexpected Host/Origin values,
  and requires a per-process token for commands. Do not expose it to the internet.
- Starting a class explicitly uses your captured upload permission to create new
  `slides/poc-slide-*.jpg` objects. It does not list, overwrite, or delete existing
  captured slide files. Uploaded images are accessible to students and may remain
  in ClassPoint's storage after class ends. Do not include confidential slide content.
- A class can be resumed rather than newly created, as in the captured official
  client flow. Do not run two presenters against the same account.
- The capture contains active signed upload URLs and personal classroom data.
  Keep captures, TLS key logs, and credentials out of Git. `.gitignore` excludes them.
- Authentication may require more than the captured fields. If the server rejects
  a command, the POC reports the rejection; it does not guess credentials or escalate
  the class limit. The class limit is taken from your own capture.

## Current Limits

Only multiple choice is wired. Stars, quiz grading, countdowns, report persistence,
and automatic reconnect are not implemented. A fresh screenshot captures the
specified slide/fragment in a headless browser, not live DOM edits or the current
state of an interactive sketch/video in the presenting browser. Those require a
future in-browser snapshot/state-transfer path. This proves the static HTML-slide
and multiple-choice workflow first.

Always end the class with the button before stopping the server. Graceful shutdown
also attempts to end it, but a disconnected server or forced termination cannot
guarantee remote cleanup.
