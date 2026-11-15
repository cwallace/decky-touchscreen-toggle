#!/usr/bin/env bash
# Remove the touchscreen helper and its sudoers fragment.
#
# Safety: every detected touchscreen is restored to inhibited=0 BEFORE any file
# is removed.  If restore fails the script aborts (unless --force) and leaves
# the helper installed so touch input can still be recovered.  Run this before
# removing the plugin package.
set -euo pipefail
IFS=$'\n\t'

GROUP="ogui-touch-toggle"
HELPER="/usr/local/libexec/ogui-touchscreen-control"
SUDOERS="/etc/sudoers.d/ogui-touch-toggle"
LEGACY_POLICY="/usr/share/polkit-1/actions/io.github.opengamepadui.touchtoggle.policy"
LEGACY_RULE="/etc/polkit-1/rules.d/49-ogui-touch-toggle.rules"

DRY_RUN=0
FORCE=0
PURGE_GROUP=0

usage() {
	cat <<'EOF'
usage: sudo ./installer/uninstall.sh [--purge-group] [--force] [--dry-run]

  --purge-group  Also delete the ogui-touch-toggle group
  --force        Remove files even if touchscreen restore fails
  --dry-run      Print planned actions without changing the system
EOF
}

die() {
	printf 'error: %s\n' "$*" >&2
	exit 1
}

while [ $# -gt 0 ]; do
	case "$1" in
		--purge-group) PURGE_GROUP=1; shift ;;
		--force) FORCE=1; shift ;;
		--dry-run) DRY_RUN=1; shift ;;
		-h|--help) usage; exit 0 ;;
		*) die "unknown argument: $1" ;;
	esac
done

if [ "$DRY_RUN" -eq 0 ]; then
	[ "$(id -u)" -eq 0 ] || die "must run as root (use sudo)"
fi

if [ "$DRY_RUN" -eq 1 ]; then
	cat <<EOF
dry-run: no changes will be made
  would run: $HELPER restore-all
  remove:    $SUDOERS
  remove:    $HELPER
  legacy:    remove stale polkit policy/rule if present
  group:     $([ "$PURGE_GROUP" -eq 1 ] && echo "delete $GROUP" || echo "keep $GROUP")
EOF
	exit 0
fi

if [ -f "$HELPER" ]; then
	echo "restoring all detected touchscreens..."
	restore_ok=1
	if [ -x "$HELPER" ]; then
		"$HELPER" restore-all || restore_ok=0
	else
		# Executable bit lost/corrupted: the isolated interpreter still works.
		/usr/bin/python3 -I "$HELPER" restore-all || restore_ok=0
	fi
	if [ "$restore_ok" -eq 0 ]; then
		if [ "$FORCE" -eq 1 ]; then
			echo "warning: restore-all failed; continuing because --force was given" >&2
		else
			die "restore-all failed; touch input may still be disabled. Fix the error or use --force"
		fi
	fi
else
	echo "helper not installed; nothing to restore"
fi

# Sudo access is revoked before the binary disappears.
rm -f "$SUDOERS" "$LEGACY_POLICY" "$LEGACY_RULE"
rm -f "$HELPER"

if [ "$PURGE_GROUP" -eq 1 ]; then
	if getent group "$GROUP" >/dev/null 2>&1; then
		groupdel "$GROUP" || echo "warning: could not delete group $GROUP" >&2
	fi
fi

cat <<EOF
Removed touchscreen helper and sudoers fragment.
A disconnected or newly attached touchscreen returns to normal on reboot
because kernel inhibit state is volatile.
EOF
