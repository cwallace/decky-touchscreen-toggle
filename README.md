# Touchscreen Toggle

**0.5 Beta** (`0.5.0-beta.1`) — early testing release. Hardware testing so far is limited to one Lenovo Legion Go S running Bazzite 45; broader testing is needed before 1.0.

Control physical touchscreen input from the [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader) Quick Access Menu.

## Features

- **Disable touchscreen:** turn touch off or on manually while Games only is off.
- **Games only:** disable touch during games and restore it outside games. Manual control is read-only while this is enabled.
- **Game exceptions:** choose installed games that should keep touch enabled. Saved selections remain if a game is uninstalled.

The settings include controller-accessible help. Controller and mouse input are not changed.

## Compatibility

Requires a physical touchscreen with kernel input-inhibit support. Manual control has been verified on a Lenovo Legion Go S running Bazzite 45.

Games-only automation remains experimental. Steam Deck/SteamOS and other handhelds have not yet been hardware-verified.

## Installation

Download the versioned ZIP from the **Artifacts** section of a successful [Build plugin](https://github.com/cwallace/decky-touchscreen-toggle/actions/workflows/build.yml) run. CI uploads the installable ZIP directly, without an extra ZIP wrapper.

Install Decky Loader first, then install the built ZIP through Decky's manual plugin installer. The plugin is self-contained: it bundles its touchscreen helper and declares Decky's `root` flag, so Decky runs the backend as root. No separate installer, sudoers rule, group or system-wide helper is required.

## Build

Requires Node.js, pnpm 9 and Python 3.

```sh
pnpm install --frozen-lockfile
npm run typecheck
npm run build
python3 scripts/package.py
```

## Recovery

Disabling touch affects Steam menus and Desktop Mode too. Keep a controller, mouse or keyboard available. To restore touch, turn off Games only and Disable touchscreen, or reboot. The plugin attempts to restore touchscreens it disabled when unloaded or removed; kernel inhibit state does not survive a reboot.

## License and credits

GPL-3.0-only. See [LICENSE](LICENSE) and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for the Decky template and dependency notices.

Most implementation code was generated with AI assistance.
