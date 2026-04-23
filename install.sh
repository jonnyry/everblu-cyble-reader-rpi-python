#!/usr/bin/env bash
# One-time setup on a fresh Raspberry Pi: enable SPI, install system deps,
# create venv, install Python deps, and grant the invoking user access to
# the SPI and GPIO device nodes so the tools run without sudo.
#
# Run as: ./install.sh    (will prompt for the sudo password once)
set -euo pipefail

cd "$(dirname "$0")"

USER_NAME="${SUDO_USER:-$USER}"

echo "[1/5] Enable SPI via raspi-config..."
sudo raspi-config nonint do_spi 0 || echo "  (already enabled or non-standard image)"

echo "[2/5] Install system packages (python3-venv, python3-dev)..."
sudo apt-get update -qq
sudo apt-get install -y python3-venv python3-dev

echo "[3/5] Grant $USER_NAME access to SPI and GPIO..."
sudo usermod -a -G spi,gpio "$USER_NAME"

echo "[4/5] Create/refresh virtualenv..."
if [ ! -d .venv ]; then
    python3 -m venv .venv
fi
./.venv/bin/pip install --upgrade pip
./.venv/bin/pip install -r requirements.txt
./.venv/bin/pip install pytest

echo "[5/5] Done."
echo
echo "You must log out and back in (or reboot) for the spi/gpio group"
echo "membership to take effect for $USER_NAME."
echo
echo "Then run the diagnostic suite:"
echo "    ./.venv/bin/python scripts/diag.py"
