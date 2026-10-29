import React from 'react';
import { Img, staticFile } from 'remotion';

export type Pose = 'waving' | 'pointing' | 'thinking' | 'celebrating' | 'running' | 'juggling' | 'buried' | 'imfine' | 'phone' | 'relaxed';

type Props = {
  pose: Pose;
  /** x centre and y of the feet (px) */
  x: number;
  y: number;
  h: number;
  rot?: number;
  sx?: number;
  sy?: number;
  flip?: boolean;
  opacity?: number;
  blur?: number;
  shadow?: boolean;
  z?: number;
  glow?: string;
};

export const Meera: React.FC<Props> = ({ pose, x, y, h, rot = 0, sx = 1, sy = 1, flip = false, opacity = 1, blur = 0, shadow = true, z = 5, glow }) => {
  const sw = pose === 'imfine' ? h * 1.0 : pose === 'buried' ? h * 0.95 : h * 0.5;
  return (
    <>
      {shadow ? (
        <div style={{ position: 'absolute', left: x - sw / 2, top: y - 14, width: sw, height: 28, borderRadius: '50%', background: 'rgba(0,0,0,0.5)', filter: 'blur(10px)', opacity: opacity * 0.9, zIndex: z - 1 }} />
      ) : null}
      <div
        style={{
          position: 'absolute', left: x, top: y, height: h, width: 'max-content', zIndex: z, opacity,
          transform: `translate(-50%,-100%) rotate(${rot}deg) scale(${flip ? -sx : sx},${sy})`,
          transformOrigin: '50% 100%',
          filter: `${blur > 0.2 ? `blur(${blur}px) ` : ''}${glow ? `drop-shadow(0 0 26px ${glow})` : ''}`.trim() || undefined,
        }}
      >
        <Img src={staticFile(`meera/meera-${pose}.png`)} style={{ height: h, width: 'auto', display: 'block' }} />
      </div>
    </>
  );
};
