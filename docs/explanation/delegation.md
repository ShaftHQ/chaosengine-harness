# Delegation

Source of truth: [delegation ladder](../../skills/chaos-engine/SKILL.md#delegation-ladder), [roles](../../references/roles.md).

The router owns the ladder. This picture only names the rungs. It does not restate the rule.

```mermaid
flowchart LR
    accTitle: Delegation ladder names
    accDescr: The rungs are named Free, Brief, Ask, Paid, and Stay. The router owns the rule text.
    Free[Free] --> Brief[Brief]
    Brief --> Ask[Ask]
    Ask --> Paid[Paid]
    Paid --> Stay[Stay]
```

Roles are orchestrator, implementer, reviewer, tester, and mechanical-helper. The orchestrator plans and verifies. The implementer takes one bounded spec.

## Next steps

- [Choose a workflow](../how-to/choose-a-workflow.md)
- [Keywords glossary](../reference/keywords.md)
