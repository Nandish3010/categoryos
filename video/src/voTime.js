// Pure helpers shared by the Remotion scenes, the cue sheet and scripts/vo.mjs: sentence splitting and "when is this phrase spoken".

/** Split a VO/caption string into sentences. Abbreviations like "a.m.," and URLs never split (a boundary needs whitespace after the mark). */
export function splitSentences(text) {
  return text.replace(/\s+/g, ' ').trim().split(/(?<=[.!?])\s+(?=[A-Z0-9])/).filter(Boolean);
}

/**
 * Seconds (from the start of the scene) at which `phrase` begins being spoken.
 * Uses the real per-sentence timing from timing.json and spreads characters evenly inside a sentence.
 * `phrase` is looked up in the VO text (the spoken spelling), so use e.g. "forty-seven", not "47".
 */
export function phraseSec(T, script, sceneId, phrase, nth = 0) {
  const sc = T.scenes.find((s) => s.id === sceneId);
  const vo = script.scenes.find((s) => s.id === sceneId).vo;
  const sents = splitSentences(vo);
  let seen = 0;
  for (let i = 0; i < sents.length; i++) {
    let from = 0;
    for (;;) {
      const at = sents[i].indexOf(phrase, from);
      if (at < 0) break;
      if (seen++ === nth) {
        const { a, b } = sc.sentences[i];
        return sc.voLead + a + ((b - a) * at) / sents[i].length;
      }
      from = at + 1;
    }
  }
  throw new Error(`phrase not found in ${sceneId}: ${phrase}`);
}

/** Local frame (inside the a2-slam scene) where the button goes down: as the name is spoken. */
export const slamLocalFrame = (T, script) => Math.max(62, Math.round(phraseSec(T, script, 'a2-slam', 'CategoryOS') * T.fps) + 4);

/** Seconds (from the start of the scene) at which sentence i starts / ends. */
export const sentenceSec = (T, sceneId, i, end = false) => {
  const sc = T.scenes.find((s) => s.id === sceneId);
  const { a, b } = sc.sentences[i];
  return sc.voLead + (end ? b : a);
};
