# Downstream extraction validation

Origin: [Riff PR #32](https://github.com/Flip-Engineering/riff/pull/32), commit `cd98f3f4191c2b1356d6048bfe44b3848d31cb2d`.
Pinned upstream: `b7ab93cf22ffd9e95a7718aca2e0d451578411b1` (Riff main with standalone LoRA).
Tested downstream code: `d49e3b7bf142a8ce8268fd55b6b978fee9704eb4`.

The extraction retains plugin-owned files and full contributor history, replaces monorepo-root assumptions with the pinned dependency, and records upstream/plugin identities separately in package metadata. Riff core is represented only by a submodule in the current tree.

## Fresh homelab results

Validated on October 20, 2026 in an isolated NVMe workspace using `scripts/validate.sh`:

- 89 Python plugin/protocol/dependency/credential tests passed.
- 5 runtime packaging tests passed.
- 26 JavaScript bridge tests passed.
- All 14 browser scenarios passed through production ManagedRiff, the upstream studio, SQLite, loopback HTTP, and actual stdio MCP. Tests include shared drafts/conflicts, writing/context, verified LoRA imports and provenance, audio playback, original ABC editing and MIDI export, review settings and recommendation export, real FFmpeg MP4 export, responsive layouts, fallback playback/encoding and teardown.
- The complete UI was bundled from the pinned Riff web sources, preserving hashes and exact adapter-point checks.
- The Linux control runtime built from the pinned Riff installer/runtime sources and passed its actual scheduler capability check.
- The downstream packager verified an existing CPU engine against the exact pinned native source/14-patch set and production LoRA capability contract. Its binary SHA-256 is recorded in the receipt.

[Machine-readable evidence](evidence/downstream-source-2026-10-20.json) includes test scope, all browser checks, tool calls, control input hashes and native source/binary identity. Logs and generated runtime artifacts remain on the homelab under `riff-chatgpt-plugin-downstream-20261020/.validation/`.

The extraction fixed a browser listener fixture that inherited the monorepo working directory and a Linux headless-keyring detection bug. It also resolved the control packaging helper from the pinned upstream project instead of the deleted monorepo-relative installer path.

## Execution and remaining delivery work

The plugin's browser and platform-package workflows use owned self-hosted runners only. The existing homelab runner group now permits this repository and only these reviewed workflow paths on main; existing permissions remain intact. [Infrastructure issue #1](https://github.com/Flip-Engineering/Riff-ChatGPT-Plugin/issues/1) records the setup and execution result.

Browser neural inference, admission, Hub and review providers use explicit fixtures. No paid provider was called. This is fresh downstream source and control-runtime validation, not a newly assembled complete user distribution, GPU inference result or actual ChatGPT installation. Historical package and inference receipts retain their pre-extraction dates. Full Linux/Apple Silicon package assembly and production host installation remain separate delivery work.

## Independent self-hosted CI result

[Browser run 39450808327](https://github.com/Flip-Engineering/Riff-ChatGPT-Plugin/actions/runs/39450808327) succeeded on downstream source `d49e3b7`. The job ran on owned homelab runner `atari-homelab-baton2-native` in group `baton2-native-homelab`. All 14 browser acceptance scenarios passed. Later changes only record evidence and documentation.
