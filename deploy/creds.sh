#!/usr/bin/env bash
# Creates or replaces one systemd encrypted credential for diary-app.
#
#   sudo deploy/creds.sh <name>              # prompts for the value (no echo)
#   sudo deploy/creds.sh <name> --generate   # random 32-byte secret
#   sudo deploy/creds.sh <name> --force      # overwrite an existing one
#
# <name> must match a LoadCredentialEncrypted= line in diary-app.service and
# the setting it feeds (lower-case, underscores). The value is piped straight
# into systemd-creds, so plaintext never touches disk or shell history.
set -euo pipefail

CRED_DIR="${CRED_DIR:-/etc/diary-app/creds}"
# "host" ties the file to this machine's /var/lib/systemd/credential.secret.
# Only override for tests: "null" provides no protection.
CREDS_KEY="${CREDS_KEY:-host}"

usage() { sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//' >&2; exit 2; }

name="${1:-}"
[[ -n "$name" ]] || usage
shift
generate=0
force=0
for arg in "$@"; do
  case "$arg" in
    --generate) generate=1 ;;
    --force) force=1 ;;
    *) usage ;;
  esac
done

[[ "$name" =~ ^[a-z][a-z0-9_]*$ ]] || {
  echo "!! name must be lower-case letters, digits and underscores" >&2
  exit 2
}
[[ "$EUID" -eq 0 ]] || { echo "!! run as root (use sudo)" >&2; exit 1; }

install -d -m 0700 "$CRED_DIR"
target="$CRED_DIR/$name.cred"
if [[ -e "$target" && "$force" -ne 1 ]]; then
  echo "!! $target exists; pass --force to replace it" >&2
  exit 1
fi

encrypt() {
  systemd-creds encrypt --with-key="$CREDS_KEY" --name="$name" - "$target"
}

if [[ "$generate" -eq 1 ]]; then
  head -c 32 /dev/urandom | base64 | tr -d '\n' | encrypt
else
  read -rs -p "Value for $name: " value; echo
  read -rs -p "Again to confirm: " again; echo
  [[ "$value" == "$again" ]] || { echo "!! values differ" >&2; exit 1; }
  [[ -n "$value" ]] || { echo "!! value is empty" >&2; exit 1; }
  printf %s "$value" | encrypt
  unset value again
fi

chmod 0600 "$target"
echo "==> Saved $target"
echo "==> Apply with: systemctl restart diary-app"
