# WPS Runtime Probe Kit

This kit is designed for manual import into an intranet environment to validate:

- Kylin V10 ARM runtime basics
- WPS binary presence
- WPS add-in runtime capability exposure
- localhost adapter reachability
- deployment directory layout

The kit is intentionally self-contained and avoids Node.js build-time dependencies.

## Contents

- `wps-probe-addon/`
- `scripts/probe_runtime.sh`
- `scripts/collect_acceptance_record.sh`
- `docs/import-guide.md`
- `docs/dependencies.md`
- `docs/target-machine-validation-checklist.md`
- `docs/acceptance-record-template.md`

## Delivery Mode

Copy the generated archive into the intranet environment, unpack it, then follow `docs/import-guide.md`.
