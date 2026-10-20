# Riff ChatGPT plugin: native runtime and platform packages

The `plugins/riff-chatgpt` implementation embeds the existing Riff studio in an
MCP Apps resource and gives it a private, managed Riff backend. Platform packages
carry the software needed to run that backend: the native YuE2 engine, Python,
the score scheduler, and audio/video tools. Installing Python, Elixir, Rust,
FFmpeg, or a compiler is not part of the end-user flow.

The plugin version is **0.2.0**. The underlying application version remains
**Riff 0.6.20**, with the complete pinned native patch set, including the LoRA
implementation. The release builder verifies that exact native source and its
advertised capabilities. It refuses a stale desktop engine or a build with
host-native CPU specialization enabled.

## Host and platform requirements

The host must support local stdio MCP servers, executable plugin packages,
`${PLUGIN_ROOT}` command expansion, and MCP Apps UI resources. Ordinary browser
JavaScript cannot execute the native engine. The public ChatGPT browser by
itself is therefore not a runtime for this local package. A host's plugin
registration and sandbox permissions remain separate from the package's own
acceptance checks; successful local tests do not prove host registration.

| Package | Engine | OS and processor baseline | Validation boundary |
| --- | --- | --- | --- |
| `linux-x86_64` | CPU | Ubuntu 24.04 build baseline, glibc 2.39 or newer; the package records and checks AVX2/FMA/BMI2/F16C features actually enabled in its engine | The local package has passed bundled-component startup with an empty language-runtime PATH. Full MCP/native smoke evidence is produced separately. |
| `macos-arm64` | Metal | Apple Silicon, macOS 15 or newer | The PR workflow builds and tests this package on its own ARM64 runner. A configured workflow is not evidence that its build has passed. |

The current packages do not contain a CUDA engine or an Intel Mac engine. The
macOS build uses ad hoc code signatures and checks its complete dylib closure.
It is not a notarized desktop application. A host that requires a different
package transport or signing policy needs its corresponding registration step.

The native engine's required RAM depends on duration, conditioning, scheduling,
and model residency. A one-second acceptance render verifies integration; it is
not a real-time performance claim or a memory recommendation for whole songs.

## What the package contains

| Location | Purpose |
| --- | --- |
| `plugin.json`, `mcp.json` | Portable plugin metadata and the real local stdio launch command |
| `server/launch.py` | Component integrity, platform checks, a private environment, and MCP startup |
| `server/main.py`, `adapter.py`, `runtime.py` | MCP protocol, bounded application/media routes, shared draft storage, and backend lifecycle |
| `dist/studio.html` | Self-contained original studio with the host bridge |
| `riff/` | Curated application source, unmodified studio assets, model/native manifests, and patches |
| `runtime/python/` | Checksum-pinned standalone CPython with TLS and SQLite; unused Tk/IDLE modules are omitted |
| `runtime/engine/audiocpp_cli` | The compiled native engine with the complete LoRA patch set |
| `runtime/control/` | Relocatable ERTS/Elixir release, Riff score scheduler, and native file-lock helper |
| `runtime/media/` | FFmpeg and ffprobe built from the repository's pinned media sources |
| `runtime/lib/` | Necessary non-system shared libraries, closed and checked by the packager |
| `runtime/certificates.pem` | The standalone runtime's public CA trust store |
| `runtime/runtime.json`, `bundle-manifest.json` | Platform/build identity and every packaged file's size, SHA-256, and executable bit |
| `notices/` | Component receipts, license notices, and complete media source archives |

The macOS control build reuses the repository's private OpenSSL/OTP build. It
verifies that receipt and replaces the matching crypto NIFs before packaging;
copying a new dylib beside a statically linked old NIF would not accomplish that.
Linux carries the non-libc dependencies reported for its actual binaries. Its
glibc and basic OS shell utilities are the documented operating-system ABI.
The launcher preserves host-supplied `SSL_CERT_FILE`/`SSL_CERT_DIR` settings and
uses the standard Linux OS trust directory alongside its bundled public roots.
This supports an already trusted managed HTTPS proxy without disabling
certificate verification or copying private host certificates into a release.

The source tree and its UI hash are recorded from the build's actual files.
`base_commit` identifies the checked-out Git commit, and
`source_has_local_changes` discloses an uncommitted build. These fields do not
pretend that a local build is identical to the public main branch. The final
bundle manifest supplies exact hashes even when there are local changes.

The package's entrypoint verifies all recorded component bytes before starting
the studio. Distribution archives contain one `riff-chatgpt/` directory and
regular files; component symlinks are flattened. The package builder writes
`SHA256SUMS`, component startup `acceptance.json`, and deterministic archive
metadata. This is a reproducible build procedure with explicit inputs, not a
claim that different compiler/OS installations produce identical native bytes.

## Workspace and lifecycle

The package is replaceable; music and preferences live elsewhere. Defaults are:

- macOS: `~/Library/Application Support/Riff ChatGPT`
- Linux: `${XDG_DATA_HOME:-~/.local/share}/riff-chatgpt`

`RIFF_PLUGIN_WORKSPACE` or the launcher's `--workspace` option can select another
directory. It must be outside the package. The managed process sets `RIFF_HOME`
to this workspace and removes the standalone install/update environment.

One MCP process owns a workspace lock. Multiple studio resources in that
process share its backend and SQLite state. Closing an individual UI resource
does not stop an active render. A competing MCP process receives a clear
already-open error instead of starting a second scheduler on the same files.
Closing the owning MCP process cancels its downloads, review/writing work and
native generator before shutting down the private HTTP service and releasing
the lock. Persisted jobs and music remain available on the next launch.

The backend binds only to an ephemeral loopback port. Its existing HTTP origin
and request checks remain intact. The UI communicates through MCP tools rather
than contacting that port directly. Protocol messages alone go to stdout;
runtime diagnostics go to stderr and the workspace's existing logs.

Every launch restores the engine executable, backend, model root and model
filenames from the package manifest before importing the application store or
probing engine readiness. User tuning such as thread count and warm residency
can persist. The app gateway rejects attempts to substitute executable or model
paths. The private maintenance service handles model setup and never runs the
standalone compiler/updater. Restart requests explain that the host manages
plugin replacement and leave the live MCP backend intact.

## First model setup and credentials

Music models are downloaded after installation. The pinned manifest currently
selects `audio-cpp/Yue2-3B-GGUF` revision
`9c31f1c64f73d36799693aa89295b410c76928c3`: the Q4 model, VAE and four sidecars,
about 2.93 GB together. They are stored under the workspace's `models/<revision>`
directory. The studio offers **Download music models**, shows byte progress and
the [YuE2 model card](https://huggingface.co/m-a-p/YuE2-3B), and supports
cancellation and resuming partial files.

Each completed file must match both its exact byte count and SHA-256 before it
is activated. An interrupted or invalid transfer cannot make the engine appear
ready. Verified cached files are reused. Setup never copies models or settings
out of an existing standalone Riff installation automatically. Model and
component licenses remain distinct from the MIT application license; see
[NOTICE.md](../NOTICE.md) and the linked model card.

The plugin can write with ChatGPT, Riff's phrase workflow, or an OpenRouter
provider configured in the studio. It does not bundle the optional MLX writer.
On macOS, provider keys use a separate `Riff ChatGPT OpenRouter` Keychain
service. On Linux, when `secret-tool` is unavailable, the studio explicitly
labels the shared writing/review credential store as **Session only — cleared
when Riff closes**. This in-memory fallback does not silently write plaintext
keys or require the user to install a keyring utility. App settings mutations
and provider details use app-only results, keeping keys out of normal model
tool output.

## Building a distribution

Build each target on that target's OS and architecture. These are release-host
dependencies, not user prerequisites: C/C++ and make, Git, pkg-config, Python
3.12 or newer, Elixir 1.18.4, OTP 28.0.2, Rust 1.89, and the target's OS SDK.
Linux also uses zlib development headers; NASM enables media assembly. The
provided workflow installs or checks them automatically. Source archives and
CMake/Python binaries are pinned in
[`desktop/components.json`](../riff/desktop/components.json) and
[`packaging/components.json`](../plugins/riff-chatgpt/packaging/components.json).

For a Linux CPU package, from the repository root:

```bash
build_root=/absolute/path/to/fresh/riff-plugin-build
python3 -B plugins/riff-chatgpt/packaging/build_toolchain.py \
  --platform linux-x86_64 --output "$build_root/tools"
export PATH="$build_root/tools/venv/bin:$PATH"
python3 -B plugins/riff-chatgpt/packaging/build_python.py \
  --platform linux-x86_64 --output "$build_root/python"
python3 -B plugins/riff-chatgpt/packaging/build_native.py \
  --backend cpu --output "$build_root/native" --jobs 2
python3 -B plugins/riff-chatgpt/packaging/build_media.py \
  --output "$build_root/media" --jobs 2
python3 -B plugins/riff-chatgpt/packaging/build_control.py \
  --output "$build_root/control"
```

The native builder prints its exact `RIFF_NATIVE_BUILD` directory and writes it
to GitHub's environment file when running in Actions. Read that same directory
from `native/build.json` for a local build. Then assemble:

```bash
native_build=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["build_directory"])' "$build_root/native/build.json")
python3 -B scripts/package_chatgpt_plugin.py \
  --platform linux-x86_64 --engine-build "$native_build" \
  --python-build "$build_root/python" --media-build "$build_root/media" \
  --control-build "$build_root/control" --output "$build_root/package"
```

For macOS ARM64, use `--platform macos-arm64` and `--backend metal`. Before the
control build, run the existing private crypto builder:

```bash
elixir desktop/build_openssl.exs --output "$build_root/openssl" --jobs 2
python3 -B plugins/riff-chatgpt/packaging/build_control.py \
  --output "$build_root/control" --crypto-build "$build_root/openssl"
```

The packager verifies native source/patch identity and LoRA capabilities,
closes platform library dependencies, checks the complete file manifest, and
launches the carried interpreter with `PATH=/nonexistent`. The launcher supplies
only its bundled tools and basic OS utility directories. Its `--check` exercises
Python SQLite/TLS, PNG-to-H.264/AAC MP4 encoding with the application's actual
video settings, PCM-to-MP3 review preparation, ffprobe inspection, and the actual
score-runtime protocol.

## Acceptance and CI

The [ChatGPT plugin workflow](../.github/workflows/chatgpt-plugin.yml) is manually dispatched on owned self-hosted Linux and Apple Silicon targets. It checks out the pinned Riff submodule before building. It builds
Linux CPU and macOS ARM64 Metal packages independently, uploads successful
archives/checksums/evidence, and retains logs on failure. It does not publish a
release or install anything into an end user's environment.

After assembly, exercise the actual packaged MCP server:

```bash
python3 -B plugins/riff-chatgpt/tests/smoke_runtime.py \
  --package "$build_root/package/riff-chatgpt" \
  --workspace "$build_root/smoke-workspace" \
  --output "$build_root/smoke" --no-render
```

The smoke check launches the packaged interpreter/entrypoint, negotiates MCP,
discovers tools and the original studio resource, verifies missing-model
honesty, persists a draft and settings, and reopens the workspace. Replace
`--no-render` with `--download-models` to verify pinned setup and a real short
native render through MCP, including polling, chunked WAV transfer and PCM
checks. For a local acceptance machine with already downloaded pinned files,
`--models /path/to/pinned-models` seeds only the isolated test workspace before
the same setup verification. Dispatching CI with `render=true` requests the
real model download/render on both targets.

Protocol contract tests and the browser host harness complement this check.
Browser fixtures test the production UI, private backend and MCP bridge while
substituting expensive neural operations; they do not prove native inference.
Actual acceptance JSON and render evidence, successful per-platform CI jobs,
and host registration are separate results and should be reported separately.
