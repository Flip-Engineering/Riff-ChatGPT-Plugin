# Riff in ChatGPT Chat

The candidate cloud package is designed to run Riff in each user's ChatGPT Chat cloud execution environment. It has
no external MCP endpoint and never uses the developer's homelab or the user's
local computer as its production backend. The homelab remains a build/CI host.
Private installation and real native generation have passed in ChatGPT Chat.
The original 0.3.0 package required writable-path, socket and setup recoveries;
0.3.1 replaces its socket transports. Fresh-Chat validation of worker persistence
is still in progress. A connected full studio has not passed Chat acceptance.

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
the pinned upstream `artwork.js` and `motionAt` unchanged, the original WAV,
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
