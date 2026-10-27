import React from 'react';
import { useCurrentFrame } from 'remotion';
import script from '../../script.json';
import { body, C, E, FPS, MARGIN_X, prog, sceneOf } from '../theme';

/** Split a VO line into short caption chunks (<= ~9 words), timed by character share of the spoken duration. */
export function chunksFor(sceneId: string): { text: string; a: number; b: number }[] {
  const sc = sceneOf(sceneId);
  const vo = (script.scenes.find((s) => s.id === sceneId)?.vo ?? '').replace(/\s+/g, ' ');
  const sentences = vo.match(/[^.!?]+[.!?]*/g)?.map((s) => s.trim()).filter(Boolean) ?? [];
  const chunks: string[] = [];
  for (const s of sentences) {
    const words = s.split(' ');
    if (words.length <= 9) { chunks.push(s); continue; }
    // break long sentences at clause marks nearest the middle
    let cur: string[] = [];
    for (const w of words) {
      cur.push(w);
      if (cur.length >= 5 && /[,:;]$/.test(w)) { chunks.push(cur.join(' ')); cur = []; }
      else if (cur.length >= 9) { chunks.push(cur.join(' ')); cur = []; }
    }
    if (cur.length) chunks.push(cur.join(' '));
  }
  const total = chunks.reduce((n, c) => n + c.length, 0);
  let t = sc.voLead * FPS;
  const span = sc.voSec * FPS;
  return chunks.map((text) => {
    const a = t;
    t += (text.length / total) * span;
    return { text, a, b: t };
  });
}

/** Burned-in captions for a scene's VO (local frame). Words rise in with a 1-frame stagger; chunk fades as one block. */
export const VoCaptions: React.FC<{ sceneId: string; accent?: string; bottom?: number }> = ({ sceneId, accent = C.blue, bottom = 70 }) => {
  const f = useCurrentFrame();
  const cs = React.useMemo(() => chunksFor(sceneId), [sceneId]);
  const cur = cs.find((c) => f >= c.a - 1 && f < c.b + 4);
  if (!cur) return null;
  const words = cur.text.split(' ');
  const out = 1 - prog(f, cur.b - 3, cur.b + 4, E.in);
  return (
    <div style={{ position: 'absolute', left: MARGIN_X, right: MARGIN_X, bottom, display: 'flex', justifyContent: 'center', opacity: out, zIndex: 50 }}>
      <div style={{ background: 'rgba(15,17,23,0.82)', borderLeft: `8px solid ${accent}`, borderRadius: 14, padding: '16px 30px', maxWidth: 1500, boxShadow: '0 10px 40px rgba(0,0,0,.45)' }}>
        <div style={{ fontFamily: body, fontWeight: 500, fontSize: 44, lineHeight: 1.22, color: C.text, display: 'flex', flexWrap: 'wrap', gap: '0 0.28em' }}>
          {words.map((w, i) => {
            const p = prog(f, cur.a + i * 1.2, cur.a + i * 1.2 + 7);
            return <span key={i} style={{ opacity: p, transform: `translateY(${(1 - p) * 14}px)`, display: 'inline-block' }}>{w}</span>;
          })}
        </div>
      </div>
    </div>
  );
};
