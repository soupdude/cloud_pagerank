#!/bin/bash
# Startup script for the Service 2 VM (the unmodified HW4 Service 2).
# Compute Engine runs it as root on every boot; the lock file makes the
# installation happen only once.
set -euo pipefail

LOCK=/var/log/startup_already_done
APP_DIR=/opt/hw5/service2
VENV=/opt/hw5/venv
MD=http://metadata.google.internal/computeMetadata/v1/instance/attributes
md() { curl -sf -H "Metadata-Flavor: Google" "$MD/$1"; }

mkdir -p "$APP_DIR"
md service2-code > "$APP_DIR/main.py"
md service2-requirements > "$APP_DIR/requirements.txt"

if [ -f "$LOCK" ]; then
  echo "[startup] setup already ran once; skipping package installation"
else
  APT="apt-get -o DPkg::Lock::Timeout=600"
  $APT update -y
  DEBIAN_FRONTEND=noninteractive $APT install -y python3-venv

  python3 -m venv "$VENV"
  "$VENV/bin/pip" install --quiet --upgrade pip
  "$VENV/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"

  cat > /etc/systemd/system/hw5-service2.service <<EOF
[Unit]
Description=CS528 HW5 Service 2 forbidden-request reporter
After=network-online.target
Wants=network-online.target

[Service]
Environment=PYTHONUNBUFFERED=1
WorkingDirectory=$APP_DIR
ExecStart=$VENV/bin/python $APP_DIR/main.py
Restart=always
RestartSec=3
DynamicUser=yes

[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
  systemctl enable hw5-service2
  touch "$LOCK"
fi

systemctl restart hw5-service2
echo "[startup] done"
