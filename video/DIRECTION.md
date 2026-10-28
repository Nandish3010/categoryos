# CategoryOS demo: direction

**Logline.** A category manager drowns in one vendor's paperwork, then an agent that checks its own numbers hands her the week back.

## Beat sheet (emotional arc: frantic -> relief -> delight)

| Act | Time | Feeling | What the audience should think |
|---|---|---|---|
| 1 The chaos | 0:00-0:35 | Frantic, funny | "I have lived this day." Hook in 3 s: a clock reads 9:00 AM, Meera sprints into frame, the inbox counter is already racing |
| 2 Team, then CategoryOS takes over | 0:35-2:35 | Relief, then respect | The button slam is the exhale. Then three proofs: it refuses a trap offer, corrects its own number, catches a lapsing licence |
| 3 Her week, back | 2:25-3:00 | Delight, calm | Red calendar melts into green. Meera finally sits down with coffee, waves, URL |

## Shot list and transitions

Act 1 cuts every 1-2 s. All speed is carried by Meera and the stations; the camera whip-pans with her.

1. Wide: clock 9:00 AM spinning, Meera dashes in (anticipation crouch, then dash). Cut on her motion -> **whip pan** (horizontal motion blur) ->
2. Medium: inbox station pops (overshoot spring), counter races to 47. **Match cut** on the counter number ->
3. Medium: spreadsheet ("Rs.399/-", blank costs) -> 4. phone rings ("+20% marketing if you sell 2,000 units!") -> 5. licence scans -> 6. red competitor alert. Each station is 1.4-1.8 s; cuts are on Meera's footfall.
7. Juggling and phone poses cut in; sticky notes rain; "time spent" counter ticks.
8. Close-up: buried in paper. **Freeze** frame, caption "about 18 hours. One vendor." with "research estimate" tag.

Act 2:
8b. "Meet the team" (v3): warm-to-neutral backdrop, Meera walks in from the left, a builder card springs up, she turns to camera on "And I'm the category manager", high-five and sparkle burst, then she walks off right. 9. She dashes back in from the right, jumps, slams the glowing button -> **zoom-through** into the app (screen scales from the button position).
10. App in a tilted browser frame (perspective, 6 deg). Zoom-in callouts on key numbers: wide to close-up to wide. Numbers hold at least 2.5 s.
11. Meera is persistent and WALKS (v3, `components/MeeraWalker.tsx`): along a floor beside the tilted frame she paces with the phone (m1), leans in to the flagged dates (m2), carries a wobbly paper stack that the agent takes off her plate sheet by sheet (m3), hands task cards to the frame (m4). She walks in from the side she left and walks out at the end; no pop-ins.
12. Montage: 7 shots of 1.6-2 s with **whip pans** and a bottom-left caption chip per shot.

Act 3:
13. Week calendar: wall-to-wall red/orange blocks; a third dissolve to green (staggered, 40 ms apart). 14. Relaxed coffee pose, then waving. 15. Model strip, URL.

## Colour script

- Act 1 warm and stressed: background shifts #1a0f0c to #2a1310, accent red #F87171 and orange #F5A962, vignette, slight desaturation of Meera's backdrop glow.
- Act 2 cool product: deck bg #0F1117, surface #171A23, accent blue #6EA8FE; highlight rings in yellow #F5C542 (attention) and green #4ADE80 (verified).
- Act 3 calm green: bg drifts to #0c1a14, accent green #4ADE80, one orange sneaker flash for continuity.
- Colour changes happen on the act transitions only (the button slam, the calendar melt), never mid-scene.

## Typography (kinetic captions)

- Space Grotesk 700 for captions and numbers; DM Sans 500 for secondary text. Minimum 28 px at 1080p; hero numbers 120-220 px.
- Captions: lower third, max 2 lines, 44 px, #EDEEF2 on a 72 % #0F1117 plate with a 6 px colour bar (red/blue/green by act). Words enter with 40 ms stagger, 14 px rise, ease-out-cubic, exit as one block with a 6-frame fade.
- Every VO line has a caption (viewers with sound off). Modelled/estimated figures carry a small tag chip ("research estimate", "modelled") at 28 px.
- Safe margins: 96 px left/right, 72 px top/bottom.

## Motion principles (applied to Meera and UI)

- Easing: entrances ease-out (springs: damping 12-14, stiffness 120-180, mass 0.6-0.9 for overshoot), exits ease-in, never linear except spin/clock.
- Anticipation: 6-frame crouch (squash 0.9 y / 1.08 x, lean back) before every dash. Stretch 1.1 y / 0.94 x at peak speed. Squash on landing (0.88 y), recover with a damped spring.
- Follow-through and overlapping action: the tablet-side and hair are not separate assets, so the whole figure carries a secondary rotation lagging the body by 3 frames, plus a motion-blur echo trail (2 ghost copies, lagged, lower opacity) and speed lines.
- Arcs: bounce uses an absolute-sine arc, not a linear hop. Slow-in/slow-out on every pop-in.
- Staging and exaggeration: one idea per shot; callout rings pulse once, not forever. Stagger lists by 4-6 frames.

## Pacing rules

- Act 1: no shot over 2 s. Act 2 hero moments: hold each key number at least 2.5 s (the number, then the explanation). Montage 1.6-2 s per shot.
- Scene durations come from the VO lengths (video/vo/<scene>.wav wins over TTS); cut to the VO rhythm: each cut lands on a sentence or clause boundary.
- First 3 s hook: clock + sprint + SFX tick; no logo card.

## Audio plan

- VO: Kokoro-82M (local neural TTS, `video/tools/tts.sh`), one file per scene, replaceable by video/vo/<scene>.wav. Scenes are VO + 0.4 s, so there is speech under almost every second; the only deliberate silences are the buried freeze and the slam.
- SFX synthesised with ffmpeg (no sampled audio): tonal pops, ticks, blips, ding/chime, phone ring, thud/slam. Noise is limited to three short swishes (avalanche, slam zoom, red-to-green melt).
- Music: composed in code (`scripts/music.mjs`), about 110 BPM, original. Act 1 busy and minor-leaning (16th hats, plucked arpeggio); the avalanche drops it to a hush; a riser and the drop land on the slam; Act 2 is a driving four-on-the-floor groove kept sparse under dense VO, with a lead motif on the hero numbers; Act 3 is a warm resolve with a final hit on the URL.
- Mix: music sidechain-ducked about 9 dB under speech, master about -14 LUFS, true peak -1 dBFS.

## Honesty

Only figures given in the brief or read from the live app and API. Modelled/estimated figures are labelled. MEASURED_BASELINE = null in src/config.ts switches the captions when the user fills it.
