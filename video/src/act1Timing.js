// Act 1 choreography timings (seconds on the Act 1 timeline). Shared by the Remotion scene, the SFX cue sheet and the music.
// Everything is derived from the VO: each station lands on the words that name it, so the picture follows the sentence.
import { phraseSec } from './voTime.js';

export const XS = [251, 603, 955, 1307, 1659]; // station centre x: inbox, sheet, phone, licences, competitor alert
export const IDLE_POSE = ['juggling', 'juggling', 'phone', 'juggling', 'phone'];
export const DASH_PRE = 8; // anticipation frames
export const DASH_LEN = 14; // frames

/**
 * @param T timing.json   @param script script.json
 * station index: 0 inbox, 1 sheet, 2 phone, 3 licences, 4 alert.
 * Order of visits follows the VO: inbox (hook), sheet ("price sheet"), inbox again ("inbox is at forty-seven"), phone, licences, alert.
 */
export function act1Times(T, script) {
  const fps = T.fps;
  const sc = (id) => T.scenes.find((s) => s.id === id);
  const I = sc('a1-intro').frames / fps;
  const mid = sc('a1-mid').frames / fps;
  const M = I + mid;
  const endSec = sc('a1-end').frames / fps;
  const m = (phrase) => I + phraseSec(T, script, 'a1-mid', phrase);
  const pre = (DASH_PRE + DASH_LEN + 3) / fps;
  // never closer together than a dash needs
  const visitsRaw = [
    { st: 0, t: 1.7 },
    { st: 1, t: m('Their price sheet') },
    { st: 0, t: m('My inbox') },
    { st: 2, t: m('A vendor is on the phone') },
    { st: 3, t: m('The licence scans') },
    { st: 4, t: m('a competitor') },
  ];
  const visits = [];
  visitsRaw.forEach((v, i) => visits.push({ ...v, t: i === 0 ? v.t : Math.max(v.t, visits[i - 1].t + 1.25) }));
  const stations = [0, 1, 2, 3, 4].map((st) => visits.find((v) => v.st === st).t); // first visit = card pop
  const buried = M + 0.2;
  const t5 = visits[visits.length - 1].t;
  // frantic back-and-forth between the last station and the avalanche
  const rainWps = [
    { t: Math.min(t5 + 1.2, buried - 1.9), x: 1300, pose: 'phone' },
    { t: Math.min(t5 + 2.3, buried - 0.95), x: 640, pose: 'juggling' },
  ].filter((w) => w.t > t5 + 0.9);
  const inboxFull = visits[2].t + (phraseSec(T, script, 'a1-mid', 'forty-seven') - phraseSec(T, script, 'a1-mid', 'My inbox'));
  const freeze = M + phraseSec(T, script, 'a1-end', 'eighteen') - 0.1;
  return {
    I, M, stations, visits, pre, dashStart: visits.map((v, i) => (i === 0 ? v.t - 1.05 : v.t - pre)), rainWps,
    notesStart: stations[2] + 0.4, inboxFull, buried, freeze: Math.max(freeze, buried + 1.0), end: M + endSec,
  };
}
