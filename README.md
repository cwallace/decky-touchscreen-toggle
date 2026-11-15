# Touchscreen Toggle

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

Install Decky Loader first. From this repository's directory, review and install the required touchscreen helper:

```sh
bash installer/install.sh --dry-run --user "$USER"
sudo bash installer/install.sh --user "$USER"
```

Install the built ZIP through Decky's manual plugin installer. The ZIP does not install the helper. If the helper cannot be installed on your system, stop rather than disabling OS protections.

## Build

Requires Node.js, pnpm 9 and Python 3.

```sh
pnpm install --frozen-lockfile
npm run typecheck
npm run build
python3 scripts/package.py
```

## Recovery

Disabling touch affects Steam menus and Desktop Mode too. Keep a controller, mouse or keyboard available. To restore touch, turn off Games only and Disable touchscreen, or reboot.

Remove the Decky plugin before uninstalling its shared helper.

## License and credits

GPL-3.0-only. See [LICENSE](LICENSE) and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for the Decky template and dependency notices.

Most implementation code was generated with AI assistance.
