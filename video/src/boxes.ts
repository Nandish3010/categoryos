import { Callout, Focus, MARKS, Src } from './components/AppParts';

type B = { x: number; y: number; w: number; h: number };

/** On-screen box of an element, measured by the capture step (so rings follow the live layout). Falls back to the replay layout. */
export const bx = (src: Src, name: string, fb: B): B => ((MARKS[src] as unknown as { boxes?: Record<string, B> }).boxes?.[name] ?? fb);

export const ring = (b: B, color: string, pad = 8): Callout => ({ x: b.x - pad, y: b.y - pad, w: b.w + 2 * pad, h: b.h + 2 * pad, color });

/** A focus rectangle centred on b, at least minW x minH. */
export const focusOn = (b: B, minW = 880, minH = 240): Focus => {
  const w = Math.max(b.w + 120, minW), h = Math.max(b.h + 80, minH);
  const cx = b.x + b.w / 2, cy = b.y + b.h / 2;
  return { x: Math.max(0, cx - w / 2), y: Math.max(0, cy - h / 2), w, h };
};

export const union = (a: B, b: B, pad = 14): B => {
  const x = Math.min(a.x, b.x) - pad, y = Math.min(a.y, b.y) - pad;
  return { x, y, w: Math.max(a.x + a.w, b.x + b.w) + pad - x, h: Math.max(a.y + a.h, b.y + b.h) + pad - y };
};

// Replay-layout fallbacks (recorded video pixels)
export const FB = {
  banner: { x: 480, y: 332, w: 880, h: 71 },
  say: { x: 480, y: 422, w: 880, h: 131 },
  condOffer: { x: 940, y: 725, w: 200, h: 20 },
  gap: { x: 930, y: 570, w: 430, h: 30 },
  gstCard: { x: 1658, y: 125, w: 220, h: 40 },
  priceRow: { x: 496, y: 262, w: 848, h: 34 },
  fssaiRow: { x: 496, y: 640, w: 850, h: 46 },
  proteinRow: { x: 498, y: 436, w: 846, h: 36 },
};
