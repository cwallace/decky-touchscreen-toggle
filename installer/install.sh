#!/usr/bin/env bash
# Install the fixed touchscreen helper and its scoped sudo permission.
#
# Run as root:  sudo ./installer/install.sh --user "$USER"
#
# Design constraints:
#   * One fixed root-owned executable (/usr/local/libexec) using an isolated
#     Python shebang.  No daemon, no shell, no interpreter, no generic
#     "write to sysfs" grant.
#   * One /etc/sudoers.d fragment authorizing exactly that executable for
#     exactly the helper's three mutating argument forms.  The helper itself
#     re-validates the device id and the sysfs location on every call.
#   * No polkit actions or rules (the Bazzite /usr filesystem is read-only and
#     the polkit path was not writable; sudoers is the supported interface).
set -euo pipefail
IFS=$'\n\t'

GROUP="ogui-touch-toggle"
HELPER="/usr/local/libexec/ogui-touchscreen-control"
SUDOERS="/etc/sudoers.d/ogui-touch-toggle"
LEGACY_POLICY="/usr/share/polkit-1/actions/io.github.opengamepadui.touchtoggle.policy"
LEGACY_RULE="/etc/polkit-1/rules.d/49-ogui-touch-toggle.rules"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_ROOT="$SCRIPT_DIR/.."
HELPER_SRC="$SRC_ROOT/root/usr/local/libexec/ogui-touchscreen-control"

TARGET_USER="${SUDO_USER:-}"
DRY_RUN=0

usage() {
	cat <<'EOF'
usage: sudo ./installer/install.sh [--user NAME] [--dry-run]

  --user NAME   Local user allowed to toggle touchscreens (default: $SUDO_USER)
  --dry-run     Print planned actions without changing the system
EOF
}

die() {
	printf 'error: %s\n' "$*" >&2
	exit 1
}

while [ $# -gt 0 ]; do
	case "$1" in
		--user)
			[ $# -ge 2 ] || die "--user requires a value"
			TARGET_USER="$2"
			shift 2
			;;
		--dry-run)
			DRY_RUN=1
			shift
			;;
		-h|--help)
			usage
			exit 0
			;;
		*)
			die "unknown argument: $1"
			;;
	esac
done

validate_user() {
	local user="$1"
	[ -n "$user" ] || die "no target user; pass --user NAME or run via sudo"
	[[ "$user" =~ ^[a-z_][a-z0-9_-]{0,31}$ ]] || die "invalid user name: $user"
	id "$user" >/dev/null 2>&1 || die "user does not exist: $user"
	local uid
	uid="$(id -u "$user")"
	[ "$uid" -ge 1000 ] || die "refusing to authorize system user $user (uid $uid)"
}

# The authorized user must not be able to replace the helper or its sudoers
# fragment, directly or through a writable parent directory.
require_root_owned_chain() {
	local path="$1"
	[ -e "$path" ] || die "required path missing: $path"
	[ -L "$path" ] && die "refusing symlinked path: $path"
	[ "$(stat -c '%U' "$path")" = "root" ] || die "$path is not owned by root"
	local mode
	mode="$(stat -c '%a' "$path")"
	(( (8#$mode & 8#022) == 0 )) || die "$path is group/other writable (mode $mode)"
}

if [ "$DRY_RUN" -eq 0 ]; then
	[ "$(id -u)" -eq 0 ] || die "must run as root (use sudo)"
fi
validate_user "$TARGET_USER"

[ -f "$HELPER_SRC" ] && [ ! -L "$HELPER_SRC" ] || die "helper source missing: $HELPER_SRC"
head -n 1 "$HELPER_SRC" | grep -qx '#!/usr/bin/python3 -I' || die "helper must use the isolated Python shebang"
command -v visudo >/dev/null 2>&1 || die "visudo not found; sudo must be installed"

if [ "$DRY_RUN" -eq 1 ]; then
	cat <<EOF
dry-run: no changes will be made
  group:        $GROUP (create if missing)
  group member: $TARGET_USER (fresh sudo group lookup; no re-login required)
  helper:       $HELPER (root:root 0755)
  sudoers:      $SUDOERS (root:root 0440, validated with visudo -cf)
  legacy:       remove stale polkit policy/rule if present
EOF
	exit 0
fi

# --- group ---------------------------------------------------------------
if getent group "$GROUP" >/dev/null 2>&1; then
	echo "group $GROUP already exists"
else
	groupadd --system "$GROUP"
	echo "created group $GROUP"
fi
usermod -aG "$GROUP" "$TARGET_USER"
echo "added $TARGET_USER to $GROUP"

# --- helper --------------------------------------------------------------
install -d -o root -g root -m 0755 /usr/local/libexec
[ ! -L "$HELPER" ] || die "refusing to install helper over a symlink: $HELPER"
install -o root -g root -m 0755 "$HELPER_SRC" "$HELPER"

# --- sudoers -------------------------------------------------------------
install -d -o root -g root -m 0750 /etc/sudoers.d
[ ! -L "$SUDOERS" ] || die "refusing to install sudoers fragment over a symlink: $SUDOERS"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
cat >"$STAGE/ogui-touch-toggle" <<EOF
# Managed by the ogui-touch-toggle installer. Do not edit.
# Only the fixed root-owned helper may run as root, and only for the helper's
# validated argument forms. The helper re-resolves and re-checks the device on
# every call; it never accepts paths or a sysfs root.
%$GROUP ALL=(root) NOPASSWD: $HELPER set on input[0-9]*, $HELPER set off input[0-9]*, $HELPER restore-all
EOF
chmod 0440 "$STAGE/ogui-touch-toggle"
visudo -cf "$STAGE/ogui-touch-toggle" >/dev/null || die "generated sudoers fragment failed visudo validation"
install -o root -g root -m 0440 "$STAGE/ogui-touch-toggle" "$SUDOERS"

# Remove stale pre-sudoers polkit artifacts from earlier builds.
rm -f "$LEGACY_POLICY" "$LEGACY_RULE"

# --- post-install safety checks -----------------------------------------
require_root_owned_chain /usr/local/libexec
require_root_owned_chain /etc/sudoers.d
[ "$(stat -c '%U:%G %a' "$HELPER")" = "root:root 755" ] || die "helper ownership/mode is not root:root 755"
[ "$(stat -c '%U:%G %a' "$SUDOERS")" = "root:root 440" ] || die "sudoers fragment ownership/mode is not root:root 440"
visudo -cf "$SUDOERS" >/dev/null || die "installed sudoers fragment is invalid"
if id -nG "$TARGET_USER" | tr ' ' '\n' | grep -qx "$GROUP"; then
	echo "confirmed $TARGET_USER is a member of $GROUP"
else
	die "failed to add $TARGET_USER to $GROUP"
fi

cat <<EOF

Installed.
  helper:  $HELPER
  sudoers: $SUDOERS

Verify status (no root needed):
  $HELPER status

sudo reads group membership fresh for each command, so no re-login is needed.
The plugin toggles one touchscreen at a time and only displays state read back
from the kernel.

Before uninstalling the plugin, restore touchscreens:
  sudo $SCRIPT_DIR/uninstall.sh
EOF
