# First install

Source of truth: [INSTALL.md](../../INSTALL.md).

Run the one-liner from the project root. The installer pins the commit it used. Then run doctor if you want a later health check.

```mermaid
flowchart LR
    accTitle: Install architecture
    accDescr: The source tree installs an overlay, and hosts read that overlay.
    Source[Source tree] --> Overlay[Project overlay]
    Overlay --> Hosts[Host adapters]
```

You should see a receipt, host files, and no usage telemetry. ChaosEngine sends no usage data.

## Next steps

- [Settings reference](../reference/settings.md)
- [Choose a workflow](../how-to/choose-a-workflow.md)
