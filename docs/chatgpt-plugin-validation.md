# Riff ChatGPT plugin validation

Checked **October 19, 2026**, for plugin **0.2.0** and Riff **0.6.20** with
the recovered YuE2 LoRA work. The implementation preserves the complete original
studio and runs its native backend inside a platform package.

## Completed integration checks

| Check | Observed result |
| --- | --- |
| Original adapter and bundler | 32 Python tests passed, including real loopback HTTP/ranged audio, strict asset handling and source-preserving UI composition |
| Protocol and settings | 26 Python contract tests passed against the production adapter, RPC parser and SQLite stores |
| Routes and staged uploads | 24 Python tests passed, including an actual HTTP upload larger than 2 MiB, ordering, private staging, cancellation races and upstream failures |
| Download recovery | 5 Python tests passed for verified resume, corruption recovery, overlong partials and cancellation |
| App bridge | 26 JavaScript tests passed |
| Complete studio in app frame | 14 browser acceptance checkpoints passed in Chromium 145.0.7632.6, with no JavaScript errors |
| Bundled software | Standalone Python 3.14.7, TLS, SQLite, native LoRA engine, Elixir/ERTS score runtime, FFmpeg and FFprobe started with no language runtimes on the input PATH |
| Bundled media codecs | The package's own FFmpeg/FFprobe created and inspected a one-second H.264/AAC MP4 and an MP3 using Riff's required codec paths |
| Packaged MCP lifecycle | Actual package process discovered 18 tools and the 903,362-byte original studio resource; missing models produced an explicit error; draft and settings survived shutdown and a new process |
| Real native render through MCP | Pinned model verification, actual queue completion, bounded WAV transfer and persistent recording succeeded; details below |

The original studio resource contains 15 JavaScript modules, the original video
worker, both stylesheets, images and original markup. The bundler records 21
source asset hashes and refuses unexpected changes to its transport adapter
points. It does not replace the studio with a separate miniature interface.

## Browser evidence and its scope

The [browser receipt](evidence/riff-chatgpt-browser-2026-10-19.json) records
production `ManagedRiff`, the original `StudioServer`, real SQLite/LoRA/media
operations and production MCP stdio, mounted in an opaque iframe. Neural
inference, model admission, Hugging Face and the external review provider are
explicit doubles.

The acceptance flow exercises original score import/transposition/notation and
MIDI/ABC downloads, actual WAV playback and A/B, draft synchronization and
conflicts, ChatGPT writing/context, engine tuning, Hub previews, verified local
LoRA import across multiple chunks, review settings and recipe exports. Video
frames go through the bundled original worker and staged MCP uploads to real
FFmpeg; ffprobe confirms the resulting MP4 has video and audio.

Host downloads work in the fixture without `allow-downloads`. A stricter CSP
case exercises data-URL audio and the original canvas frame fallback. Desktop
and 390-pixel mobile screenshots were visually inspected. Frame requests are
local media URLs; HTTP API calls use the host's tool transport.

This proves those paths in a protocol host fixture. It does not establish a
production ChatGPT account connection, its actual CSP or its download policy.
The fixture's rendered music and composed tokens are not YuE2 inference evidence.

## Actual packaged YuE2 render

The [native receipt](evidence/riff-chatgpt-cpu-2026-10-19.json) comes from
`tests/smoke_runtime.py` launching the bundled Python and `server/launch.py` in a
fresh workspace. It sends current MCP requests rather than invoking the native
CLI directly. The test copies existing model files only after checking their
published size/SHA, then asks the real managed Setup service to verify them.

The model is `audio-cpp/Yue2-3B-GGUF` at
`9c31f1c64f73d36799693aa89295b410c76928c3`, with the Q4 main model, F16 VAE and
four sidecars totaling **2,933,414,997 bytes**. The engine SHA-256 is
`a73b1605147a55f108348832e994fb15d7be7f28b4c7762b17ca9b0fe77a3889`.
It contains the complete repository patch set, including LoRA support.

The recipe uses instrumental conditioning, planning off, seed 1234, two CPU
threads, two midpoint synthesis steps and a one-second target. No style adapter
is selected for this plugin integration smoke; the separate
[LoRA validation](lora-validation.md) records actual adapted native inference.

| Observation | Result |
| --- | --- |
| Queue transitions | `queued` → `running` → `done` |
| Wall time from submission through completion polling | 32.199 seconds |
| PCM format | Stereo, 48,000 Hz, signed 16-bit |
| Audio frames / duration | 47,936 / 0.998667 seconds |
| WAV bytes / app chunks | 191,788 bytes / 3 chunks |
| Absolute PCM peak | 0.2265625 of full scale |
| Full-scale samples | 0 |
| Performance and acoustic artifacts | Both saved |
| Reopened process | Recording, shared draft and settings persisted |
| WAV SHA-256 | `5ed86c834e82da6e29ef317fdd5360d574a67d106e972759b3c9789c0a409c0d` |

Audio bytes appeared only in app tool-result metadata. The client reconstructed
the WAV from that path, parsed its PCM, verified nonzero samples and checked the
saved recipe. The process shut down on stdin closure and reopened the same
workspace without a stale lock.

This is a short integration smoke, not a musical-quality comparison, a
full-song benchmark or a whole-song memory recommendation. Its receipt identifies
the exact tested package manifest. Later package assembly includes the same
native pipeline plus the separately verified host-CA handling change, and emits
its own component and process acceptance receipts.

## Reproduce and interpret delivery status

See [plugin usage and commands](../plugins/riff-chatgpt/README.md),
[runtime packaging](chatgpt-plugin-runtime.md) and
[protocol contracts](chatgpt-plugin-protocol.md). The GitHub workflow builds
Linux CPU and Apple Silicon Metal distributions with the real packaged MCP
startup check. A manual dispatch with `render=true` adds a pinned model download
and native render on both targets.

The following are separate acceptance boundaries:

- A successful source or browser fixture test does not imply an executable
  package exists.
- A successful Linux package does not establish a successful Mac package;
  inspect that platform's workflow result and receipt.
- A local stdio package needs a host that runs packaged processes and supports
  MCP Apps. An account upload does not provide that runtime to web/mobile.
- Production ChatGPT registration, opening the studio from its real entrypoint,
  and saving a download in that host remain host-specific checks. They are not
  claimed by these receipts.
