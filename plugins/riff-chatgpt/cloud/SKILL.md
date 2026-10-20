---
name: riff-studio
description: Compose and revise songs, generate actual YuE2 music and symbolic scores, manage LoRAs and compare/export recordings using Riff inside this user's ChatGPT Work cloud computer. Use for Riff music requests; the native engine and score/media runtime are bundled with this plugin.
---

# Riff in ChatGPT Work Cloud

Run the bundled Riff runtime in **this user's cloud execution environment**.
Use the command tool available in ChatGPT Work. Never connect to a local
computer, the developer's homelab, or an external inference service. A plugin
installation supplies the executable runtime; music weights download from the
pinned public Hugging Face revision into this cloud workspace on first use.

Resolve `scripts/riff.py` relative to this SKILL.md. Use `python3` to execute it:

```sh
python3 /absolute/path/to/this/skill/scripts/riff.py start
python3 /absolute/path/to/this/skill/scripts/riff.py call riff_read --arguments '{"path":"/api/state"}'
```

The private worker persists between command calls in the cloud computer. Jobs,
saved drafts, models and recordings live outside the replaceable plugin package.
A new/reset cloud computer may need setup again. Save requested outputs to the
user's Library; do not claim storage survives cloud computer deletion.

## First use

Run `start`, then read `/api/state` and `/api/capabilities` with `riff_read`.
If music models are missing, use `riff_setup` with `{}` and poll `/api/system`
until the setup task completes. These are the pinned YuE2 model files, whose
license is CC-BY-NC-4.0; include the model terms when relevant to a commercial
use request. Report actual readiness and errors. Do not replace the engine,
model revision or scheduler with a different music generator.

All 18 existing Riff adapter tools are available through `call TOOL`.
`--arguments` accepts a JSON object or `@/absolute/path/to/arguments.json`.
Inspect the bundled `runtime/server/adapter.py` for tool schemas if needed;
the runtime cache location appears in `start` output. The source is the same
pinned Riff dependency used by the desktop studio.

## Compose, render and inspect

1. Read `riff_get_draft` before changing a song. Save its complete recipe with
   `riff_save_draft`, using the exact `expected_revision` just read. Reconcile
   revision conflicts instead of forcing overwrites. Preserve unrelated score,
   seed, style and LoRA settings.
2. Write or revise the music with ChatGPT. Use the Riff recipe and native schema;
   do not require an OpenRouter key for writing with ChatGPT.
3. When asked to render, call `riff_generate` with the recipe. Queued work is
   not completed audio. Poll `riff_read` at `/api/jobs/<returned-id>` until its
   actual terminal status. Do not resubmit after a command timeout; inspect the
   queue first. Retain error and resume information.
4. A completed job has a real recording ID. Read `/api/tracks/<id>`. Use the
   returned recording file in the workspace's outputs folder, verify its WAV
   header/duration with ffprobe, and save it to the Library for playback/download.
   Never claim to have listened without an audio-capable tool actually hearing it.

The original score, LoRA, media and studio implementations are included. A cloud
CLI call does not itself mount an interactive MCP App in the ChatGPT browser.
Do not claim an interactive studio opened just because `riff_open_studio`
returned its resource reference. Use available cloud browser preview support to
inspect the studio; report the actual host UI support honestly.

## LoRAs, scores and output files

Read `/api/loras`, `/api/loras/hub` and the selected published detail before
installing/selecting a LoRA through `riff_lora`. Preserve revision, source,
license and AR/NAR strengths; recipes use the installed library ID. Installation
must complete and native readiness must confirm compatibility before generation.
Use `riff_edit` for the declared metadata, preset and queue operations.

Binary transport results belong in files. For app-only audio/media chunks,
pass `--output-file /absolute/private/result.json` and decode `_meta` into a
file with Python; stdout deliberately omits these binary values. Prefer the
workspace's original output files for Library publication. Do not paste base64,
keys or audio bytes into the conversation. Optional provider-backed reviews
require the user's configured provider and must not substitute for listening.

For reproducibility, preserve the returned recipe, seed, model/LoRA identity,
job, recording and source receipt alongside exported music when requested.
