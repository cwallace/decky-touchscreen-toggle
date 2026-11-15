# Touchscreen Toggle

A Decky plugin with one **Disable touchscreen** switch. On disables every supported
physical touchscreen; Off enables them. It does not cover the game with an overlay
or change controller and mouse settings.

The panel reads the actual touchscreen state when it opens. There is no refresh
button or background polling. Changes use independent state readback. If only some
screens change, the plugin tries to restore their previous state and reports the
failure. Unsupported touchscreens are listed but not changed.

## Status

This is an experimental, manually installed plugin, not an official Decky-store
release. The current build is installed and confirmed working by the maintainer on
a Lenovo Legion Go S running Bazzite 45. It includes the **Disable touchscreen**
switch and automatic status refresh when the panel opens. Steam Deck/SteamOS
Stable and Beta testing is still needed. Legion Go 2, ROG Ally variants and other
handhelds have not been hardware-verified; generic discovery is not certification.

Most implementation code was generated with AI assistance. Requirements and
physical testing came from the maintainer. This source is supplied for human
review; it is not being represented as predominantly human-written code.

## Required helper

The backend runs as the normal Decky host user. It calls the fixed root-owned
`/usr/local/libexec/ogui-touchscreen-control` through a narrow sudoers permission.
The helper discovers physical touchscreens through udev, validates each target
again before writing, and uses the kernel's `inhibited` attribute. It excludes
mouse, touchpad, controller and virtual devices.

This source includes the helper and its existing prerequisite installer. The
installer installs the helper and scoped permissions only, not an OGUI interface.
Its historical `ogui-touch-toggle` filenames remain to match the tested deployment.
Do not run it merely to review or build this package.

On a supported system, first inspect the scripts and run their no-write preview:

```sh
bash installer/install.sh --dry-run --user "$USER"
```

The actual prerequisite setup requires administrator approval:

```sh
sudo bash installer/install.sh --user "$USER"
```

Then install the plugin ZIP through Decky's manual plugin installer. A fresh
SteamOS installation of the helper is not yet hardware-verified. If a required
system path is read-only or prerequisite checks fail, stop rather than disabling
OS protections. The runtime ZIP alone does not install these prerequisites.

Removing the helper while this Decky plugin is in use breaks the toggle. The
included uninstall script restores touch before removing the shared helper and
permissions; review its impact before running it.

## Recovery

Turning **Disable touchscreen** on also disables touch navigation in menus and Desktop Mode. Keep a controller,
keyboard or remote recovery connection available. Reboot restores touch because
no off-state is saved. Orderly plugin unload tries to restore only screens this
session disabled, but a crash or forced stop can prevent that recovery. You can
also enable touch by turning the switch off or using the helper's scoped
`restore-all` command.

## Build and test

Use Node and pnpm 9 with the checked-in lockfile:

```sh
pnpm install --frozen-lockfile
npm test
npm run typecheck
npm run build
python3 -m venv .venv
.venv/bin/python -m pip install pytest pytest-asyncio
.venv/bin/python -m pytest tests -q
python3 scripts/package.py
```

Tests simulate touchscreen devices and kernel trees; they do not replace physical
input testing. The package script copies an explicit list of runtime files and
checks required outputs. It does not install anything.

See `THIRD_PARTY_NOTICES.md` for template and dependency notices. Project code is
licensed under GPL-3.0-only, subject to the retained notices for dependencies.

## Marketplace submission

See [SUBMISSION.md](SUBMISSION.md) for the remaining eligibility, SteamOS testing,
metadata and screenshot requirements. Publishing this source does not mean the
plugin is accepted by, or currently eligible for, the official store.
