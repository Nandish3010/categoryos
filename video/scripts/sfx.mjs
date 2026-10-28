// Synthesises all sound effects with ffmpeg (sine/noise generators only: no sampled or copyrighted audio) into out/sfx/*.wav
import fs from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';

const out = path.resolve(import.meta.dirname, '../out/sfx');
fs.mkdirSync(out, { recursive: true });
const FF = '/opt/homebrew/bin/ffmpeg';
const run = (args) => execFileSync(FF, ['-y', '-loglevel', 'error', ...args]);
const ev = (name, expr, d, post = '') =>
  run(['-f', 'lavfi', '-i', `aevalsrc='${expr}':s=44100:d=${d}`, ...(post ? ['-af', post] : []), '-ar', '44100', '-ac', '1', path.join(out, `${name}.wav`)]);
const noise = (name, d, af, color = 'pink') =>
  run(['-f', 'lavfi', '-i', `anoisesrc=d=${d}:c=${color}:r=44100:a=0.5`, '-af', af, '-ac', '1', path.join(out, `${name}.wav`)]);

// The only noise-based effect: ONE short, quiet, narrow-band swish for the few key transitions (slam zoom, buried, week melt).
noise('whoosh', 0.32, 'highpass=f=700,lowpass=f=3200,afade=t=in:d=0.14,afade=t=out:st=0.14:d=0.18,volume=0.8');
ev('pop', 'sin(2*PI*(450+1400*exp(-t*35))*t)*exp(-t*28)*0.8', 0.16);
ev('blip', '(sin(2*PI*988*t)*exp(-t*22)+gt(t,0.07)*sin(2*PI*1319*(t-0.07))*exp(-(t-0.07)*20))*0.55', 0.28);
ev('tock', 'sin(2*PI*(900-300*t)*t)*exp(-t*70)*0.7', 0.07);
ev('pluck', '(sin(2*PI*659.3*t)+0.4*sin(2*PI*1318.6*t))*exp(-t*14)*0.5', 0.3);
ev('tick', 'sin(2*PI*2200*t)*exp(-t*180)*0.6', 0.04);
ev('thud', 'sin(2*PI*(60+90*exp(-t*20))*t)*exp(-t*16)*0.95', 0.3);
ev('slam', '(sin(2*PI*(45+120*exp(-t*9))*t)*exp(-t*6)+0.25*sin(2*PI*900*t)*exp(-t*40))*0.95', 0.9);
ev('ding', '(sin(2*PI*1318.5*t)+0.45*sin(2*PI*1975.5*t)+0.2*sin(2*PI*2637*t))*exp(-t*4.5)*0.35', 1.4);
ev('ring', '(sin(2*PI*440*t)+sin(2*PI*480*t))*0.28*gt(sin(2*PI*14*t),0)', 0.9);
ev('buzz', 'sin(2*PI*180*t)*gt(sin(2*PI*9*t),0)*0.3', 0.5);
ev('alert', '(sin(2*PI*880*t)*gt(sin(2*PI*5*t),0))*0.35', 0.6);
ev('chime', '(sin(2*PI*523.25*t)*exp(-t*3)+gt(t,0.12)*sin(2*PI*659.25*(t-0.12))*exp(-(t-0.12)*3)+gt(t,0.24)*sin(2*PI*783.99*(t-0.24))*exp(-(t-0.24)*3)+gt(t,0.36)*sin(2*PI*1046.5*(t-0.36))*exp(-(t-0.36)*2.5))*0.3', 1.8);
ev('error', '(sin(2*PI*220*t)+sin(2*PI*233*t))*exp(-t*6)*0.35', 0.5);
console.log('sfx:', fs.readdirSync(out).join(' '));
