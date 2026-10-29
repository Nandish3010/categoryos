# CategoryOS demo video

A reproducible pipeline: the app is recorded with playwright-core (system Chrome), the film is composed in Remotion (React), the voiceover is Kokoro-82M (local neural TTS) unless you drop in your own, the sound effects are synthesised with ffmpeg and the music bed is composed in code (`scripts/music.mjs`).

```
make video          # capture the app, voiceover, synth SFX, compose music, mix, render both cuts
make video-render   # same without re-capturing (after editing scenes or swapping VO)
```

Outputs (git-ignored): `video/out/categoryos-demo.mp4` (v5: 2:57; v4 was 2:42, 1920x1080, 30 fps), `video/out/categoryos-x-30s.mp4` (30 s, 1080x1080) and review stills in `video/out/stills/`.

The creative brief is in [DIRECTION.md](DIRECTION.md).

## Layout

| Path | What |
|---|---|
| `capture/` | `capture.mjs` flows (V001 decide/verifier/levers/docs, V001 label check, V002 intake and live call, Run pages, impact). `lib.mjs` has the CDP screencast recorder, smooth cursor and click ripple. `probe.mjs` / `explore.mjs` are selector-discovery helpers. `BASE_URL=... node capture/capture.mjs v2` re-records one flow, e.g. against a live-mode deploy. |
| `script.json` | Per scene: `vo` (spoken spelling), `caption` (written properly, shown on screen), `emph` (stress words for the `say` fallback), `minSec`, optional `tailSec`. Top level: `voice`/`speed` (Kokoro), `sayVoice`/`rate` (fallback). Scene durations are VO + 0.4 s (0.15 s lead, 0.25 s tail). |
| `scripts/vo.mjs` | Voiceover per scene into `out/vo/`; writes `src/timing.json` (scene frames, per-sentence timing). **`video/vo/<scene>.wav` wins over TTS.** See *Voice* below. |
| `scripts/live-asr.mjs`, `src/data/live_asr.json` | v5: the ONE live call to `muse-voice-transcribe-1.0` (vendor offer synthesised with Kokoro `am_michael` into `assets/live/vendor-offer.wav`; the response, latency and date are the committed fixture the `m1-asr` scene shows). Not re-run by `make video`; `FORCE=1` calls again (a fraction of a cent). A scene with `clip` in `script.json` appends that wav to its voice file. The `rules` capture flow (`capture.mjs rules`) records the plain-English rule as Arjun, then Meera's approval, on a fresh visitor sandbox. |
| `scripts/sfx.mjs`, `scripts/music.mjs`, `scripts/mix.mjs` | ffmpeg-synthesised SFX (tonal pops, ticks and chimes; three noise swishes at most), the composed music bed (`audio/music.wav`), cue sheet in `src/cues.js`. `mix.mjs` ducks the music under the voice and masters to -14 LUFS. `scripts/audio-report.mjs` prints levels, duck depth and VO gaps. |
| `src/voTime.js`, `src/act1Timing.js` | "When is this phrase spoken" helpers. Scenes, captions, SFX cues and music cut on the words, so changing the script or the voice re-times the film. |
| `src/` | Remotion project: `scenes/Act1` (chaos, the problem), `Team` (meet the team), `Slam`, `Act2` (app scenes), `Act3` (week back, close), `XCut` (30 s cut). `components/MeeraWalker.tsx` is the walk system (beats of `{at, x, pose, text?}`; she walks, idles and never pops in) and `components/WalkerProps.tsx` the paper stack, thrown documents, task cards and sparkles. |
| `assets/meera/` | Presenter cut-outs. `tools/gen.py` makes new poses with Muse Image, `tools/cutout.py` cuts them out. |

## Replacing things

- **Team members and photos:** edit the `TEAM` list in `src/config.ts` (`{ name, role, photo }`); put an optional photo in `video/assets/team/` and set `photo: 'nandish.jpg'` (it is served via `staticFile('team/nandish.jpg')`; with `photo: null` the card shows an initials avatar). The "Meet the team" voiceover and caption live in `script.json` (`a2-team`).
- **Your own voice:** record each scene to `video/vo/<scene-id>.wav` (ids are in `script.json`, e.g. `m1-call.wav`) and run `make video-render`. Scene lengths follow your recording (sentence timing is estimated by character share).
- **Voice engine:** see *Voice* below.
- **Music:** `make video-render` composes `audio/music.wav` (about 110 BPM, original, additive sines plus a synthesised kick, clap and hats; arrangement follows the scene timing). To use your own track instead, delete `audio/music.wav` and put `audio/music.mp3` there; `mix.mjs` takes either (the `.wav` wins). The mix ducks music about 9 dB under speech. No file means no music.
- **Measured baseline:** `MEASURED_BASELINE` in `src/config.ts` is `null`, so captions say "research estimate". Set it to `{ hoursPerVendor, minutesWithCos }` and the Act 1 caption and tag switch to "measured".
- **Live runs instead of the replay:** `BASE_URL=<live deploy> make video`. Callout rectangles in `src/scenes/Act2.tsx` are in recorded-video pixels; re-check them if the layout differs.

## Voice

Engine order, per scene: `video/vo/<scene>.wav` (your recording), else `video/tools/tts.sh "<text>" <out.wav>` if that file exists, else macOS `say -v Tara` (sentence by sentence, with rate, pitch and emphasis tweaks, plus ffmpeg presence/de-ess/room polish).

`tts.sh` ships with **Kokoro-82M** (Apache-2.0, runs locally). Setup once:

```
cd video/tools && uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python kokoro==0.9.4 soundfile
```

The model downloads from Hugging Face on first use. `tts.sh` uses `video/tools/.venv`, else `$KOKORO_VENV`, else the main checkout's venv. Choose the voice with `"voice"` in `script.json` (`af_heart` default, `af_bella`, `bf_emma`, ...; `"speed"` too) and run `make video-render`. Kokoro output gets only a light polish (high-pass, gentle compression, loudness); `kokoro_tts.py` renders each sentence separately, trims the model's own padding, adds a 140 ms breath between sentences and writes `<out>.json` with sentence start/end times so captions and cuts land on the real sentence boundaries.

To drop in another neural TTS, replace `tools/tts.sh` with anything that takes `(text, out.wav)` (any sample rate; optionally write `<out.wav>.json` as `[{"a":0,"b":2.1}, ...]`, one entry per sentence). No code change needed. `VO_ENGINE=say` forces the Tara fallback.

## Honesty

Figures on screen are either from the brief (18 h research estimate, 47 unread, P(hit) < 0.1%, 250 units, 60.5%, 27.1%, 22%, 198/200, 36 issues / 32 fixes) or read from the live app (the verifier card, FSSAI and label mismatches, price list, and `GET /api/impact` which is saved to `src/data/impact.json`). The week calendar, its per-module blocks (`modules[].saved_pct` from `/api/impact`) and the corner counter are labelled "modelled".
