// Dev helper: contact sheet of a video. node tools/sheet.mjs <in.mp4> <everySec> <cols> <rows> <out.png> [startSec] [thumbW]
import { execFileSync } from 'node:child_process';
const [inp, every, cols, rows, out, start = '0', tw = '480'] = process.argv.slice(2);
const th = Math.round((+tw * 9) / 16);
const d = execFileSync('/opt/homebrew/bin/ffprobe', ['-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', inp]).toString().trim();
console.log('duration', d);
execFileSync('/opt/homebrew/bin/ffmpeg', ['-y', '-loglevel', 'error', '-ss', start, '-i', inp, '-vf', `fps=1/${every},scale=${tw}:${th},tile=${cols}x${rows}`, '-frames:v', '1', out]);
