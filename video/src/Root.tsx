import React from 'react';
import { AbsoluteFill, Composition, Sequence } from 'remotion';
import { Act1 } from './scenes/Act1';
import { Slam } from './scenes/Slam';
import { M1Scene, M2Scene, M3Scene, M4Scene } from './scenes/Act2';
import { CloseScene, WeekScene } from './scenes/Act3';
import { XCut, X_FRAMES } from './scenes/XCut';
import { FPS, sceneOf, T } from './theme';

const S = (id: string, C: React.FC) => {
  const s = sceneOf(id);
  return <Sequence key={id} from={s.start} durationInFrames={s.frames} name={id}><C /></Sequence>;
};

export const Demo: React.FC = () => {
  const a1 = ['a1-intro', 'a1-mid', 'a1-end'].map(sceneOf);
  const a1Frames = a1.reduce((n, s) => n + s.frames, 0);
  return (
    <AbsoluteFill style={{ background: '#0F1117' }}>
      <Sequence from={a1[0].start} durationInFrames={a1Frames} name="act1"><Act1 /></Sequence>
      {S('a2-slam', Slam)}
      {S('m1-call', M1Scene)}
      {S('m2-verifier', M2Scene)}
      {S('m3-vision', M3Scene)}
      {S('m4-run', M4Scene)}
      {S('a3-week', WeekScene)}
      {S('a3-close', CloseScene)}
    </AbsoluteFill>
  );
};

export const Root: React.FC = () => (
  <>
    <Composition id="Demo" component={Demo} durationInFrames={T.total} fps={FPS} width={1920} height={1080} />
    <Composition id="XCut" component={XCut} durationInFrames={X_FRAMES} fps={FPS} width={1080} height={1080} />
  </>
);
