# Delivery loop

Source of truth: [router](../../skills/chaos-engine/SKILL.md#check-and-deliver), [overview](../../guides/overview.md).

Work is researched, planned, implemented, verified, reviewed, and learned. A pending check is not done.

```mermaid
flowchart LR
    accTitle: Delivery loop
    accDescr: A task moves from research through plan, implement, verify, review, and a learning record.
    Research[Research] --> Plan[Plan]
    Plan --> Implement[Implement]
    Implement --> Verify[Verify]
    Verify --> Review[Review]
    Review --> Learn[Learn]
```

Hook hosts run the guard from SessionStart. Hookless hosts run `tool.py entry` and record the same receipts.

## Next steps

- [How ChaosEngine thinks](how-chaosengine-thinks.md)
- [Choose a workflow](../how-to/choose-a-workflow.md)
