# Riff ChatGPT Plugin

Riff music tooling packaged for ChatGPT, downstream of the native Riff project. This repository is downstream of [Riff](https://github.com/Flip-Engineering/riff); it does not maintain a fork of the generation engine or studio.

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

Validation needs Python 3.10+, Node.js, Chromium and FFmpeg/FFprobe. Run it on the homelab with `TMPDIR` and the checkout on NVMe. No hosted compute is required. Python runtime packaging remains separately pinned for user distributions.

## ChatGPT Work Cloud

The cloud distribution runs the bundled native engine inside each user's ChatGPT Work cloud computer, with no homelab or local-computer backend. See [cloud packaging and qualification](docs/chatgpt-cloud.md). It is a skill-driven cloud runtime; interactive MCP App mounting is a separate host integration and must be verified explicitly. The original local stdio distribution remains available.

## Run and package

See [plugin usage](plugins/riff-chatgpt/README.md) and [runtime packaging](docs/chatgpt-plugin-runtime.md). Build the UI with `npm run build:ui`. For development, start `plugins/riff-chatgpt/server/main.py --riff-root "$PWD/riff" --workspace /absolute/private/workspace --ui-file "$PWD/plugins/riff-chatgpt/dist/studio.html"`.

Builders under `plugins/riff-chatgpt/packaging/` consume the verified Riff submodule. `scripts/package_chatgpt_plugin.py` assembles the plugin-owned integration plus the curated pinned upstream runtime. Package receipts identify both the plugin commit and Riff commit. The complete studio and LoRA workflow are retained.

Update Riff by checking out a reviewed upstream revision inside `riff/`, updating `upstream.lock.json`, running validation and committing both pins together. Builders reject mismatched revisions and tracked changes. The UI adapter checks exact integration points and refuses incompatible upstream UI changes.

## Delivery status

Repository extraction and source integration do not constitute a published ChatGPT installation. [Historical validation](docs/chatgpt-plugin-validation.md) records pre-extraction evidence; fresh downstream results are tracked separately in [extraction validation](docs/downstream-validation.md). Platform package builds, real model inference, Apple Silicon behavior and actual ChatGPT host installation must each be reported independently. Music weights are downloaded separately under their own terms.
