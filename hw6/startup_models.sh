#!/bin/bash
# Startup script for the HW6 models VM (passed with --metadata-from-file).
# Runs as root at boot: installs Python, fetches the code from the VM's
# metadata, trains both models, and uploads the results to the bucket.
# run_hw6.sh waits for gs://.../hw6-output/summary.txt (or run_error.log),
# then deletes this VM.
set -uo pipefail

LOCK=/var/log/startup_already_done
APP=/opt/hw6
LOG=/var/log/hw6-models.log
OUT=gs://cs528-12kfiles-bucket-thomas/hw6-output
MD=http://metadata.google.internal/computeMetadata/v1/instance/attributes
md() { curl -sf -H "Metadata-Flavor: Google" "$MD/$1"; }

if [ -f "$LOCK" ]; then
  echo "[startup] already ran once; not running the models again"
  exit 0
fi
touch "$LOCK"

(
  set -e
  echo "[startup] installing Python"
  APT="apt-get -o DPkg::Lock::Timeout=600"
  $APT update -y
  DEBIAN_FRONTEND=noninteractive $APT install -y python3-venv

  echo "[startup] fetching code from metadata"
  mkdir -p "$APP"
  md models-code    > "$APP/models.py"
  md dbconn-code    > "$APP/dbconn.py"
  md requirements   > "$APP/requirements.txt"

  echo "[startup] installing libraries"
  python3 -m venv "$APP/venv"
  "$APP/venv/bin/pip" install --quiet --upgrade pip
  "$APP/venv/bin/pip" install --quiet -r "$APP/requirements.txt"

  echo "[startup] running models.py"
  cd "$APP"
  "$APP/venv/bin/python" models.py
) > "$LOG" 2>&1
status=$?

if [ "$status" -ne 0 ]; then
  echo "[startup] FAILED with status $status" >> "$LOG"
  gcloud storage cp "$LOG" "$OUT/run_error.log"
else
  gcloud storage cp "$LOG" "$OUT/run.log"
fi
echo "[startup] done (status $status)"
