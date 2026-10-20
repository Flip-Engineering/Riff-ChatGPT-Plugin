# Self-hosted runners

Issue #31 moves standard Riff validation and delivery jobs off GitHub-hosted
runners. The workflow source now requires these labels:

| Purpose | Runner labels | Required platform/toolchain |
| --- | --- | --- |
| Linux source, browser, CPU native, release and Pages | `self-hosted`, `Linux`, `X64`, `baton2-native-linux-x64` | Ubuntu 22.04/24.04/26.04; Python 3.9 and 3.14; Node 22; OTP 28.0.2; Elixir 1.18.4; Rust 1.89; FFmpeg/FFprobe; CMake; C/C++ build tools; Playwright Chromium dependencies; Docker for the CUDA container job |
| Apple Silicon source, browser, Metal native, plugin and desktop | `self-hosted`, `macOS`, `ARM64` | macOS 15 or newer; full Xcode including the Metal compiler; Python 3.14; Node 22; OTP 28.0.2; Elixir 1.18.4; Rust 1.89; CMake 4.4.3; FFmpeg/FFprobe |
| CUDA compile probe | `self-hosted`, `Linux`, `X64`, `riff-cuda` | Linux runner with Docker, NVIDIA container runtime and a supported CUDA GPU |

`Apple Silicon qualification` is a manual exact-source workflow. It records the
runner name, OS, architecture, macOS version, Xcode version, Metal compiler path,
Python/Node/Elixir/Rust/CMake/FFmpeg versions, and the exact source SHA in its
artifact before running source, browser and Metal checks.

The Linux homelab workflow remains the exact-source Linux route. The standard
workflows now use the same self-hosted Linux label. Actual self-hosted runs,
runner identity receipts and remote Apple Silicon qualification remain pending
until the runners are provisioned and the shared compiler queue in
`Flip-Engineering/baton#970` is qualified; a configured workflow is not evidence
that its run passed.
