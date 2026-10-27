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

noise('whoosh', 0.7, 'highpass=f=250,lowpass=f=4200,afade=t=in:d=0.3,afade=t=out:st=0.3:d=0.4,volume=1.6');
noise('whoosh-short', 0.4, 'highpass=f=300,lowpass=f=5000,afade=t=in:d=0.15,afade=t=out:st=0.15:d=0.25,volume=1.4');
ev('pop', 'sin(2*PI*(450+1400*exp(-t*35))*t)*exp(-t*28)*0.9', 0.18);
ev('tick', 'sin(2*PI*1900*t)*exp(-t*140)*0.8', 0.06);
ev('thud', 'sin(2*PI*(60+90*exp(-t*20))*t)*exp(-t*16)*0.95', 0.3);
ev('slam', '(sin(2*PI*(45+120*exp(-t*9))*t)*exp(-t*6)+0.25*sin(2*PI*900*t)*exp(-t*40))*0.95', 0.9);
ev('ding', '(sin(2*PI*1318.5*t)+0.45*sin(2*PI*1975.5*t)+0.2*sin(2*PI*2637*t))*exp(-t*4.5)*0.35', 1.4);
ev('ring', '(sin(2*PI*440*t)+sin(2*PI*480*t))*0.28*gt(sin(2*PI*14*t),0)', 0.9);
ev('buzz', 'sin(2*PI*180*t)*gt(sin(2*PI*9*t),0)*0.3', 0.5);
ev('alert', '(sin(2*PI*880*t)*gt(sin(2*PI*5*t),0))*0.35', 0.6);
ev('chime', '(sin(2*PI*523.25*t)*exp(-t*3)+gt(t,0.12)*sin(2*PI*659.25*(t-0.12))*exp(-(t-0.12)*3)+gt(t,0.24)*sin(2*PI*783.99*(t-0.24))*exp(-(t-0.24)*3)+gt(t,0.36)*sin(2*PI*1046.5*(t-0.36))*exp(-(t-0.36)*2.5))*0.3', 1.8);
ev('error', '(sin(2*PI*220*t)+sin(2*PI*233*t))*exp(-t*6)*0.35', 0.5);
noise('rustle', 0.35, 'highpass=f=2500,afade=t=in:d=0.04,afade=t=out:st=0.1:d=0.25,volume=0.9', 'white');
console.log('sfx:', fs.readdirSync(out).join(' '));
