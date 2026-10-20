# Riff ChatGPT Plugin

Turn your ideas into songs with vocals and instruments in ChatGPT. Write and revise lyrics, shape melodies and arrangements, listen to your music, and download the results. This repository packages [Riff](https://github.com/Flip-Engineering/riff) for ChatGPT.

## Source and dependency

Extracted from [Riff PR #32](https://github.com/Flip-Engineering/riff/pull/32), source commit `cd98f3f4191c2b1356d6048bfe44b3848d31cb2d`. Its full Git ancestry is preserved so original authorship and the original integration remain inspectable. The extraction commit removes upstream implementation files from this repository's working tree.

Riff is a Git submodule at `riff/`, locked in `upstream.lock.json` to `b7ab93cf22ffd9e95a7718aca2e0d451578411b1`, the merge of standalone LoRA PR #28. This plugin owns MCP tools, the ChatGPT bridge and UI integration, shared drafts/settings, plugin metadata, packaging and host acceptance tests. Upstream Riff owns generation, LoRAs, recordings, the studio and native/control/media source pins.

```sh
git clone --recurse-submodules https://github.com/Flip-Engineering/Riff-ChatGPT-Plugin.git
cd Riff-ChatGPT-Plugin
npm ci
npx playwright install chromium
./scripts/validate.sh
```

Validation needs Python 3.10+, Node.js, Chromium and FFmpeg/FFprobe. Development validation runs on the homelab with `TMPDIR` and the checkout on NVMe. Python runtime packaging remains separately pinned for user distributions.

## ChatGPT Chat target

ChatGPT Chat is the required user surface. The cloud distribution bundles the native engine for execution in the user's Chat environment. Private installation, native CPU generation, exact WAV export and inline player display have passed in Chat. Version 1.1.1 combines the native runtime, music skill and connected original Studio in one app-backed Riff plugin. Actual Chat checks cover library playback with the custom visualizer, seek and looping, shared score editing, and public LoRA installation and selection. The full studio transferred and played a complete 180-second WAV fixture; the separate standalone recording panel uses a labeled preview for larger files. See [the measured results and limits](docs/chatgpt-cloud.md). Writing and reviews use the current ChatGPT session. Studio writing, reviews and WAV export send requests directly to the current ChatGPT conversation from the original button event. The hosted bridge is an internal component of that plugin. The original local stdio distribution remains available.

## Run and package

See [plugin usage](plugins/riff-chatgpt/README.md) and [runtime packaging](docs/chatgpt-plugin-runtime.md). Build the UI with `npm run build:ui`. For development, start `plugins/riff-chatgpt/server/main.py --riff-root "$PWD/riff" --workspace /absolute/private/workspace --ui-file "$PWD/plugins/riff-chatgpt/dist/studio.html"`.

Builders under `plugins/riff-chatgpt/packaging/` consume the verified Riff submodule. `scripts/package_chatgpt_plugin.py` assembles the plugin-owned integration plus the curated pinned upstream runtime. Package receipts identify both the plugin commit and Riff commit. The complete studio and LoRA workflow are retained.

Update Riff by checking out a reviewed upstream revision inside `riff/`, updating `upstream.lock.json`, running validation and committing both pins together. Builders reject mismatched revisions and tracked changes. The UI adapter checks exact integration points and refuses incompatible upstream UI changes.

## Delivery status

The cloud package is privately installed and tested; it has not been published to the public directory. [Historical validation](docs/chatgpt-plugin-validation.md) records pre-extraction evidence; downstream results are tracked in [extraction validation](docs/downstream-validation.md) and [Chat acceptance](docs/chatgpt-cloud.md). Platform package builds, real model inference, Apple Silicon behavior and actual ChatGPT host installation are reported independently. Music weights are downloaded separately under their own terms.
