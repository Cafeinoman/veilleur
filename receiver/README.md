# veilleur-receive

Reference receiver for [Veilleur](https://github.com/Cafeinoman/veilleur): a small command that shows how to write a
receiving tool with the `veilleur-protocol` library. It depends on that library only.

```bash
veilleur-receive pair                                # paste the pairing code (it is never a command-line argument)
veilleur-receive pull --folder reports/              # fetch over HTTPS, check, and file the reports
veilleur-receive pull --folder reports/ --from usb/  # read a folder written by `veilleur export`
```

Each report is filed in `<folder>/<uid>/<number>-<kind>/`: `items.jsonl` (the authoritative data), `manifest.json` and
the renderings the subscription asked for. Reports are readable by the current user only.

The pairing secret, the trusted server keys and the last number received are kept in
`$XDG_STATE_HOME/veilleur-receive/receiver.json` (or the folder given by `--state-dir`), readable by the current user
only. Anyone who gets that file can read the reports of this pairing: protect it as a password.

The exit status is 0 when everything was received, 1 when something was refused or failed: what was received before
the failure is kept, and the next `pull` resumes from there.
