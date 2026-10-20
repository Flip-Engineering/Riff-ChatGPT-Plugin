# Riff in ChatGPT Work Cloud

The cloud plugin runs Riff in each user's ChatGPT Work cloud computer. It has
no external MCP endpoint and never uses the developer's homelab or the user's
local computer as its production backend. The homelab remains a build/CI host.

The cloud distribution is a portable plugin containing a skill, a small Python
launcher and a checksum-verified native runtime archive. ChatGPT Work supplies
Python 3.12+. The package carries the pinned Riff source, CPU YuE2 engine,
Elixir/ERTS score/control runtime, media executables, libraries, studio source
and component notices. The separately licensed music models download from the
pinned public Hugging Face revision into the user's cloud workspace.

A worker inside that cloud computer owns a private Unix socket. Successive
cloud command calls use the existing adapter and share the same native jobs,
drafts, LoRA library and recordings. No public port or developer credentials
are needed. The original stdio/MCP App distribution remains separate.

Build a complete Linux CPU platform package with the existing builder, then:

```sh
python3 scripts/package_cloud_plugin.py \
  --runtime-package /absolute/platform/package/riff-chatgpt \
  --output /absolute/output/riff-chatgpt-cloud.zip
```

Install the resulting archive through ChatGPT's private plugin importer and
start a fresh Work chat. The skill launches its bundled runtime with:

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

## Actual host qualification

On October 20, a fresh ChatGPT Work browser chat executed a read-only probe in
its cloud environment: Ubuntu 24.04.3, glibc 2.39, x86-64, the required AVX2/FMA/
BMI2/F16C flags, an 8 GiB cgroup memory limit, eight CPU equivalents and roughly
28 GiB available disk. Native ELF execution succeeded. GitHub and Hugging Face
responded to bounded HTTPS requests. Python 3.12.14, FFmpeg/FFprobe and Node
were present; CMake, Erlang and Elixir were not on PATH. The package carries its
score runtime and requires no compiler in the user's cloud computer.

These are measured compatibility results for one cloud environment, not a
promise that every future cloud computer is identical. Bundle validation checks
architecture, glibc, CPU requirements and every carried file before startup.

Cloud native generation, account installation and the browser UI must be
verified independently. The CLI does not mount an interactive MCP App. Preserve
the complete studio in the package and report actual cloud preview/MCP UI
support; do not label a returned resource reference as an opened studio.
