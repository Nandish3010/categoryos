// Act 1 choreography timings (seconds on the Act 1 timeline). Shared by the Remotion scene and the SFX mixer.
export const XS = [251, 603, 955, 1307, 1659]; // station centre x
export const IDLE_POSE = ['juggling', 'juggling', 'phone', 'juggling', 'phone'];
export const DASH_PRE = 8; // anticipation frames
export const DASH_LEN = 14; // frames

export function act1Times(introSec, midSec, endSec) {
  const I = introSec;
  const M = I + midSec;
  const stations = [1.7, I + 0.5, I + 2.9, I + 5.3, I + 7.7];
  const pre = (DASH_PRE + DASH_LEN + 3) / 30;
  const dashStart = stations.map((t, i) => (i === 0 ? t - 1.05 : t - pre));
  const t4 = stations[4];
  // frantic back-and-forth while the notes rain
  const rainWps = [
    { t: t4 + 1.5, x: 640, pose: 'juggling' },
    { t: t4 + 3.0, x: 1300, pose: 'phone' },
    { t: t4 + 4.5, x: 960, pose: 'juggling' },
  ];
  return { I, M, stations, dashStart, rainWps, notesStart: stations[2] + 0.4, buried: M + 0.7, freeze: M + 2.1, end: M + endSec };
}
