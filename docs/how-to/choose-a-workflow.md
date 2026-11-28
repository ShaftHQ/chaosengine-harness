# Choose a workflow

Source of truth: [execution workflows](../../references/execution-workflows.md).

Say the phrase that matches the shape of the work. The glossary owns the words. This page only helps you pick.

```mermaid
flowchart TD
    accTitle: Workflow selection
    accDescr: A tight change stays solo. The default is one implementer. Parallel implementers are an owner opt-in.
    A[How wide is the change?] --> B{One coupled edit?}
    B -->|yes| C[SOLO]
    B -->|no| D{File-disjoint units?}
    D -->|no| E[ORCHESTRATOR + SINGLE IMPLEMENTER]
    D -->|yes, owner asks| F[ORCHESTRATOR + PARALLEL IMPLEMENTERS]
```

Say `SOLO` for one tightly coupled change. Say `work as orchestrator` for the default single implementer. Add `parallelize` only when the owner wants file-disjoint units.

## Next steps

- [Keywords glossary](../reference/keywords.md)
- [How ChaosEngine thinks](../explanation/how-chaosengine-thinks.md)
