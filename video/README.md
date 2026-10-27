# CategoryOS demo video

A reproducible pipeline: the app is recorded with playwright-core (system Chrome), the film is composed in Remotion (React), the voiceover is `say -v Tara` unless you drop in your own, and every sound effect is synthesised with ffmpeg.

```
make video          # capture the app, draft VO, synth SFX, mix, render both cuts
make video-render   # same without re-capturing (after editing scenes or swapping VO)
```

Outputs (git-ignored): `video/out/categoryos-demo.mp4` (about 3:00, 1920x1080, 30 fps), `video/out/categoryos-x-30s.mp4` (30 s, 1080x1080) and review stills in `video/out/stills/`.

The creative brief is in [DIRECTION.md](DIRECTION.md).

## Layout

| Path | What |
|---|---|
| `capture/` | `capture.mjs` flows (V001 decide/verifier/levers/docs, V001 label check, V002 intake and live call, Run pages, impact). `lib.mjs` has the CDP screencast recorder, smooth cursor and click ripple. `probe.mjs` / `explore.mjs` are selector-discovery helpers. `BASE_URL=... node capture/capture.mjs v2` re-records one flow, e.g. against a live-mode deploy. |
| `script.json` | VO line per scene and the minimum scene length. Scene durations come from the VO lengths. |
| `scripts/vo.mjs` | TTS draft per scene into `out/vo/`, writes `src/timing.json`. **`video/vo/<scene>.wav` wins over TTS.** |
| `scripts/sfx.mjs`, `scripts/mix.mjs` | ffmpeg-synthesised SFX, cue sheet in `src/cues.js`, VO + SFX (+ optional music) mixed and loudness-normalised. |
| `src/` | Remotion project: `scenes/Act1` (chaos), `Slam`, `Act2` (app scenes), `Act3` (week back, close), `XCut` (30 s cut). |
| `assets/meera/` | Presenter cut-outs. `tools/gen.py` makes new poses with Muse Image, `tools/cutout.py` cuts them out. |

## Replacing things

- **Your own voice:** record each scene to `video/vo/<scene-id>.wav` (ids are in `script.json`, e.g. `m1-call.wav`) and run `make video-render`. Scene lengths follow your recording.
- **Music:** put a file at `video/audio/music.mp3`. It is ducked about 18 dB under the voice. No file means no music.
- **Measured baseline:** `MEASURED_BASELINE` in `src/config.ts` is `null`, so captions say "research estimate". Set it to `{ hoursPerVendor, minutesWithCos }` and the Act 1 caption and tag switch to "measured".
- **Live runs instead of the replay:** `BASE_URL=<live deploy> make video`. Callout rectangles in `src/scenes/Act2.tsx` are in recorded-video pixels; re-check them if the layout differs.

## Honesty

Figures on screen are either from the brief (18 h research estimate, 47 unread, P(hit) < 0.1%, 250 units, 60.5%, 27.1%, 22%, 198/200, 36 issues / 32 fixes) or read from the live app (the verifier card, FSSAI and label mismatches, price list, and `GET /api/impact` which is saved to `src/data/impact.json`). The week calendar and the corner counter are labelled "modelled".
