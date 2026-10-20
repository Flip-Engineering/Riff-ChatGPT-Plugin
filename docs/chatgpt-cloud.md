# Riff in ChatGPT Chat

The candidate cloud package is designed to run Riff in each user's ChatGPT Chat cloud execution environment. It has
no external MCP endpoint and never uses the developer's homelab or the user's
local computer as its production backend. The homelab remains a build/CI host.
Installation and native generation in ChatGPT Chat have not yet passed end-to-end validation.

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
