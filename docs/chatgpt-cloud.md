# Riff in ChatGPT Chat

The cloud package runs Riff in each user's ChatGPT Chat cloud execution environment. It has
no external MCP endpoint and never uses the developer's homelab or the user's
local computer as its production backend. The homelab remains a build/CI host.
Private installation and real native generation have passed in ChatGPT Chat.
The original 0.3.0 package required writable-path, socket and setup recoveries;
0.3.1 replaces its socket transports; 0.3.2 adds file-lock worker ownership and
the reusable recording player. Actual Chat verified that the host reaps detached
workers between execution calls: 0.3.2 restarts safely and preserves drafts, while
setup/render/polling must share a retained execution session. A connected full
studio has not passed Chat acceptance.

Version 0.3.3 is privately installed on the existing Riff plugin identity. Its
installed native export command and the actual Chat inline player display passed
acceptance. The renderer and audio controls also passed sandboxed Chromium tests;
direct playback inside Chat's own nested iframe now passes trusted-click, audio advancement, seeking, loop-wrap and changing original-canvas checks.

## OpenAI documentation contract

The implementation follows these documented distinctions:

- [Plugin architecture](https://developers.openai.com/plugins/concepts/plugins)
  supports skills containing instructions and supporting scripts, references,
  templates or assets. A skills-only plugin can use tools already available to
  the model; an MCP server is a separate integration.
- [Build skills](https://developers.openai.com/plugins/build/skills) permits
  deterministic helper scripts under `scripts/`. This is the basis for the
  cloud command adapter, rather than a bundled stdio MCP connection.
- [Package your plugin](https://developers.openai.com/plugins/build/plugins)
  defines root `plugin.json`, `skills/`, relative asset paths and
  `extensions.com.openai`. Installing a plugin on the web does not deploy
  lifecycle-hook scripts.
- [Desktop-only plugins](https://developers.openai.com/plugins/deploy/desktop-only)
  identifies local stdio MCP servers as a desktop execution path. A packaged
  local server must not be described as an automatically hosted cloud MCP service.
- [Add UI](https://developers.openai.com/plugins/build/chatgpt-ui) requires an
  MCP server to associate a tool with a UI resource, and an MCP Apps host bridge
  for component interaction. Including studio source in a skill archive does
  not register that studio as a ChatGPT UI component.
- [Connect and test](https://developers.openai.com/plugins/deploy/connect-chatgpt)
  requires testing the installed package in a new conversation with
  representative requests and verifying bundled-resource resolution.

These pages do not guarantee native Riff execution, a fixed cloud CPU/memory
allocation, background-worker persistence, or a route from a skills-only
command worker to an MCP App. Those remain explicit compatibility questions;
host probes are implementation evidence, not substitutes for platform documentation.

The documented [shared archive checks](https://developers.openai.com/plugins/deploy/submission-errors#archive-errors)
limit the ZIP to 100 MB compressed, 512 MiB extracted, 100 MiB per member and
5,000 entries. The native runtime is a compressed skill asset; validation must
check both the outer plugin archive and the extracted runtime independently.

The cloud distribution is a portable plugin containing a skill, a small Python
launcher and a checksum-verified native runtime archive. The candidate launcher currently requires Python 3.12+; Chat must supply it
or the launcher must be adapted after checking its actual runtime. The package carries the pinned Riff source, CPU YuE2 engine,
Elixir/ERTS score/control runtime, media executables, libraries, studio source
and component notices. The separately licensed music models download from the
pinned public Hugging Face revision into the user's cloud workspace.

A worker inside that cloud computer uses a private SQLite mailbox. Native
studio request handlers run in that same process without an HTTP listener.
Successive
cloud command calls use the existing adapter and share the same native jobs,
drafts, LoRA library and recordings. No network/Unix listener or developer credentials
are needed. The original stdio/MCP App distribution remains separate.
Worker liveness is established by a kernel-held file lock rather than PID lookup,
which is unreliable across execution namespaces and succeeds for zombies or
reused PIDs. Worker loss reports the request identity promptly. On restart,
unfinished mailbox requests are failed for inspection rather than replayed.

Build a complete Linux CPU platform package with the existing builder, then:

```sh
python3 scripts/package_cloud_plugin.py \
  --runtime-package /absolute/platform/package/riff-chatgpt \
  --output /absolute/output/riff-chatgpt-cloud.zip
```

Install the resulting archive through ChatGPT's private plugin importer and
start a fresh Chat conversation. The skill launches its bundled runtime with:

```sh
python3 /path/to/skill/scripts/riff.py start
python3 /path/to/skill/scripts/riff.py call riff_read --arguments '{"path":"/api/state"}'
```

`--arguments @/path/to/file.json` supports complete recipes without shell
interpolation. App-only binary metadata is omitted from stdout; use
`--output-file` to preserve a full transport result privately. Export original
recordings through the host's Library instead of embedding audio bytes in chat.

Cloud workspace persistence is bounded by the cloud computer's lifetime. Models
may need to download again after reset. Publish requested recordings and recipe
receipts to the user's Library. A queued job is not completed audio.

## Recording panel

The cloud skill now includes `scripts/player.py`. It reads a real recording and
its native visualization through the existing adapter, transfers WAV bytes using
the declared bounded audio chunks, and exports self-contained HTML. It carries
the pinned upstream `artwork.js` and `motionAt` unchanged,
and a receipt with audio/source hashes and measured WAV metadata. No audio bytes
enter model context. The skill asks Chat to display this exact file through the
host's HTML/Visualize capability and publish audio to Library.

```sh
python3 /path/to/skill/scripts/player.py --track-id RECORDING_ID \
  --output /writable/path/riff-player.html
```

This recording player supports playback, seek, loop and download. It does not
provide a live native command connection for library, LoRA or score controls.
Those remain available conversationally through the adapter. Full studio
navigation and editing require the registered MCP UI transport described above;
bundling the studio alone does not establish it.

The installed Visualize helper requires an **HTML fragment**, and documents and
enforces a **1,000,000-byte fragment limit**. The export omits document wrappers
so it can use the host's source-path registration/display workflow unchanged.
Version 0.3.3 preserves the exact embedded WAV when it fits;
larger recordings use a clearly labeled 128 kbit/s MP3 preview created with the
bundled FFmpeg. Preview duration follows from the remaining fragment capacity,
including actual encoder overhead. All original motion frames are gzip-compressed
without loss. The complete original WAV stays in Library. The panel can open
that downloaded WAV through a local file picker, verify its original SHA-256,
and play/visualize the complete recording without uploading it or making HTTP
requests. A preview is never described as a full original WAV.

The Visualize instructions do not document a large-media upload bridge; their
preview policy does not permit arbitrary HTTPS media or Library download URLs.
The full MCP studio already has chunked exact-audio transfer, but that transport
still needs to be connected to Chat. This is tracked in [issue #2](https://github.com/Flip-Engineering/Riff-ChatGPT-Plugin/issues/2).

On October 20, the actual Chat acceptance conversation generated recording
`cfeb4193acd84a87b12ce9800bd204f4`: 47,936 stereo PCM16 frames at 48 kHz,
0.998666667 seconds, native exit 0, seed 1234, two midpoint acoustic steps.
The original WAV SHA-256 is
`314375cb23ea17bd6c2762e637b649e42f878d6b3184bf6226def9acb8080523`.
Chat displayed an HTML recording player using the original Riff renderer and
actual motion data. The browser's conversation iframe was observed, but playback
inside that host iframe was not independently inspected. The reusable packaged
player passed a separate Chromium test of playback time, seeking, looping,
changing artwork, media identity and title-injection handling without HTTP.

The native studio returned HTTP 200 inside the Chat execution environment;
Chat's separate cloud browser received `ERR_CONNECTION_REFUSED` at its loopback
address. A direct studio response also forbids framing. An external UI transport
would have to connect the host panel to each user's cloud worker; the developer's
homelab is not a runtime backend.

## Installed 0.3.3 acceptance, October 20

The final cloud archive was packaged from `d14782e`, with SHA-256
`a50b791846ab728e1be3a171fda3e81e7a588c2a6254c9c80d96e36558188063`
and size 56,998,097 bytes. Browser-side byte count and SHA-256 matched before
upload. Chat confirmed the existing plugin had updated to 0.3.3.

A fresh Chat then reused native recording `a006eb3c51174f42bde14dcac379a4c8`
from the successful 0.3.2 render. It checked that no job was running, left an
unrelated process with a reused PID untouched, started the new package in a
retained session, and stopped it gracefully after export. No new render or draft
mutation was performed in this final export test.

| Check | Evidence |
| --- | --- |
| Real native generation | 0.3.2 completed one YuE2 job with native exit 0, 47,936 stereo PCM16 frames at 48 kHz, seed 1234 and two midpoint steps. Models passed their six pinned size/SHA checks. |
| Installed export command | 0.3.3 `scripts/player.py` exited 0 through native `riff_audio_chunk`; no direct builder-import workaround or runtime patch. |
| Exact audio | Original and embedded WAV were 191,788 bytes, SHA-256 `3b946eccd47220e3fcdecc84bd0e5ee2c58a63fb8de3a72f895b3a3db039c4f3`. |
| Host format | 306,139-byte fragment; installed Visualize `render.py` exited 0; no document wrappers. Original artwork and motion function were present verbatim, and decompressed motion data matched the native response. |
| Chat display | The final response mounted an iframe titled “Riff 033 Native Player”. |
| Browser controls | Two Chromium tests passed in an opaque sandbox iframe with an offline CSP: trusted keyboard playback, seek, loop, changing canvas frames, exact audio hashes, title injection, MP3 fragment budget, wrong-file rejection and full-WAV selection. No HTTP requests or relaxed autoplay policy. |
| Network-enabled download | The host's approved network-enabled `curl` fetched one 466-byte pinned sidecar, `yue2-generation-config.json`, SHA-256 `203830cebde6e3644eb291925362990d198e66c3b6006cd11f1aaa21904bcc61`. The restricted executor's native HTTPS download had failed; supported host execution can provide the pinned files. |

Source regression validation passed 96 Python tests, five packaging tests and 26
bridge tests. Linux archive acceptance exercised native runtime components and
the installed player CLI with an explicit PCM transport fixture; that smoke is
not a neural generation test. The real generation above occurred in Chat.

Subsequent inspection through the existing signed-in Chrome connection reached the
actual nested Chat iframe. A trusted native-player click advanced `currentTime`
from 0.521333 to 0.870651 seconds while the original canvas changed. Looping
crossed 0.982444 to zero and continued to 0.722662; seeking to 0.5 succeeded.
The player was paused and reset afterward. The full connected studio remains
tracked in issue #2. The short native render establishes functionality;
no listening or musical-quality acceptance is claimed.

## Historical Work probe: not Chat acceptance

On October 20, a fresh ChatGPT Work browser chat executed a read-only probe in
its cloud environment: Ubuntu 24.04.3, glibc 2.39, x86-64, the required AVX2/FMA/
BMI2/F16C flags, an 8 GiB cgroup memory limit, eight CPU equivalents and roughly
28 GiB available disk. Native ELF execution succeeded. GitHub and Hugging Face
responded to bounded HTTPS requests. Python 3.12.14, FFmpeg/FFprobe and Node
were present; CMake, Erlang and Elixir were not on PATH. The package carries its
score runtime and requires no compiler in the user's cloud computer.

This Work probe does not validate the required Chat surface.
These are measured compatibility results for one cloud environment, not a
promise that every future cloud computer is identical. Bundle validation checks
architecture, glibc, CPU requirements and every carried file before startup.

Cloud native generation, account installation and the browser UI must be
verified independently. The CLI does not mount an interactive MCP App. Preserve
the complete studio in the package and report actual cloud preview/MCP UI
support; do not label a returned resource reference as an opened studio.


## Private connected studio transport (0.4.0 candidate)

The existing native plugin keeps its identity. Its cloud package declares a dependency
on the separately provisioned, canonical Sites transport App
`asdk_app_sites_47b8744149508191b69a7fe838be8b6d`, verified in Chat settings.
The companion plugin is `plugin_asdk_app_sites_47b8744149508191b69a7fe838be8b6d`.
No second MCP server mapping is registered for the same Site.

The transport is privately deployed at
https://riff-studio-transport.amusedcorgi5.chatgpt.site. It is an MCP Apps bridge,
not an inference backend. It serves the full original 903,396-byte studio and
all 18 original adapter tool schemas. User identity comes from Sites-authenticated
MCP requests. A one-use five-minute enrollment creates an isolated one-hour
worker capability for the user's own Chat runtime. The helper makes only outbound
HTTPS requests to that fixed origin; native handlers remain socket-free.

Transient commands/results pass through R2 with compare-and-swap claims and
bounded chunks; media remains in hidden tool metadata. The local SQLite journal
prevents mutation replay after an interrupted exchange. Results are erased after
delivery, disconnect erases session messages, and expired sessions are immediately
inaccessible and collected by bounded background scans. Native library, drafts,
LoRAs, scores and models remain in the cloud workspace.

Four transport tests cover concurrent enrollment, cross-user isolation, native
command envelope/media preservation, one-time claims, offline handling and
authenticated commands. Three Python tests cover crash recovery, duplicate
mutations and rejection of arbitrary endpoints. The 99-test source suite passes.

Private acceptance can pass a Sites owner service-access token through an
untracked, mode-600 file. It is never shipped in source, an archive, an enrollment
or a shared prompt. This private access path does not establish general-user
availability. The Site remains owner-private; making its runtime route generally
reachable requires an explicit audience decision and retains per-session runtime
authorization and authenticated MCP identity. Connected studio host acceptance
is still in progress.
