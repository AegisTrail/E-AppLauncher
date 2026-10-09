#!/usr/bin/env bash
#
# Install E-AppLauncher from GitHub Release binaries (Linux).
#
#   curl -fsSL https://raw.githubusercontent.com/AegisTrail/E-AppLauncher/main/install.sh | bash
#   curl -fsSL .../install.sh | bash -s -- --dir ~/AppImages --version 0.2.0
#
# Options:
#   --version X     install version X (default: latest release)
#   --to DIR        install directory (default: ~/.local/bin)
#   --system        install to /usr/local/bin instead
#   --dir DIR       configure DIR as the AppImage library (default: ~/AppImages)
#   --no-configure  skip the library configuration step
#   --uninstall     remove the installed binary and exit
#   -h, --help      show this help
#
# Env overrides (useful for mirrors and testing):
#   EAL_REPO          GitHub repo slug (default: AegisTrail/E-AppLauncher)
#   EAL_RELEASE_BASE  full base URL for assets (default: GitHub releases for VERSION)
#   EAL_API_URL       override the "latest release" API endpoint
#
set -euo pipefail

REPO="${EAL_REPO:-AegisTrail/E-AppLauncher}"
VERSION=""
INSTALL_DIR="${HOME}/.local/bin"
SYSTEM=0
APPS_DIR="${HOME}/AppImages"
CONFIGURE=1
UNINSTALL=0

usage() {
  sed -n '2,/^$/p' "$0" | sed 's/^# \?//'
}

log()  { printf '==> %s\n' "$*"; }
die()  { printf 'error: %s\n' "$*" >&2; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --version)      VERSION="${2:?--version needs a value}"; shift 2 ;;
    --to)           INSTALL_DIR="${2:?--to needs a value}"; shift 2 ;;
    --system)       SYSTEM=1; shift ;;
    --dir)          APPS_DIR="${2:?--dir needs a value}"; shift 2 ;;
    --no-configure) CONFIGURE=0; shift ;;
    --uninstall)    UNINSTALL=1; shift ;;
    -h|--help)      usage; exit 0 ;;
    *)              die "unknown option: $1 (see --help)" ;;
  esac
done

if [ "$SYSTEM" -eq 1 ]; then
  INSTALL_DIR="/usr/local/bin"
fi

need() {
  command -v "$1" >/dev/null 2>&1 || die "required tool missing: $1"
}
need curl
need tar

# sha256 backend: prefer sha256sum, fall back to shasum.
if command -v sha256sum >/dev/null 2>&1; then
  SHA256SUM="sha256sum"
elif command -v shasum >/dev/null 2>&1; then
  SHA256SUM="shasum -a 256"
else
  die "required tool missing: sha256sum (or shasum)"
fi

if [ "$(uname -s)" != "Linux" ]; then
  die "this installer supports Linux only (detected: $(uname -s))"
fi

case "$(uname -m)" in
  x86_64|amd64)   ARCH="x86_64" ;;
  aarch64|arm64)  ARCH="aarch64" ;;
  *)              die "unsupported architecture: $(uname -m)" ;;
esac

# --- uninstall -------------------------------------------------------------
find_binary() {
  # prints the installed binary path, if any
  for d in "$INSTALL_DIR" "$HOME/.local/bin" "/usr/local/bin"; do
    if [ -x "$d/e-applauncher" ] && [ -f "$d/e-applauncher" ]; then
      printf '%s\n' "$d/e-applauncher"
      return 0
    fi
  done
  return 1
}

if [ "$UNINSTALL" -eq 1 ]; then
  if bin="$(find_binary)"; then
    log "removing $bin"
    rm -f "$bin"
    log "uninstalled. Your library config (~/.local/share/e-applauncher) was left in place."
    log "Run 'e-applauncher --forget' before uninstalling to clear it as well."
  else
    log "no installed e-applauncher binary found."
  fi
  exit 0
fi

# --- resolve version -------------------------------------------------------
if [ -z "$VERSION" ]; then
  api="${EAL_API_URL:-https://api.github.com/repos/${REPO}/releases/latest}"
  log "resolving latest release ($api)"
  tag="$(curl -fsSL --retry 3 "$api" | grep -o '"tag_name": *"[^"]*"' | head -n1 | cut -d'"' -f4)"
  [ -n "${tag:-}" ] || die "could not determine latest release from $api"
  VERSION="$tag"
fi
# Accept "0.2.0" or "v0.2.0"; assets use the bare version.
VER="${VERSION#v}"
if ! [[ "$VER" =~ ^[0-9]+\.[0-9]+\.[0-9]+ ]]; then
  die "invalid version: $VERSION (expected like 0.2.0)"
fi

base="${EAL_RELEASE_BASE:-https://github.com/${REPO}/releases/download/v${VER}}"
asset="e-applauncher-${VER}-linux-${ARCH}.tar.gz"

# --- download + verify -----------------------------------------------------
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
log "downloading ${asset} (${VERSION})"
curl -fSL --retry 3 -o "$tmp/$asset" "$base/$asset"
curl -fSL --retry 3 -o "$tmp/$asset.sha256" "$base/$asset.sha256"
log "verifying checksum"
(cd "$tmp" && $SHA256SUM -c "$asset.sha256")

log "extracting"
tar -xzf "$tmp/$asset" -C "$tmp"
[ -f "$tmp/e-applauncher" ] || die "archive did not contain e-applauncher binary"

# --- install ---------------------------------------------------------------
mkdir -p "$INSTALL_DIR"
if command -v install >/dev/null 2>&1; then
  install -m 0755 "$tmp/e-applauncher" "$INSTALL_DIR/e-applauncher"
else
  cp -f "$tmp/e-applauncher" "$INSTALL_DIR/e-applauncher"
  chmod 0755 "$INSTALL_DIR/e-applauncher"
fi
chmod +x "$INSTALL_DIR/e-applauncher"  # belt and braces: must be executable
BIN="$INSTALL_DIR/e-applauncher"
log "installed to $BIN"
"$BIN" --version

case ":$PATH:" in
  *":$INSTALL_DIR:"*) ;;
  *) log "NOTE: $INSTALL_DIR is not on your PATH. Add it, e.g.:"; printf '  export PATH="%s:$PATH"\n' "$INSTALL_DIR" ;;
esac

# --- configure -------------------------------------------------------------
# Default library location is ~/AppImages; --dir overrides, --no-configure skips.
if [ "$CONFIGURE" -eq 1 ]; then
  if [ -n "$APPS_DIR" ]; then
    mkdir -p "$APPS_DIR"
    log "configuring library: $APPS_DIR"
    # --list scans + saves the directory without opening the TUI.
    "$BIN" --dir "$APPS_DIR" --list > /dev/null
    log "library configured."
  else
    log "skipping library setup (pass --dir PATH to set one)."
  fi
fi

log "done. Run: e-applauncher   (state lives in ~/.local/share/e-applauncher)"
