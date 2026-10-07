# Live ClassPoint Presenter: Two-PR Handoff

## Status

On 2026-10-04, the instructor confirmed that the HTML presenter POC worked in a
live test without PowerPoint. Students continued using ClassPoint's existing app.
The intended acceptance case is class startup, a visible slide, and an open
multiple-choice activity. This is an unofficial, experimental integration, not a
supported authentication contract or a production release.

The current code is preserved in `experiments/html-presenter/`. It is deliberately
not wired into existing `classpoint.py`, reports, or deckgen commands yet. This
draft is a development handoff; retain the working baseline while extracting it.

The preserved baseline includes a separate read-only audience window, local
slide/fragment/pause synchronization with audience reload recovery, and an
optional check that ClassPoint returns the configured join code before opening
an activity. Synthetic protocol and browser validation covers these additions.
The reusable client extraction and packaged deckgen command remain follow-up
work. Deckgen's shared window-lifecycle and deck-selection helper is available
through [deckgen PR #12](https://github.com/ait4x/deckgen/pull/12); the POC server
itself still requires explicit **End class** before stopping.

## Ownership and Dependency Direction

```text
deckgen presenter (slides, browser, local UI)
    -> classpoint.py live client (ClassPoint protocol and uploads)
        -> ClassPoint / Azure
```

The core client must not depend on deckgen, Reveal.js, Playwright, or a particular
HTML renderer. Deckgen can opt into the client; there must be no dependency cycle.
Do not move the current combined POC unchanged into the normal runtime of either
project, and do not maintain two copies of the live protocol implementation.

## PR 1: classpoint.py - Experimental Live Presenter Client

Suggested finished title: `Add an optional experimental live ClassPoint client`.

Direction:

1. Extract the connection, SignalR framing, invocation/completion handling,
   heartbeat, event parsing, uploads, class lifecycle, and multiple-choice
   lifecycle from `experiments/html-presenter/bridge.py` into a reusable client.
2. Separate class startup from question startup. A renderer supplies slide-image
   bytes plus slide/step metadata; the client never launches a browser. Keep
   response normalization and deduplication in the client, not in the HTML UI.
3. Introduce an explicit private configuration object for the instructor profile,
   region, class settings, and upload permission. Keep the captured account's
   limits. Repr, exceptions, state, and logs must not expose credentials or signed
   URLs. Make network dependencies optional and preserve current import/API
   compatibility for PPTX injection and report readers.
4. Retain capture import as an optional development helper, not a mandatory login
   flow. Do not require Wireshark/tshark for imports, existing APIs, or mock tests.
   Document the authentication limitations rather than inventing a login API.
5. Add browser-free mock transport/upload tests in the existing test conventions,
   plus protocol notes and a small non-renderer-specific example. Use synthetic
   fixtures, never classroom captures or recorded personal responses.

An illustrative API boundary, not a committed naming decision:

- `start_class(total_slide_count, audience_slide_viewer=True)`
- `send_slide(image_bytes, slide_index, step)`
- `start_multiple_choice(choices, select_multiple=False)`
- `close_submissions()`, `end_activity()`, `end_class()`
- A redacted state snapshot and an event subscription/callback for participants,
  answers, connection changes, and failures.

Acceptance:

- Existing `python tests.py` still passes and offline functionality has no new
  mandatory network/browser dependency.
- A fake server verifies SignalR handshake/framing, invocation errors, backend
  failure events, participant joins, answer deduplication, explicit cleanup, and
  the limited reconnect-to-end behavior already present in the POC.
- No connection opens on import, configuration load, or state reads; only an
  explicit start action makes remote ClassPoint requests.
- New slide objects do not overwrite captured slides. Failure cannot be reported
  as success, and a possibly active class remains explicitly endable.

## PR 2: ait4x/deckgen - Optional HTML Presenter Integration

Suggested finished title: `Present HTML decks with optional live ClassPoint activities`.

Direction:

1. Add a local presentation entry point, for example
   `deckgen present week01 --classpoint`, using the normal project/deck loader and
   the existing `Slide.cp` activity spec. The spelling is proposed, not available
   today. Depend on PR 1's live client through an optional presenter extra.
2. Move/adapt `deck.py`, the renderer-specific parts of `presenter.py`, and `web/`
   from the preserved POC into deckgen. Deckgen owns Reveal, browser capture,
   navigation/fragments, button wiring, local request guards, and UI rendering.
3. Polish the operator experience using the existing ait4x visual language:
   clear start/close/end states, a projected join code, useful response tallies,
   readable failure/retry states, keyboard access, and responsive layouts.
4. Keep published decks passive and credentials out of generated HTML. Only the
   explicit local presenter mode makes activity badges actionable; existing
   report links, reading view, static builds, PDFs, and PPTX export keep working.
5. Test the adapter against a fake live client and the real deckgen renderer.
   Finish with a user-driven live acceptance test using the instructor's own
   account; cloud CI must never start a real class automatically.

Acceptance:

- A trusted course deck can be presented without PowerPoint, with the first
  supported multiple-choice question selected and the existing activity metadata
  used without duplicating the source spec.
- Navigation and fragments synchronize raster snapshots; another question ends
  the previous activity and starts the new one in the same class.
- Students join and submit through the existing ClassPoint app, while the local
  operator sees redacted state and tallies.
- Loading the page does not start a class. The server binds to loopback, rejects
  foreign Host/Origin values, and requires a command token.
- Chromium/live dependencies do not become mandatory for ordinary deck builds.

## Current Code Map

| POC file | Future owner |
| --- | --- |
| `bridge.py` | classpoint.py live client; remove snapshot/UI coupling |
| `capture.py` | optional classpoint.py capture-import helper |
| `deck.py` | deckgen project loader/build adapter |
| `presenter.py` | deckgen local server and snapshotter; use the extracted client |
| `web/`, `DESIGN.md`, `PRODUCT.md` | deckgen presenter surface and design context |
| `demo_deck.py` | deckgen example/acceptance fixture |
| `validate.py` | split into browser-free protocol tests and deckgen adapter tests |

## Cloud Session Starting Point

Checkout this draft branch and read `experiments/html-presenter/README.md`. Run:

```bash
python tests.py
cd experiments/html-presenter
uv sync --locked
uv run playwright install chromium
uv run python validate.py
```

`validate.py` uses local mock services and synthetic identity/answers. It does not
need captures, TLS keys, credentials, or a real ClassPoint connection. Chromium may
need OS libraries on Linux (`playwright install --with-deps chromium`). The POC's
deckgen dependency is pinned to
`9990546c01865807e6aaac5aaa50977b4b6b916a` for a reproducible baseline.

Implementation order: extract/test PR 1 first, then wire PR 2 against its client
API. The deckgen draft can evolve in parallel against a fake client. Keep the POC
baseline runnable until the replacement passes the same acceptance case.

## Boundaries and Follow-Ups

- Do not commit `.pcap`/`.pcapng`, TLS key logs, account profiles, signed Azure
  URLs, real class codes, or student data. The uploaded handoff contains source,
  a dependency lock, documentation, and synthetic validation only.
- Capture-based setup proved the protocol but is not the intended onboarding UX.
  Decide a supported/explicit private configuration or authentication story
  separately; do not claim that absent handshake tokens mean absent backend
  authorization.
- Multiple choice is the first scope. Stars, other activity types, countdowns,
  quiz grading, report persistence, and automatic reconnect are follow-ups.
- Fresh headless screenshots do not capture live sketch/editor/video state from
  the presenting browser. Document this limitation; later add a deliberate
  in-browser snapshot/state-transfer path rather than silently misrepresent it.
- Always attempt explicit class cleanup; forced process termination cannot
  guarantee that a remote class ended.
