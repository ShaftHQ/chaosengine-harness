# Memory and retrieval

Source of truth: [retrieve-first](../../references/retrieve-first.md).

Retrieve before a broad search. Memory, MemPalace, and Graphify answer different questions. The file on disk still wins when they disagree.

```mermaid
flowchart TD
    accTitle: Retrieve before search
    accDescr: A broad search records a retrieve receipt. A cheap read of a named file does not wait.
    Q[Question] --> R{Broad search?}
    R -->|yes| Store[Memory, MemPalace, or Graphify]
    R -->|named file| File[Read the file]
    Store --> File
```

Record `retrieve: used`, `retrieve: skipped`, or `retrieve: exempt(harness)`.

## Next steps

- [How ChaosEngine thinks](how-chaosengine-thinks.md)
- [Delivery loop](delivery-loop.md)
