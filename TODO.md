# TODO

## Media upload follow-up items

These are findings from reviewing the media-upload fork and should be addressed during refactoring/hardening.

### 1. Validate incompatible post options

The current implementation appears to allow combinations that X likely rejects.

Items to enforce client-side:

- reject `--media` + `--poll`
- reject media attachment combined with quote-post payloads if X still treats `media` and `quote_tweet_id` as mutually exclusive
- review any other mutually exclusive payload combinations in the X create-post docs and enforce them before making requests

Why this matters:

- the current code can build payloads that are structurally invalid for X
- failing early in the CLI gives much better UX than surfacing raw API errors

### 2. Improve error reporting for upload/post failures

Add clearer errors for:

- upload INIT failure
- APPEND failure on a specific segment index
- FINALIZE failure
- STATUS polling failure / timeout
- post creation failure after successful upload

Why this matters:

- media upload is multi-step
- users need to know where the failure happened

### 3. Add live integration validation

Current media tests are mocked and pass, but we still need real-world validation.

Suggested real tests:

- upload and post a small image
- upload and post a short MP4
- verify processing succeeds and attached media appears on the created post

Why this matters:

- mocked tests prove code flow, not actual X compatibility
- auth/tier/API behavior still needs real confirmation

### 4. Verify auth expectations for upload endpoints

Current implementation uses the legacy upload endpoint:

- `https://upload.twitter.com/1.1/media/upload.json`

And signs requests with OAuth 1.0a.

Follow-up:

- verify this is reliable with the target X developer tier/account in real usage
- confirm whether any newer OAuth 2.0 media-upload path should also be supported

Why this matters:

- docs are evolving
- real auth compatibility matters more than mocked behavior

### 5. Document media support more clearly

README / docs should explain:

- supported file types
- when simple upload vs chunked upload is used
- that video uses INIT/APPEND/FINALIZE/STATUS
- current limitations (single media, unsupported combinations, etc.)
- known X API restrictions that affect posting/replies/interactions

### 6. Review quote-post + media behavior

Current CLI supports:

- `tweet quote --media ...`

Need to verify against current X create-post rules whether this is valid.

If invalid:

- block it in the CLI
- document the reason

### 7. Review single-media limitation

Current helper returns a single uploaded media ID.

That is fine for the current MP4 workflow, but future design should decide whether to support:

- one attachment only
- or multiple attachments/images

### 8. Optional: add an integration-test helper script

Consider a manual/dev script that:

- uploads a file
- polls until processed
- creates a post with the returned media ID
- prints structured success/failure details

This would make debugging real API issues much easier during refactoring.
