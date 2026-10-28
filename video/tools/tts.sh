#!/bin/sh
# Neural voiceover with Kokoro-82M (Apache-2.0), run locally. vo.mjs calls this as: tts.sh "<text>" <out.wav>
# Voice and speed come from KOKORO_VOICE / KOKORO_SPEED (defaults af_heart, 1.0). Setup: see video/README.md.
# Python venv: $HERE/.venv, else $KOKORO_VENV, else the main checkout's venv (so a git worktree needs no second copy).
set -eu
HERE="$(cd "$(dirname "$0")" && pwd)"
VENV="$HERE/.venv"
[ -x "$VENV/bin/python" ] || VENV="${KOKORO_VENV:-/Users/NS/meta_hackathon/video/tools/.venv}"
exec "$VENV/bin/python" "$HERE/kokoro_tts.py" "$1" "$2"
