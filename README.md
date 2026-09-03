# Omarchy Backup History

A compact GitHub-style calendar for systemd backup services in the Omarchy bar.

![Backup History in the Omarchy bar](preview.png)

- Green: the latest run that day succeeded.
- Red: the latest run that day failed.
- Gray: no run was recorded.
- Accent: a backup is running today.
- Click: follow the service logs.

## Install

```bash
omarchy plugin add https://github.com/mnsosa/omarchy-backup-history.git --enable --yes
```

The default service is `restic-backup.service`. Configure another oneshot service with:

```bash
omarchy bar set io.github.mnsosa.backup-history service your-backup.service
```

Optional settings:

```bash
omarchy bar set io.github.mnsosa.backup-history weeks 12 --json
omarchy bar set io.github.mnsosa.backup-history refreshIntervalSec 60 --json
omarchy bar set io.github.mnsosa.backup-history successColor '"#3fb950"' --json
```

The service must be managed by systemd and its logs must be readable by the desktop user. Successful and failed oneshot executions are detected from systemd's structured journal events, so the plugin does not require access to backup credentials.

## Development

```bash
python -m unittest discover -s tests -v
omarchy plugin validate .
```

## License

MIT
