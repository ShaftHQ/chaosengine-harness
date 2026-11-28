# Safety gates

Source of truth: [ethics card](../../companions/ethics-card.md), [router](../../skills/chaos-engine/SKILL.md#check-and-deliver).

Hook hosts run the guard from the host lifecycle. Hookless hosts run `tool.py entry` and record the same receipts.

```mermaid
flowchart TD
    accTitle: Hook and hookless entry
    accDescr: A hook host enters through SessionStart. A hookless host enters through tool.py entry. Both reach the guard.
    Hook[Hook host] --> Start[SessionStart]
    Plain[Hookless host] --> Entry[tool.py entry]
    Start --> Guard[Guard]
    Entry --> Guard
```

The ethics floor blocks person-only exams and live answer feeds. The delete guard and the secret guard stay on unless the owner turns a documented switch off.

## Next steps

- [How ChaosEngine thinks](how-chaosengine-thinks.md)
- [Status codes](../reference/settings.md)
