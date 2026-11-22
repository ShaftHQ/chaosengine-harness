---
name: word-timed-explainer
description: Use when a procedural explainer's picture must follow local word timings of the narration, on one canvas, with its own layout per aspect.
---

# D24 Word-timed explainer

## Use when

The picture is a procedural explainer whose cues move with the spoken words.
Load this card only for that opt-in. It does not replace the technical-video
pipeline, D08 motion tokens, D17 voice production, or the D21 arc.

## Rules

- The picture timeline comes from local word timings of the narration. Do not
  hand-time cues against a clock that can drift from the take.
- Replacing one line's take and rebuilding moves that line's picture cue.
  Other lines stay put unless their timings changed.
- A scratch voice is for timing only and is never shipped. The shipped
  narration is the approved human take or the approved D17 voice, named in
  the manifest. Keep the scratch take out of delivery.
- One canvas. Frames are deterministic: the same timings and the same scene
  code produce the same frames. No random seed and no network at render.
- Captions use the same word timings as the picture. File rules stay on D18.
- Review is measured: the word-timing gate below, then the delivery checks
  the pipeline already names. This card does not render a pilot.
- 16:9 is laid out as 16:9. 9:16 is laid out on its own. Never crop one master
  to invent the other.

## Workflow

1. Lock the narration lines (D01, D21). Mark which lines drive a picture cue.
2. Time those lines locally. A scratch synthesis may supply the timings. It
   is not the shipped voice.
3. Write `timings.json`: an object with a `lines` array. Each line has
   non-empty `text`, a `words` array of `{text, start, end}` with `end`
   greater than `start`, a `picture` string, the `take` file name, the
   spoken `word` that cue hits, and `overflow: false` only after a measured
   fit. `"draft": true` is a timing pass, not a master.
4. Rebuild the one canvas from that file. Change a line by replacing its
   take, re-timing that line, and rebuilding so only that cue moves.
5. Lay out 16:9 and 9:16 as two compositions. Caption from the same words.
6. Run `wordtiming`, `wordcue`, and `wordreview`, then a measured pass on
   frames that were actually rendered. Do not treat this card as that render.

## Verify

- `design_qc.py wordtiming timings.json` exits 0. An empty file, missing
  `lines`, a line with no words, or a line with no picture exits non-zero
  and prints a named reason (`empty-file`, `missing-lines`, `no-words`,
  `no-picture`).
- `design_qc.py wordcue timings.json` exits 0 only when every line names a
  take, a shipped take is not `*.scratch.*`, `overflow` is false, and `word`
  is one of that line's timed words. Missing evidence fails closed
  (`missing-take`, `scratch-take`, `overflow-text`, `cue-without-word`).
  A shipped file also fails `missing-whisper` unless this add-on contains
  the pinned whisper.cpp binary. A draft may omit that binary and may name
  a scratch take. The gate reads the timing file. It does not run a model
  and it does not call a second ASR stack.
- `design_qc.py wordreview timings.json` exits 0 only when every line is at
  most 3.5 words/s, the log reports wpm against 140–160, each `cue_at` is
  within 3 frames or 150 ms of its spoken word, every `cues` name is still
  spoken, `16:9` and `9:16` are laid out (not cropped) with overflow and
  overlap false, the hero box sits inside both frames or `hero_waiver` says
  why there is no hero, and `score_payoff` has the voice louder than the
  score (`vo_db` > `score_db`) or `score_waiver` says why. Missing numbers
  fail closed. A `retake` block (`index`, `before` lines) fails when that
  line's cue did not follow the new word time or any other line moved.
- The manifest names the shipped voice and states that the scratch take was
  not shipped. The line `take` is that name.
- 16:9 and 9:16 frames, when a render exists, show their own layout, not a
  crop. No pilot is claimed here.

## Sources

Patterns re-expressed from cth9191/animate (MIT),
https://github.com/cth9191/animate at
7e5eb56feb2dd573f890e1b7b34748af43d58263, studied 2026-11-15.
No files copied. No pilot was rendered for this card.
