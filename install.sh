#!/bin/sh
# Install flappy: fetch the single script, check it runs, drop it on your PATH.
#
#   curl -fsSL https://raw.githubusercontent.com/OWNER/flappy-terminal/main/install.sh | sh
#
# Override with FLAPPY_REPO, FLAPPY_REF, FLAPPY_BIN or FLAPPY_URL.

set -eu

REPO="${FLAPPY_REPO:-OWNER/flappy-terminal}"
REF="${FLAPPY_REF:-main}"
URL="${FLAPPY_URL:-https://raw.githubusercontent.com/$REPO/$REF/flappy.py}"

command -v python3 >/dev/null 2>&1 || {
    echo "flappy needs python3" >&2
    exit 1
}
python3 -c 'import curses' >/dev/null 2>&1 || {
    echo "your python3 has no curses module (Debian/Ubuntu: apt install python3-curses)" >&2
    exit 1
}

BIN=""
for dir in "${FLAPPY_BIN:-}" "$HOME/.local/bin" /usr/local/bin; do
    [ -n "$dir" ] || continue
    if mkdir -p "$dir" 2>/dev/null && [ -w "$dir" ]; then
        BIN="$dir"
        break
    fi
done
[ -n "$BIN" ] || {
    echo "no writable install directory found; set FLAPPY_BIN=/somewhere/bin" >&2
    exit 1
}

TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT INT TERM

if command -v curl >/dev/null 2>&1; then
    curl -fsSL "$URL" -o "$TMP"
elif command -v wget >/dev/null 2>&1; then
    wget -qO "$TMP" "$URL"
else
    echo "flappy needs curl or wget" >&2
    exit 1
fi

python3 "$TMP" --selftest >/dev/null || {
    echo "the downloaded file failed its own selftest, refusing to install it" >&2
    exit 1
}

chmod 755 "$TMP"
mv "$TMP" "$BIN/flappy"
trap - EXIT INT TERM

echo "installed $BIN/flappy"
case ":$PATH:" in
    *":$BIN:"*) echo "start it with: flappy" ;;
    *) echo "$BIN is not on your PATH; start it with: $BIN/flappy" ;;
esac
