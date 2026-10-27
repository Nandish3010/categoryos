#!/bin/zsh
# Dev helper: render preview stills of the XCut composition. Usage: tools/xstills.sh <outdir> <frame> [frame ...]
cd "$(dirname "$0")/.."
out=$1; shift
mkdir -p "$out"
for f in "$@"; do
  npx remotion still src/index.ts XCut "$out/x$f.png" --frame=$f --log=error > /dev/null 2>&1
done
echo done
