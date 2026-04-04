# x-cli

x-cli is a terminal-first client for X/Twitter. It uses the v2 API for tweets, users, bookmarks, and timelines, and the v1.1 upload endpoint for media attachments.

It shares the same credentials as [x-mcp](https://github.com/INFATOSHI/x-mcp). If you already have x-mcp set up, x-cli usually works with no extra auth setup.

If you're an LLM or automation agent working in this repo, read [LLMs.md](./LLMs.md) for the codebase map and command reference.

<!-- #region Capabilities -->
## What It Covers

- Post: `tweet post`, `tweet reply`, `tweet quote`, `tweet delete`
- Media: `tweet post --media`, `tweet reply --media`, `tweet quote --media`
- Read: `tweet get`, `tweet search`, `user timeline`, `me mentions`
- Users: `user get`, `user followers`, `user following`
- Engage: `like`, `retweet`
- Bookmarks: `me bookmarks`, `me bookmark`, `me unbookmark`
- Analytics: `tweet metrics`

Every command that takes a tweet target accepts either a raw tweet ID or a full X/Twitter status URL.
<!-- #endregion Capabilities -->

<!-- #region Install -->
## Install

x-cli requires Python 3.12+ and uses `uv` as the recommended workflow.

```bash
# install from source
git clone https://github.com/robert-hoffmann/x-cli.git
cd x-cli
uv tool install .

# or install from PyPI once published
uv tool install x-cli
```

For local development instead of a tool install:

```bash
uv sync
uv run --with-editable . python -m x_cli.cli --help
```
<!-- #endregion Install -->

<!-- #region Auth -->
## Auth

You need five credentials from the [X Developer Portal](https://developer.x.com/en/portal/dashboard):

1. Consumer Key
2. Consumer Secret
3. Bearer Token
4. Access Token
5. Access Token Secret

### Reuse x-mcp credentials

```bash
mkdir -p ~/.config/x-cli
ln -s /path/to/x-mcp/.env ~/.config/x-cli/.env
```

### Fresh setup

1. Create or select an app in the X Developer Portal.
2. In User authentication settings, enable `Read and write` permissions.
3. Generate or regenerate the Access Token and Access Token Secret after enabling write access.
4. Put all five values in `~/.config/x-cli/.env`.

```dotenv
X_API_KEY             = your_consumer_key
X_API_SECRET          = your_secret_key
X_BEARER_TOKEN        = your_bearer_token
X_ACCESS_TOKEN        = your_access_token
X_ACCESS_TOKEN_SECRET = your_access_token_secret
```

x-cli also checks the current directory for a `.env` file before falling back to environment variables.
<!-- #endregion Auth -->

<!-- #region QuickStart -->
## Quick Start

```bash
x-cli tweet post "Hello world"
x-cli tweet post --media ~/Pictures/photo.jpg "Ship log"
x-cli tweet reply 1890000000000000000 --media ./reply.png "good catch"
x-cli tweet quote https://x.com/user/status/1890000000000000000 --media ./clip.mp4 "Worth watching"
x-cli tweet search "has:media from:openai" --max 10
x-cli user timeline openai --max 5
x-cli me bookmarks --max 20
```
<!-- #endregion QuickStart -->

<!-- #region Posting -->
## Posting Commands

### Post a new tweet

```bash
x-cli tweet post "Hello world"
x-cli tweet post --poll "Yes,No" "Do you like polls?"
x-cli tweet post --media ./photo.jpg "Check this out"
```

### Reply to a tweet

```bash
x-cli tweet reply <id-or-url> "nice post"
x-cli tweet reply <id-or-url> --media ./reply.jpg "adding context"
```

### Quote a tweet

```bash
x-cli tweet quote <id-or-url> "this is important"
x-cli tweet quote <id-or-url> --media ./clip.mp4 "watch this part"
```

### Inspect or remove posts

```bash
x-cli tweet get <id-or-url>
x-cli tweet delete <id-or-url>
x-cli tweet metrics <id-or-url>
x-cli tweet search "machine learning" --max 20
```
<!-- #endregion Posting -->

<!-- #region Media -->
## Media Uploads

Media attachments are supported on three commands today:

- `x-cli tweet post --media PATH TEXT`
- `x-cli tweet reply ID_OR_URL --media PATH TEXT`
- `x-cli tweet quote ID_OR_URL --media PATH TEXT`

Current behavior:

- One attachment path per command. The CLI uploads one file and sends one media ID with the post request.
- `~` paths are expanded, so `~/Pictures/photo.jpg` works.
- Small images use a direct multipart upload.
- Videos, and any file larger than 1 MB, use the chunked upload flow automatically.
- Videos are always chunked, even when the file itself is small.
- Chunked uploads are sent in 4 MB segments.
- Progress messages such as `Uploading ...` and `Upload complete ...` go to stderr so stdout stays usable for JSON or piping.

Supported media categories in the current implementation:

- Images use the image upload path.
- GIF files use the GIF media category.
- MP4, MOV/QuickTime, and WebM files use the video upload path.

For video uploads, X may process the media asynchronously after the file transfer completes. x-cli polls until processing succeeds, fails, or times out, so a video post can take longer than an image post.

Examples:

```bash
x-cli tweet post --media ./photo.jpg "Release photo"
x-cli tweet reply <id-or-url> --media ~/Downloads/diagram.png "here is the diagram"
x-cli tweet quote <id-or-url> --media ./demo.mp4 "demo attached"
```
<!-- #endregion Media -->

<!-- #region Read -->
## Read, Users, and Self-Service Commands

### Tweets

```bash
x-cli tweet get <id-or-url>
x-cli tweet search "from:elonmusk" --max 20
x-cli tweet metrics <id-or-url>
```

### Users

```bash
x-cli user get elonmusk
x-cli user timeline elonmusk --max 10
x-cli user followers elonmusk --max 50
x-cli user following elonmusk --max 50
```

### Your account

```bash
x-cli me mentions --max 20
x-cli me bookmarks --max 20
x-cli me bookmark <id-or-url>
x-cli me unbookmark <id-or-url>
```

### Quick actions

```bash
x-cli like <id-or-url>
x-cli retweet <id-or-url>
```
<!-- #endregion Read -->

<!-- #region Output -->
## Output Modes

The default output is compact, human-readable rich formatting. Structured output stays available when you need to pipe results into other tools.

```bash
x-cli tweet get <id>                 # human-readable output
x-cli -j tweet get <id>              # JSON
x-cli -p user get elonmusk           # TSV for shell tools
x-cli -md tweet get <id>             # Markdown
x-cli -j tweet search "ai" | jq '.data[].text'
```

Add `-v` for timestamps, metrics, metadata, and fuller payload detail:

```bash
x-cli -v tweet get <id>
x-cli -v -md user get elonmusk
x-cli -v -j tweet get <id>
```
<!-- #endregion Output -->

<!-- #region Troubleshooting -->
## Troubleshooting

### 403 `oauth1-permissions` when posting

Your Access Token was likely generated before write access was enabled. Set app permissions to `Read and write`, then regenerate the Access Token and Access Token Secret.

### 401 Unauthorized

Re-check all five credentials in your `.env`. Extra whitespace and stale tokens are the usual causes.

### 429 Rate Limited

The error includes the reset timestamp returned by X. Wait until that time before retrying.

### `Missing env var` on startup

x-cli looks in `~/.config/x-cli/.env`, then the current directory's `.env`, then environment variables. At least one source must provide all five values.

### `Media file not found`

The `--media` path must exist on disk. The CLI validates this before any upload request is made.

### `Media processing failed` or `Media processing timed out`

This usually means X rejected the uploaded video during processing, or processing did not complete in time. Retry with a smaller or cleaner file, or switch to a format the current implementation handles directly: GIF, MP4, MOV, or WebM.
<!-- #endregion Troubleshooting -->

<!-- #region License -->
## License

MIT
<!-- #endregion License -->
