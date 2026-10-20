# Riff for ChatGPT

Riff's complete visual studio, original native music pipeline and persistent
recording library, packaged as a local MCP plugin. Conversation and the studio
share a revisioned draft. ChatGPT can write or revise it while the original
score editor, LoRA browser, player, comparison tools and exports remain available.

The plugin version is **0.2.0**. It includes Riff 0.6.20 with the subsequent
YuE2 LoRA implementation. The earlier 0.1.0 adapter artifact supplied the initial
draft and stdio bridge; this implementation adds the complete original UI,
managed native runtime, binary transfers, lifecycle, current MCP contracts and
platform package builders.

## Host and platform requirements

Use a host that **executes local stdio MCP servers and displays MCP Apps**.
The portable `mcp.json` launches Python from inside the platform package;
installing Python, Docker, Riff Desktop or a separate inference service is not
part of the user flow. First setup downloads the separately licensed music
weights into the plugin's persistent workspace.

The current package targets are Apple Silicon/macOS with Metal and x86-64/Linux
with CPU inference. Build and operating-system requirements are recorded in
[runtime packaging](../../docs/chatgpt-plugin-runtime.md).

**A local package is not a hosted ChatGPT web app.** Uploading its metadata to an
account does not give web or mobile clients a native process. A web deployment
needs an authenticated remote MCP service with a real native inference runtime;
no such service or endpoint is declared by this package. Production-host
installation and rendering must be verified separately from the automated host
fixture described below. See the [protocol and acceptance record](../../docs/chatgpt-plugin-protocol.md).

## Use Riff

1. Install the platform distribution through the target host's supported local
   plugin flow and open **Riff**. The host owns starting and stopping its process.
2. In Studio settings, choose **Download music models** if models are missing.
   Riff verifies every file against `sources.json`, reports progress, resumes
   interrupted downloads and keeps the models across plugin updates.
3. Compose in the original studio. Use **Save shared draft** to share the current
   recipe, or **Write with ChatGPT** to send a writing request with the draft.
   A new shared revision appears in a clean editor; unsaved local edits are kept
   and a conflict offers **Restore shared draft**.
4. Generate a take, inspect the real queue, listen, compare and refine it. Export
   WAV, MP4, artwork, recipe, ABC or MIDI through the host's download service.

The original optional OpenRouter writer and producer review remain available
through Review settings. ChatGPT writing uses the conversation and does not
require an OpenRouter key. The separate optional desktop MLX writer is not
included in this distribution; its original option displays unavailable.
Phrase suggestions remain available. Keys use the dedicated macOS Keychain
service or Linux Secret Service when present. Without a Linux keyring the UI
explicitly offers session-only storage; the key is cleared when the process exits.

Riff's application code is MIT licensed. The music model has its own
[CC BY-NC 4.0 terms](https://huggingface.co/m-a-p/YuE2-3B). Component licenses,
source receipts and bundled media-library sources accompany platform packages.

## Implemented surfaces

| Surface | Behavior |
| --- | --- |
| Original studio | Bundles every referenced original script, stylesheet, image and video worker into one MCP App resource; checks expected adapter points and records source hashes |
| Global and thread entrypoints | **Riff** opens globally; **Current song** opens beside a conversation; both support inline/fullscreen modes |
| Shared creative state | SQLite draft revisions, optimistic concurrency, editor polling, explicit attachment, background structured context, optional auto-save and persistent settings |
| Native pipeline | Private loopback backend with generator, score/performance/acoustic artifacts, resource admission, reviews, LoRAs and media exports |
| Local runtime | Bundled Python, YuE2 audio.cpp binary, Elixir/ERTS control runtime, FFmpeg/FFprobe, CA store and required shared libraries |
| Models and adapters | Pinned, resumable, verified model setup; original Hub browsing and compatibility checks; staged safetensors import; independent AR/NAR strengths and immutable take receipts |
| Playback and export | Bounded app-only media chunks, browser playback cache, A/B listening, staged frame uploads and host downloads; canvas/media fallbacks for stricter app sandboxes |
| Optional providers | Existing configured OpenRouter writing and audio review; app-only credential entry; explicit cancellation and shutdown cleanup |
| Protocol | Current per-request MCP discovery plus legacy initialization; strict input schemas, sanitized errors, finite routes and private cache declarations |

## Tools

The conversational tools are `riff_open_studio`, `riff_open_project`, `riff_read`,
`riff_generate`, `riff_edit`, `riff_get_draft`, `riff_save_draft`, `riff_setup`,
`riff_write`, `riff_review`, `riff_lora`, `riff_settings_read` and
`riff_settings_update`.

Five transport tools are available only to the app: `riff_ui_request`,
`riff_audio_chunk`, `riff_media_chunk`, `riff_upload_chunk` and
`riff_upload_cancel`. JSON responses retain the native status and body. Binary
responses keep their bytes in result metadata, outside conversation content.
Uploads accept selected bytes, never an arbitrary host path. Route and size
limits are enforced before the private backend is reached.

`riff_read` accepts the finite route list in `server/routes.py`. Read
`/api/capabilities` for the actual recipe contract. A successful generation call
returns a queued job; poll `/api/jobs/<id>` before reporting a completed track.
The bundled `riff-studio` skill describes the creative workflow and conflict
handling for the assistant.

## Develop and verify

The [validation record](../../docs/chatgpt-plugin-validation.md) contains the
current test counts, browser scope and an actual packaged YuE2 render receipt.

Run these commands from the repository root:

```sh
python3 plugins/riff-chatgpt/scripts/build_ui.py --riff-web riff/web
python3 -m unittest discover -s plugins/riff-chatgpt/tests -p 'test_*.py' -v
python3 -m unittest discover -s plugins/riff-chatgpt/packaging -p 'test_*.py' -v
node plugins/riff-chatgpt/tests/bridge.test.cjs
npm ci
npx playwright install chromium
node plugins/riff-chatgpt/tests/browser.test.cjs
```

The Python contract and gateway suites use explicit fixtures where needed.
The browser suite uses production `ManagedRiff`, the actual `StudioServer`,
SQLite, HTTP transport and MCP stdio inside an opaque sandbox. Its neural
inference, admission, Hub and external review provider are doubles; its media
export uses real FFmpeg. This verifies the integration without claiming the
fixture audio came from YuE2. The test runner writes its receipt and screenshots
under `test-results/chatgpt-plugin/`.

To inspect the real source adapter without a platform package:

```sh
python3 plugins/riff-chatgpt/server/main.py \
  --riff-root "$PWD/riff" \
  --workspace /absolute/path/to/a/separate/riff-plugin-workspace \
  --ui-file "$PWD/plugins/riff-chatgpt/dist/studio.html"
```

That development invocation uses the developer's Python and configured source
engine. A missing engine returns an explicit setup error. User distributions
instead launch `server/launch.py` with the bundled interpreter and validate
component integrity before opening the workspace.

After building a platform distribution, verify its actual process from a clean
environment:

```sh
python3 plugins/riff-chatgpt/tests/smoke_runtime.py \
  --package /absolute/path/to/riff-chatgpt \
  --workspace /absolute/path/to/new-acceptance-workspace \
  --output /absolute/path/to/new-acceptance-evidence \
  --no-render
```

Use `--models /absolute/path/to/pinned-model-files` or `--download-models` in place
of `--no-render` for a real one-second YuE2 render through MCP. The check verifies
model identities, native queue completion, chunked audio, stereo 48 kHz PCM16,
nonzero samples, saved recording and draft/settings persistence across a second
process. The receipt labels this short pipeline smoke and distinguishes it from
a production ChatGPT host session or a musical-quality evaluation.

## Source boundaries

- `server/`: MCP protocol, tool schemas, private HTTP bridge, staged uploads,
  persistent state, managed lifecycle and distribution launcher.
- `web/`: host messaging, media/exports, shared-draft and ChatGPT actions.
- `scripts/build_ui.py`: strict original-UI bundler with a provenance receipt.
- `packaging/`: pinned Python, native, control and media component builders.
- `tests/`: protocol, gateway, app bridge, browser and real-package acceptance.
- `../../scripts/package_chatgpt_plugin.py`: platform assembly, dependency
  relocation, integrity manifest and reproducible archive layout.
- `../../.github/workflows/chatgpt-plugin.yml`: validation and platform artifacts.

Plugin installation replaces package files. Recordings, metadata, downloads,
drafts and settings live in a separate workspace. A process lock prevents two
native servers from writing that workspace at once. Disconnecting the host
cancels owned work and closes private services; closing only an app view releases
its media and polling while keeping the shared studio process available.
