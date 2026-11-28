# Opt in or out

A bool whose default is on is an opt-out. A bool whose default is off is an opt-in. The settings reference lists the flag, the env var, and the TOML key.

```mermaid
flowchart LR
    accTitle: Opt-in and opt-out
    accDescr: Default-on switches turn off with a flag. Default-off switches turn on with a flag.
    On[Default on] --> OffFlag[Opt out]
    Off[Default off] --> OnFlag[Opt in]
```

Say `stop caveman` or `stop ponytail` to drop a companion for this session. `normal mode` drops both. Those phrases are in the [keywords glossary](../reference/keywords.md).

## Next steps

- [Configure](configure.md)
- [Keywords glossary](../reference/keywords.md)
