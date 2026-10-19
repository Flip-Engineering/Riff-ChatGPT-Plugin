---
name: riff-studio
description: Compose and revise music in Riff's embedded visual studio, synchronize a song with ChatGPT, generate native YuE2 recordings or scores, manage the queue and LoRAs, compare takes, and request configured producer reviews. Use when the user asks to work in Riff and its MCP tools are connected.
---

# Riff studio

Open `riff_open_studio` for the complete studio or `riff_open_project` for the
current song beside this conversation. Both accept an empty object. Keep the
visual editing, score, listening and library workflow available throughout.

## Read the song before changing it

1. Read `riff_get_draft` for the saved recipe and revision. Use attached Riff
   context to understand the visible selection and any unsaved editor changes.
2. Read `riff_read` with `/api/capabilities` when choosing unfamiliar recipe
   fields, and `/api/state` for actual engine readiness, jobs and recordings.
3. Apply the requested creative change to the complete recipe. Preserve unrelated
   settings, seed, score references and installed LoRA selections. Do not invent
   recording, score, acoustic or adapter identifiers.
4. Save with `riff_save_draft`, supplying the exact `expected_revision` just read.
   On a conflict, read again and reconcile the changes; do not force an overwrite.

Open studios poll shared drafts. A clean editor applies a new revision; an editor
with unsaved changes keeps them and offers **Restore shared draft**. Explain the
conflict when one occurs. Saving a draft does not generate audio.

For requests sent through **Write with ChatGPT**, complete the writing or recipe
edit yourself and save the result to the shared draft. The studio receives it
through that same revision mechanism. Use lyrics mode for newly supplied lyrics,
or retain the user's instrumental/free mode as appropriate. Do not leave a new
ChatGPT-written song dependent on an unavailable local AI writer.

## Make music and inspect the result

Use `riff_generate` with an explicit recipe when the user requests generation.
Set `plan_only: true` only for a requested symbolic score; the recipe must enable
melody or full planning. Read the returned job at `/api/jobs/<id>` until it reaches
its actual terminal state. A queued submission, plan, saved performance or saved
sound is distinct from a completed recording.

After a completed render, read `/api/tracks/<track_id>` and open its recording in
the studio. Describe errors and available recovery stages from the actual job.
Do not silently retry an ambiguous or timed-out submission: inspect the queue
first so the same request does not render twice. Do not claim to have listened
unless audio was actually provided to an audio-capable tool or model.

Use `riff_edit` for supported track metadata, presets, queue movement and
cancellation. Retry with the inspected recipe through `riff_generate` when
requested. Use the exact paths and identifiers returned by Riff. Keep
permanent recording deletion and browser-selected file import in the studio.

## Setup, writing providers and style adapters

If models are missing, use `riff_setup` for the requested model download or open
Studio settings. The platform package supplies Python, the native engine, media
tools and the score runtime; setup downloads pinned music models into its own
workspace. Read `/api/system` for progress and errors. The model terms appear in
the studio. Do not replace packaged executable/model locations or install an
external application to work around a missing runtime.

Use `riff_write` only when the user wants Riff's configured provider to produce
ideas or revise a score. **Write with ChatGPT** uses the conversation instead.
Use `riff_review` when a producer review is requested; starting one sends the
selected audio and recipe to the configured OpenRouter provider. Read review
status before reporting a result. Enter credentials only through the app's
Review settings, never through chat or shared draft/context fields.

Read `/api/loras/hub`, its detail route and `/api/loras` before selecting an
adapter. Preserve the published revision, compatibility, stages and license
information. Use `riff_lora` for an authorized install, metadata update, removal
or cancellation; inspect the resulting task until complete. A recipe refers to
the installed 64-character library ID and its AR/NAR strengths, never a filename
or an unverified Hub title. An adapter removal needs `body.confirm: true` and
must pass Riff's references check.

## App data and host capabilities

Use `riff_settings_read` and `riff_settings_update` for the declared display,
context-sharing, playback-cache and draft preferences. Updates contain only the
changed keys under `set`.

Treat `riff_ui_request`, binary chunk and upload tools as app-only transports.
The UI keeps media bytes in tool-result metadata and uses the host's download
service for WAV, MP4, artwork, recipe, ABC and MIDI exports. Never paste binary
base64 or credentials into the conversation. Use a returned recording reference;
do not invent a public URL or a ChatGPT plugin ID.

Report an unavailable native engine, missing UI resource or unsupported host
capability accurately. Distinguish a built platform package, a connected plugin,
a browser fixture and a real music render. This local stdio distribution needs
a host that executes packaged processes and displays MCP Apps; source files alone
are not an installed ChatGPT web app.
