# ClassPoint official public client protocol evidence

Inspected 2026-10-21 UTC, unauthenticated static JavaScript only. No live class, hub connection, student upload, credentials, or private response retrieval was performed. These are outgoing official client implementation facts, not a backend API contract or verified server acceptance.

## Reproducible sources

- https://presenter.classpoint.app/ currently references https://presenter.classpoint.app/static/js/main.0ddf9c96.js
  SHA256: `737d41f541db4155eee410ac41346630bcb1e8ff8b078d1d765395c5901af084`
- https://www.classpoint.app/ currently references https://www.classpoint.app/static/js/main.3e361846.js
  SHA256: `6bf4de22e26bde4296dd4332923176b587df5948008ac26bdc6cda088862f438`
- Bare https://classpoint.app/ is only a redirect wrapper; use www bundle.

Positions below are zero-based Python string character offsets in UTF-8 decoded minified source. Search symbols/strings too; deployed assets may change. Do not commit whole vendor bundles: unnecessary copyrighted source, and bundles may contain embedded storage access material that must not be copied into repository/tests/docs.

## Presenter start command

Presenter constants around 2287049 specify `Short Answer`, `Image Upload` (with spaces/case).
`qw` immediately before offset2884590 maps these types to `sa`/`iu` prefixes; `Kw` generates UTC yyyyMMddHHmmssSSS +4 uppercase letters.
`Ww=async e=>` at2884590 builds:
- activityId
- activityType
- activitySlideUrl
- activityStartTime: Date.now()
- activityEndTime: set only for countdown>0 by Date.setSeconds(now.seconds+countdown), otherwise forwards input (undefined omitted by JSON serialization)
- countdown
For Short Answer: numOfSubmissionsAllowed, isNamesHidden.
For Image Upload: numOfSubmissionsAllowed, isNamesHidden, isCaptionRequired.
Only MC case sets isQuizMode and MC-specific fields.

At2900659 startActivity calls Ww then adds `{email:user.email}` and invokes `PresenterStartActivity` with that object. Thus this is direct presenter outgoing command evidence, not solely student received schema.

Multiplicity caveat: numeric numOfSubmissionsAllowed otherwise passes through. Legacy isMultipleSubmissionsAllowed mapping is surprising but explicit: true -> 3 if ID starts sa, otherwise1; false ->1. No evidence of0/-1 unlimited. Student add-new UI compares submission count<allowed and text says up to allowed. Host-native defaults are not visible here. Recommend explicit1 as initial supported policy rather than inventing conversion for image boolean multiple=true.

Hide names passes isNamesHidden through; presenter renderers default missing to false. This affects presentation, not removing identity fields from wire.

## Student image submission

Student xI image modal (~2768000 onward) sets responseId `resp-`+W(). At2769973 submission:
- Rejects blank trimmed caption if isCaptionRequired.
- Search/list selection uses its selected URL directly.
- Device image or crop uploads via Tm.uploadToStorage(blob,responseId+'.'+extension,'user').
- Creates responseData with JSON.stringify([imageURL,caption]).
- Dispatches {activityId,activityType,responseId,responseData}.
Caption input maxLength50 near2749801. This is UI behavior, not proof server enforces length.

Common submitResponse function at2196015 adds presenterEmail, participantId,participantName,participantAvatar and invokes `SubmitResponse`. On failed invoke, it calls HTTP submit-response fallback using same object. No such call was made in research.

Student storage helper Cm at2190402 constructs a URL on cpfile11.blob.core.windows.net/user/{filename}, sets content type from blob, and returns unsigned HTTPS URL on successful upload. Never use/republish embedded access material. Search-selected images may be external URLs, so Azure-only acceptance is a deliberate limitation, not complete official capability. Prefer safe HTTPS URL validation, no server-side arbitrary fetching, referrerpolicy=no-referrer; make other-host display opt-in if privacy requires it.

## Short Answer submission

At2541193, student creates same four response fields, but responseData is lT(u), a sanitized HTML STRING, not JSON array. lT is a DOMPurify-like sanitize wrapper with allowed formatting tags. Presenter should either implement a vetted sanitizer or render plain text after HTML-to-text conversion; never insert student HTML unescaped. Escaped HTML displayed literally is safe but not polished. Document any lost formatting.

## Lifecycle, response identity and deduplication

Presenter ParticipantSubmittedResponse handler at2964744 accepts object or JSON string. It appends to a 50ms local cache/current list, then dispatches RESPONSES_RECEIVED. SyncActivityResponsesOnRejoin receives a whole list and dispatches SYNC_RESPONSES_ON_REJOIN. Reducer at2847565 replaces its response list for both. No explicit deduplication visible in this path; backend duplicate guarantees remain unknown. Bridge deduplication by responseId scoped to activityId is prudent, not an observed backend guarantee.

PresenterCloseSubmission command sends {email} for non-MC; only quiz MC adds scoring. PresenterEndActivity sends {email}. End resets local activity; Close preserves results and switches to view mode. New start closes/ends prior activity through _C. No IU/SA-specific close command found.

Student binds ActivityStarted (object or JSON string), ActivityClosed, ActivityEnded. Start resets activity state, Close changes status to submitted, End clears state. Rejoin model contains yourSubmittedResponses and activityStatus. DeletedResponse uses responseId and removes matching response; responseData may be retained to edit/retry.

## What remains unverified

A subsequent, separate [live acceptance test on 2026-10-21](live-image-upload-handoff.md#live-acceptance-21-october-2026) verified backend acceptance, actual student browser image upload, a decoded operator gallery thumbnail and one-response short answer in one instructor setup. That test does not change the public-source-only provenance of this research.

Still unverified: other accounts/versions; whether missing optional fields have server defaults; current response transport limits; server-enforced multiplicity/caption limits; three real short-answer submissions; retry/update, reconnect and late-submission behavior in a live class. Native-host options UI defaults are not recoverable from these bundles. The integration remains experimental rather than a supported backend API contract.
