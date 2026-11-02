# VERIFY-DROPPED (2026.11.01 inputs already shipped)

- Designer L1–L4 / voice speaker+ASR+unk+proper-nouns → L93/L96 (`design_qc.py tts`)
- Designer L8 cap-2 → `design_fix_loop.py` (L72)
- Designer L9 / Writer stop-all / E1 peer cancel → L90 + E1 `evaluate_stop_scope`
- Writer dropped-item verify → L86 `verify_dropped.py`
- Writer no-probe-live → L75 `no_probe_live.py`
- C4 dropped-item board owner → L86 (`board owner` marker in `verify_dropped.py`)
- L95 installer path → L100 + pr-gate `packs/**`
