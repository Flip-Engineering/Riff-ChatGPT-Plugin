# Downstream extraction validation

Origin: Riff PR #32, commit `cd98f3f4191c2b1356d6048bfe44b3848d31cb2d`.
Pinned upstream: `b7ab93cf22ffd9e95a7718aca2e0d451578411b1` (Riff main with standalone LoRA).

The first extraction retains plugin-owned files and history, replaces monorepo root assumptions with the pinned dependency, and records upstream/plugin identities separately in package metadata. Riff core is represented only by a submodule in the current tree.

Fresh source/protocol/browser results will be recorded after running `scripts/validate.sh` on the homelab. Prior package and inference receipts in the historical validation documents predate extraction and must not be represented as fresh downstream package qualification.
