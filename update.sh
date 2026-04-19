#!/usr/bin/env bash
set -e

INSTALL_DIR="$HOME/.claude/cc-2x-statusline"
REPO_URL="https://github.com/Nadav-Fux/claude-2x-statusline.git"
ZIP_URL="https://github.com/Nadav-Fux/claude-2x-statusline/archive/refs/heads/main.zip"
TEMP_DIR=""

cleanup() {
    if [ -n "$TEMP_DIR" ] && [ -d "$TEMP_DIR" ]; then
        rm -rf "$TEMP_DIR"
    fi
}
trap cleanup EXIT

if [ ! -f "$INSTALL_DIR/install.sh" ]; then
    echo "Install dir not found at $INSTALL_DIR"
    exit 1
fi

if [ -d "$INSTALL_DIR/.git" ] && command -v git >/dev/null 2>&1; then
    echo "Updating existing git install..."
    git -C "$INSTALL_DIR" pull --ff-only
    exec bash "$INSTALL_DIR/install.sh" --update --quiet "$@"
fi

TEMP_DIR=$(mktemp -d)

if command -v git >/dev/null 2>&1; then
    echo "Bootstrapping latest source via git clone..."
    git clone --depth 1 "$REPO_URL" "$TEMP_DIR/claude-2x-statusline"
    exec bash "$TEMP_DIR/claude-2x-statusline/install.sh" --update --quiet "$@"
fi

if command -v curl >/dev/null 2>&1; then
    echo "Bootstrapping latest source via zip download..."
    curl -fsSL "$ZIP_URL" -o "$TEMP_DIR/repo.zip"
elif command -v wget >/dev/null 2>&1; then
    echo "Bootstrapping latest source via zip download..."
    wget -q "$ZIP_URL" -O "$TEMP_DIR/repo.zip"
else
    echo "git, curl, or wget is required to update this install."
    exit 1
fi

unzip -q "$TEMP_DIR/repo.zip" -d "$TEMP_DIR"
SOURCE_DIR=$(find "$TEMP_DIR" -maxdepth 1 -type d -name 'claude-2x-statusline-*' | head -n 1)

if [ -z "$SOURCE_DIR" ]; then
    echo "Could not unpack update source."
    exit 1
fi

exec bash "$SOURCE_DIR/install.sh" --update --quiet "$@"