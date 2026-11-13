# Gamepad And Answer Overlay Evidence

Observed 2026-11-13. This extends the accepted classpoint.py HTML presenter at
`fd51535`, retaining the laptop's existing fixed-join-code changes. It reuses
deckgen's Reveal renderer and the current local audience BroadcastChannel.
There is no course-source or renderer replacement.

## Star Command

The instructor's private historical capture contains, in order:

- `PresenterCloseSubmission` at frame 4991, completion at 4994.
- `GivePointsToParticipants` at frame 5183, two positional arguments:
  `{email}` and `[{participantId, points: 1}]`.
- `ParticipantsGotPoints` plus matching invocation completion at frame 5191.
- `PresenterEndActivity` at frame 5275.

The recorded recipient set matches the activity's unique respondents. Identities,
payloads and capture/TLS files remain private and are not reproduced here.

The public official presenter observed this session loads `main.3ada61cc.js`;
SHA256 `f2e40889194d2174d507f6916fcf3fbe4b7a9a55e262fe7a54ed20cc684623f2`.
Focused inspection confirms the same participant command at character offset
2975843, additive local points at 2970844 and server point replacement at 2966215.
This is outgoing client evidence, not fresh backend acceptance. The retained REA
analysis has partial semantic-graph coverage following a heap limit; exact command
findings come from focused source inspection and the historical capture.

No request/activity/idempotency key appears in the award command. The bridge
closes first, deduplicates internal respondent IDs, and reserves the award before
sending. Confirmed awards cannot be repeated for the activity. Ambiguous outcomes
remain uncertain and are never automatically retried. Participant IDs and names
are not exposed in normalized answer rows.

`GivePointsToResponses` is a separate official-client operation for response/report
stars. It is absent from this capture and is not implemented by this change.

## Reused Pins And Checks

Classpoint upstream observed HEAD: `fd51535`; accepted laptop base: `fd51535`
plus pre-existing fixed-code edits. Deckgen upstream observed HEAD: `f2bdaad`;
the POC renderer retains tested pin `9990546c01865807e6aaac5aaa50977b4b6b916a`.
The existing launcher already loads the separately tested deckgen lifecycle helper.
No dependency upgrades were needed for these features.

Loopback validation covers the actual SignalR client, ordered close/award,
one star per unique respondent, empty responses, repeated calls and uncertain
dispatches, plus browser/controller edges, 35 text responses, preserved scrolling,
audience synchronization, desktop/mobile/fullscreen and existing session behavior.
The user's physical PS5 D-pad navigation succeeded on the laptop. Circle/square
mapping is explicitly requested by the user and covered by controller tests.

No real class or star award was made during implementation. A real short-answer
submission and participant-star receipt remain the live acceptance check.
