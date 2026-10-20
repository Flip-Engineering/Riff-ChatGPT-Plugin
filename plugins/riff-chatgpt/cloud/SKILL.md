---
name: riff-studio
description: Compose and revise songs, generate actual YuE2 music and symbolic scores, manage LoRAs and compare/export recordings using Riff inside this user's ChatGPT Chat cloud execution environment. Use for Riff music requests; the native engine and score/media runtime are bundled with this plugin.
---

# Riff in ChatGPT Chat

Run the bundled Riff runtime in **this user's cloud execution environment**.
Use the Python or command execution tool actually available in ChatGPT Chat.
If this Chat cannot execute the bundled runtime, report the concrete error;
do not switch to Work or claim generation succeeded. Never connect to a local
computer, the developer's homelab, or an external inference service. A plugin
installation supplies the executable runtime; music weights download from the
pinned public Hugging Face revision into this cloud workspace on first use.

Resolve `scripts/riff.py` relative to this SKILL.md. Use `python3` to execute it:

```sh
python3 /absolute/path/to/this/skill/scripts/riff.py start
python3 /absolute/path/to/this/skill/scripts/riff.py call riff_read --arguments '{"path":"/api/state"}'
```

The private filesystem-mailbox worker opens no network or Unix sockets.
Its native routes run in process. The worker is designed to persist between execution calls. Verify it
is still running before reusing it; host session lifetime is not guaranteed. Jobs,
saved drafts, models and recordings live outside the replaceable plugin package.
A new/reset cloud computer may need setup again. Save requested outputs to the
user's Library; do not claim storage survives cloud computer deletion.
Worker ownership uses a held file lock, not a PID that may be invisible or reused
across execution namespaces. If this host reaps detached processes, keep startup,
generation and polling in the same retained execution session. Never replay a
mutation after losing its worker; inspect persisted jobs and the request first.

## First use

Run `start`, then read `/api/state` and `/api/capabilities` with `riff_read`.
If music models are missing, use `riff_setup` with `{"action":"setup"}` and poll `/api/system`
until the setup task completes. These are the pinned YuE2 model files, whose
license is CC-BY-NC-4.0; include the model terms when relevant to a commercial
use request. Report actual readiness and errors. Do not replace the engine,
model revision or scheduler with a different music generator.
If the command sandbox denies HTTPS downloads, use the host's supported download
or file-transfer tools for the exact files and revision in the bundled
`riff/sources.json`. Place them at the runtime's declared model paths, then run
`riff_setup` again so Riff verifies every size and SHA-256 before use. Do not
change pins, patch the native runtime or use an external inference backend.

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

## Display the player in Chat

### Connected full studio

When the user asks for the complete studio, use the private **Riff Studio
Transport** companion when it is connected. Its canonical plugin is
https://chatgpt.com/plugins/plugin_asdk_app_sites_47b8744149508191b69a7fe838be8b6d.
It carries MCP Apps commands and media; the native engine and every project
file stay in this user's Chat cloud workspace. It is not an inference service.
Preserve this Riff plugin and its workspace when connecting the companion.

1. Call the companion's `riff_runtime_status`. Reuse an online connection; never
   start a duplicate relay. If offline but already paired, inspect its exact
   process identity and private log before resuming the same workspace. Do not
   replace an existing pairing or start a different native workspace silently.
2. For an unpaired runtime, call its `riff_connect_runtime` and save the returned
   enrollment JSON to a private file. Prepare the adjacent `scripts/relay.py`
   launch with `--workspace /exact/workspace --enrollment-file /private/enrollment.json`.
   The helper consumes the one-use enrollment file and stores its own private
   session capability. Never paste worker credentials or media bytes in chat.
3. Launch the relay from the host's **network-enabled** execution tool. Prefer
   a detached process with its own OS session, `/dev/null` input and a private
   file log. This exact method survived launcher return, separate execution
   calls and a subsequent normal conversation turn in actual Chat acceptance:

   ```python
   import os, subprocess, sys
   from pathlib import Path
   workspace = Path("/exact/existing/workspace")
   relay = Path("/absolute/path/to/this/skill/scripts/relay.py")
   log_path = workspace / "studio-relay.log"
   # First establish that no relay already owns this workspace. Preserve any
   # existing pairing; append enrollment/private-owner flags only when needed.
   flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW
   with os.fdopen(os.open(log_path, flags, 0o600), "ab") as log:
       os.fchmod(log.fileno(), 0o600)
       process = subprocess.Popen(
           [sys.executable, "-B", str(relay), "--workspace", str(workspace)],
           stdin=subprocess.DEVNULL, stdout=log, stderr=log,
           start_new_session=True,
       )
   print({"relay_pid": process.pid, "private_log": str(log_path)})
   ```

   For first pairing, include `--enrollment-file /private/enrollment.json` in
   that same command. For private owner acceptance only, also include the
   existing `--service-access-file`; never expose its contents. Wait for
   `connected` in the private log, verify the exact process identity and only
   one instance, and call `riff_runtime_status` plus a native read after the
   launcher has returned. A PID or successful Popen alone is not readiness.
   If this host reaps detached processes, use a retained network-enabled
   execution session and verify it between turns. Neither method guarantees
   cloud-computer lifetime. The native worker opens no listener; only the
   relay makes outbound HTTPS requests to its fixed endpoint.
4. Call the companion's `riff_open_studio`. Its registered MCP resource opens
   the complete original studio, including library, LoRA and score navigation.
   Use the same companion tools for conversational changes so UI and chat share
   the native state and revision checks. A displayed panel is not sufficient:
   verify state, library selection and an actual edit through its command channel.
5. If the cloud process stops, report offline status and resume it explicitly.
   Interrupted mutations are never replayed. Inspect job/draft state before retrying.
   Disconnect through `riff_disconnect_runtime` only when the user requests it
   or at the end of an explicitly temporary acceptance test; native data survives.

The companion currently has an **owner-private** Sites audience. Do not change
its audience or claim general availability. During private owner acceptance,
Sites service access may be supplied to the helper through a private
`--service-access-file`. Never put that owner credential in a plugin archive,
shared enrollment, prompt or source. Other users must not depend on it. If that
private access is unavailable, report the actual connection failure and use the
self-contained player below; do not expose studio controls with a fake backend.

### Self-contained recording player

After generating or selecting a recording, **display its player in Chat**. Do
not stop at a WAV attachment or a tool response. The bundled helper exports the
actual native visualization data and original Riff artwork renderer:

```sh
python3 /absolute/path/to/this/skill/scripts/player.py \
  --track-id RECORDING_ID --output /workspace/riff-player-RECORDING_ID.html
```

Pass the same `--workspace` used for generation if it differs from the default.
Use the host's available Visualize/HTML panel capability to render that exact
HTML inline. Read that capability's instructions first. Preserve the original
renderer and recording; do not rebuild them with an approximation. The player
includes play/pause, seeking, loop, download and the recording receipt. Save the
original WAV and receipt to Library too. If the host cannot display HTML, report
the actual error and provide the HTML file and audio as downloadable fallbacks.
An HTML file alone is not an opened panel. Verify playback and visualization in
the displayed panel when browser inspection is available.
The helper emits an HTML **fragment**, as Visualize requires, with a unique root
and scoped controls/styles. Keep it in `/workspace` and display it using the
host's documented absolute-path content reference in the **final response**.
Do not invent a registration API or save inline fragments to Library. If the user
requests an HTML download, use the host's documented standalone export wrapper
and save that separate deliverable. Do not wrap the inline fragment in a full
`<!doctype>`, `<html>`, `<head>` or `<body>` document before registration.

Visualize's installed helper limits HTML fragments to 1,000,000 bytes. The player
embeds the exact WAV when it fits. Otherwise it uses bundled FFmpeg to make a
clearly labeled MP3 preview sized to that physical budget. Original visualization
frames are gzip-compressed without loss. **Always save the full original WAV to
Library.** The panel's Open full WAV control lets the user select that downloaded
file, verifies its SHA-256 against the receipt, and enables full-length playback
and visualization locally. It never uploads the selected file. Do not call the
embedded preview the full recording. If the original analysis alone exceeds the
host budget, report the helper's actual error and provide the files separately.

This fallback is a self-contained recording player, not a connected studio. Do not expose
library/LoRA/composition controls that lack a working native command connection.

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

Actual Chat file uploads currently reject WAV, ABC and MIDI, and a component
follow-up message may stall even when its API returns. The studio prepares a
visible, copyable request for the user to paste into Chat instead of sending
through that unreliable path. Do not report Library publication from a panel
status alone. When asked in a normal conversation,
publish the original workspace files through an available documented host
file-output tool, reconcile any uncertain earlier save first, and verify the
recording is available to play or download. Do not add audio checksum chores
to user-facing verification. If a prepared upload helper
fails before writing, use another supported host file-output route; do not
require that helper or replay an uncertain save. Distinguish successful
conversation export from unsupported panel export and report concrete errors.

Writing and listening reviews use this ChatGPT session. The plugin has no
OpenRouter configuration and installs no separate Qwen/MLX writer. Use your
own writing ability to revise lyrics, musical direction and ABC, then save
the shared draft with its current revision and idea_engine="chatgpt". YuE2
composes melody/chord scores and renders music; use riff_generate with
plan_only=true for native score composition. For Surprise song, write the
lyrics before submitting generation. Phrase shuffle remains an optional
instant source. Legacy native provider selections are routed to ChatGPT,
never to a separate model or paid provider.
