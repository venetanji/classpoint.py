# Presenter Extension

This is a functional extension of deckgen's existing ait4x presentation surface,
not a new slide design. Inherit its self-hosted Inter and JetBrains Mono, white and
paper surfaces, ink typography, deep-teal interaction state, and restrained geometry.

The Reveal.js slide is the dominant surface. A compact adjacent operator column
contains the join code, explicit class controls, and response tallies. Navigation
stays with Reveal. Full screen projects the existing deck, with a small join-code
overlay. Short-answer responses open as an explicit overlay on the slide, with a
white title/count header and persistent status/action footer around a scrollable
paper answer list. Ink answer text and deep-teal monospaced numbering inherit the
existing type and palette. Closing submissions leaves the answers visible.

The operator's close and one-star award controls remain in the footer while the
list scrolls, including inside operator full screen. On narrow screens, the panel
fills the viewport with an inset margin. A separate read-only audience screen
mirrors the slide, answer visibility, and relative scroll position; it retains the
join code and textual submission/award status while omitting hide, close, and award
controls. Diagnostics remain in the operator shell.

Tokens: ink #000B1C, paper #F4F4F2, white #FFFFFF, muted #5C6470,
line #E1E1DE, teal #64C2C3, deep teal #00544C, orange #ED6D24.
Keyboard access, non-color status text, error recovery, disabled states, narrow
screen stacking, and reduced-motion support are required for the operator shell.
