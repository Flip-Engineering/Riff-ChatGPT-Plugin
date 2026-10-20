# Self-hosted runners

Issue #31 tracks the move of Riff validation and delivery jobs to self-hosted
runners, including the remote Apple Silicon qualification target.

## Runner requirements

| Jobs | Required labels | Required environment |
| --- | --- | --- |
| Linux source, browser, CPU native, release, and Pages | `self-hosted`, `Linux`, `X64`, `baton2-native-linux-x64` | Supported Ubuntu image; Python 3.9 and 3.14; Node 22; OTP 28.0.2; Elixir 1.18.4; Rust 1.89; FFmpeg/FFprobe; CMake; C/C++ build tools; Playwright Chromium dependencies |
| Apple Silicon source, browser, Metal native, plugin, and desktop | `self-hosted`, `macOS`, `ARM64` | macOS 15 or newer; full Xcode with Metal compiler; Python 3.14; Node 22; OTP 28.0.2; Elixir 1.18.4; Rust 1.89; CMake 4.4.3; FFmpeg/FFprobe |
| CUDA compile probe | `self-hosted`, `Linux`, `X64`, `riff-cuda` | Linux runner with Docker, NVIDIA container runtime, and a supported CUDA GPU |

The workflows verify required host packages and tools. The pinned CUDA workflow
installs packages inside its pinned container image.

## Provisioning status

Organization runner inventory reviewed on 2026-10-20 showed two online Linux
runners with the `baton2-native-linux-x64` label. The `baton2-native-homelab`
runner group includes this repository and permits selected workflows. At review,
its Riff allowlist contained only
`Flip-Engineering/riff/.github/workflows/homelab-linux-validation.yml@refs/heads/main`;
`ci.yml`, `chatgpt-plugin.yml`, `chatgpt-plugin-browser.yml`, `desktop.yml`,
`pages.yml`, and `release.yml` were not allowlisted. Those workflows cannot use
the group until an organization owner updates its policy. The inventory
contained no `macOS`/`ARM64` runner and no `riff-cuda` runner. Rerun the
inventory and inspect runner-group workflow access before dispatching; these
facts can change independently of this repository.

## Workflow access and source trust

The manual Linux and Apple Silicon qualification workflows accept an exact
source commit and record its SHA. GitHub permits workflow dispatch by users who
can write to the repository. The standard `pull_request` jobs run on self-hosted
runners only when the pull request head belongs to this repository. Fork-origin
pull requests skip those jobs; a maintainer can use the manual exact-source
workflow after reviewing the proposed source. Keep the organization runner-group
workflow allowlist restricted to reviewed workflow paths.

The Apple Silicon workflow writes `runner.json` with the runner and source
identity before setup actions, then writes `toolchain.json` after setup-python,
setup-node, and setup-beam. The latter records the versions active for the
checks. The Linux manual workflow records runner and source identity separately.
Actual self-hosted runs and remote Apple Silicon qualification remain pending
until the runner-group policy and required platforms are provisioned and their
workflows complete successfully. The shared compiler queue in
`Flip-Engineering/baton#970` is also required for native build qualification.
