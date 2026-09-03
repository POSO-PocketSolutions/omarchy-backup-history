<p align="center">
  <img src="assets/logo-readme.png" width="120" alt="Backup History logo">
</p>

<h1 align="center">Backup History for Omarchy</h1>

<p align="center">
  A status panel for systemd backup services in the Omarchy bar.
</p>

<p align="center">
  <img src="preview.png" width="360" alt="Backup History panel in the Omarchy bar">
</p>

## Features

- Theme-aware backup logo in the bar.
- At-a-glance health and the latest successful backup.
- Four-week, GitHub-style history of daily runs.
- Run a backup on demand through Polkit.
- Follow the service logs in a terminal.

Backup results are read from systemd's structured journal events, so the plugin never touches your backup credentials.

## How it works

The plugin is **backup-tool agnostic**. It knows nothing about restic, borg, rsync, or any specific tool — it only speaks *systemd*. Anything you can run as a systemd oneshot service works, and the journal is the single source of truth.

```mermaid
flowchart LR
    B["Your backup tool<br/>restic · borg · rsync · custom"] --> S["systemd oneshot<br/>service"]
    S -->|"start / success / fail<br/>lifecycle events"| J[("systemd journal")]
    J -->|"journalctl -o json"| H["backup-history<br/>reads MESSAGE_IDs"]
    H --> P["Omarchy bar panel<br/>health · last run · 4-week map"]
    P -->|"Run backup now"| R["pkexec systemctl start"]
    R --> S
    P -->|"View logs"| L["journalctl -f<br/>in a terminal"]
```

Each day in the map is colored from the journal, not from the tool's output:

```mermaid
flowchart TD
    Q{"Latest journal event<br/>for that day?"}
    Q -->|"unit failed"| F["Red — failed"]
    Q -->|"unit started / ran"| G["Green — successful"]
    Q -->|"no event"| N["Grey — no backup"]
```

Because detection relies on systemd's own unit lifecycle, a run that exits non-zero is recorded as `failed` by systemd and shown in red — no per-tool parsing required.

## Install

```bash
omarchy plugin add https://github.com/POSO-PocketSolutions/omarchy-backup-history.git --enable --yes
```

The default service is `restic-backup.service`. Point it at another oneshot service with:

```bash
omarchy bar set io.github.mnsosa.backup-history service your-backup.service
```

Optional settings:

```bash
omarchy bar set io.github.mnsosa.backup-history weeks 4 --json
omarchy bar set io.github.mnsosa.backup-history refreshIntervalSec 60 --json
omarchy bar set io.github.mnsosa.backup-history successColor '"#3fb950"' --json
```

The service must be managed by systemd, and its journal must be readable by the desktop user.

## Development

```bash
python -m unittest discover -s tests -v
omarchy plugin validate .
```

## License

MIT © POSO Pocket Solutions
