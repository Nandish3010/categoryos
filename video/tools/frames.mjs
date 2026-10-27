// Dev helper: 2x2 sheet of 4 timestamps at 960x540 each. node tools/frames.mjs <in.mp4> <out.png> t1 t2 t3 t4
import { execFileSync } from 'node:child_process';
const [inp, out, ...ts] = process.argv.slice(2);
const args = ['-y', '-loglevel', 'error'];
ts.forEach((t) => args.push('-ss', t, '-i', inp));
const fc = ts.map((_, i) => `[${i}:v]select=1,scale=960:540[v${i}]`).join(';') + ';' + ts.map((_, i) => `[v${i}]`).join('') + `xstack=inputs=${ts.length}:layout=0_0|960_0|0_540|960_540[o]`;
args.push('-filter_complex', fc, '-map', '[o]', '-frames:v', '1', out);
execFileSync('/opt/homebrew/bin/ffmpeg', args);
