#!/bin/zsh
# Dev helper: render quick preview stills of the Demo composition. Usage: tools/stills.sh <outdir> <frame> [frame ...]
cd "$(dirname "$0")/.."
out=$1; shift
mkdir -p "$out"
for f in "$@"; do
  npx remotion still src/index.ts Demo "$out/f$f.png" --frame=$f --log=error > /dev/null 2>&1
done
echo done
