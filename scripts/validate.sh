#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
python3 -B -c 'import sys; sys.path.insert(0, "plugins/riff-chatgpt/scripts"); from riff_dependency import riff_root; print("Pinned Riff:", riff_root())'
python3 -B -m unittest discover -s plugins/riff-chatgpt/tests -p 'test_*.py' -v
python3 -B -m unittest discover -s plugins/riff-chatgpt/packaging -p 'test_*.py' -v
node --test plugins/riff-chatgpt/tests/bridge.test.cjs
python3 -B plugins/riff-chatgpt/scripts/build_ui.py --riff-web riff/web
node plugins/riff-chatgpt/tests/browser.test.cjs
node --test plugins/riff-chatgpt/tests/player.test.cjs
