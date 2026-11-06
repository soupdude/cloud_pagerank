#!/bin/bash
# Startup script for the HW5 web server VM (passed with --metadata-from-file).
# Compute Engine runs it as root on every boot.
#
# First boot: installs packages, creates a venv, writes the systemd service,
#             then creates the lock file.
# Every boot: refreshes server.py from the VM's metadata and restarts the
#             service, so ./manage.sh redeploy-server can ship new code.
set -euo pipefail

LOCK=/var/log/startup_already_done
APP_DIR=/opt/hw5/server
VENV=/opt/hw5/venv
MD=http://metadata.google.internal/computeMetadata/v1/instance/attributes
md() { curl -sf -H "Metadata-Flavor: Google" "$MD/$1"; }

mkdir -p "$APP_DIR"
md server-code > "$APP_DIR/server.py"
md server-requirements > "$APP_DIR/requirements.txt"

if [ -f "$LOCK" ]; then
  echo "[startup] setup already ran once; skipping package installation"
else
  echo "[startup] installing system packages"
  # Wait for the apt lock if another installer is running at boot.
  APT="apt-get -o DPkg::Lock::Timeout=600"
  $APT update -y
  DEBIAN_FRONTEND=noninteractive $APT install -y python3-venv

  echo "[startup] installing Python libraries"
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install --quiet --upgrade pip
  "$VENV/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"

  echo "[startup] writing systemd service"
  cat > /etc/systemd/system/hw5-server.service <<EOF
[Unit]
Description=CS528 HW5 web server
After=network-online.target
Wants=network-online.target

[Service]
Environment=PORT=80
Environment=WORKERS=16
Environment=PYTHONUNBUFFERED=1
# Per-request timings, readable with: sudo cat /var/lib/hw5/timings.csv
Environment=TIMINGS_FILE=/var/lib/hw5/timings.csv
StateDirectory=hw5
WorkingDirectory=$APP_DIR
ExecStart=$VENV/bin/python $APP_DIR/server.py
Restart=always
RestartSec=3
# Run as a throwaway unprivileged user, with only the right to bind port 80.
DynamicUser=yes
AmbientCapabilities=CAP_NET_BIND_SERVICE
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
  systemctl enable hw5-server
  touch "$LOCK"
fi

systemctl restart hw5-server   # picks up the refreshed code
echo "[startup] done"
