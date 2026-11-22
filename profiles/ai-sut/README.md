# AI system under test

On-demand profile. The installer does not copy it with the portable distribution, and it does not start a paid or live model campaign.

Use it when the subject under test is an AI system and the ordinary functional card is not enough. The checks below are names and pass rules. They are not quotations of the standards.

## ISO/IEC TR 29119-11

Testing of AI systems. A check names the input distribution it claims to represent. A single happy-path prompt is not a sample of that distribution.

## ISO/IEC TS 42119-2

Testing of AI systems, part 2. Record the model identifier, version, and sampling settings next to the result. A result with no sampling record is not comparable to the next run.

## ISTQB CT-AI v2.0

- Metamorphic relations: where there is no single expected value, state the relation that must hold when the input changes. A failed relation fails the check.
- Statistical pass criteria: a rate needs a stated threshold and the number of trials. One success is not a rate.
- Bias and robustness: include a shift the system should survive, and a group or slice the result must not systematically miss. Name the slice. Do not treat a high average as proof that every slice passed.
- Calibrated LLM-judge: a model may score another model's output only when a human sample has checked that judge on this task. An uncalibrated judge is a note, not a pass.

Deterministic gates for these rules live in `runtime/sdlc_flows.py` and `experiments/harness-ab/score.py` (`ct_genai_metrics`). They do not call a model.
