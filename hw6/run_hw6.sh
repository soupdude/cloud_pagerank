#!/bin/bash
# CS528 HW6: one command for the whole run.
#   1. starts the Cloud SQL database (and pauses the hourly HW5 monitor)
#   2. rebuilds the 3NF database hw6 from the HW5 tables (migrate_schema.py)
#   3. creates a VM that trains both models and writes the test-set output
#      to gs://<bucket>/hw6-output/
#   4. waits for it, then stops the database, deletes the VM, re-enables the
#      monitor, and prints the output files from the bucket
# Step 4's cleanup also runs if anything fails or you press Ctrl-C.
#
#   ./run_hw6.sh
set -euo pipefail
cd "$(dirname "$0")"

PROJECT="project-f131ec20-0df6-4cfa-bf0"     # hardcoded on purpose
REGION="us-central1"
ZONE="us-central1-b"
BUCKET="cs528-12kfiles-bucket-thomas"
OUT="gs://$BUCKET/hw6-output"
DB_INSTANCE="hw5-db"
DB_SECRET="hw5-db-pass"
MONITOR_JOB="hw5-db-monitor-hourly"
SA_NAME="hw6-sa"
SA="${SA_NAME}@${PROJECT}.iam.gserviceaccount.com"
VM="hw6-models"
MACHINE="e2-standard-2"                       # 2 vCPUs, 8 GB for pandas/scikit-learn
TIMEOUT_MIN=45

g() { gcloud --project="$PROJECT" --quiet "$@"; }
db_policy() { g sql instances describe "$DB_INSTANCE" --format='value(settings.activationPolicy)'; }
job_state() { g scheduler jobs describe "$MONITOR_JOB" --location="$REGION" --format='value(state)' 2>/dev/null || true; }

PAUSED_MONITOR=0
CLEANED=0
cleanup() {
  [ "$CLEANED" = 1 ] && return
  CLEANED=1
  echo "== Cleaning up"
  if g compute instances describe "$VM" --zone="$ZONE" >/dev/null 2>&1; then
    echo "   deleting VM $VM"
    g compute instances delete "$VM" --zone="$ZONE" || true
  fi
  if [ "$(db_policy 2>/dev/null || true)" = "ALWAYS" ]; then
    echo "   stopping database $DB_INSTANCE"
    g sql instances patch "$DB_INSTANCE" --activation-policy=NEVER || true
  fi
  if [ "$PAUSED_MONITOR" = 1 ]; then
    echo "   re-enabling the hourly database monitor"
    g scheduler jobs resume "$MONITOR_JOB" --location="$REGION" || true
  fi
}
trap cleanup EXIT

echo "== 1. APIs and the VM's service account"
g services enable compute.googleapis.com sqladmin.googleapis.com \
  secretmanager.googleapis.com storage.googleapis.com iam.googleapis.com
if ! g iam service-accounts describe "$SA" >/dev/null 2>&1; then
  g iam service-accounts create "$SA_NAME" --display-name="CS528 HW6 models"
  sleep 20
fi
# Connect to Cloud SQL, read the DB password, write results to the bucket, write logs.
for role in roles/cloudsql.client roles/logging.logWriter; do
  g projects add-iam-policy-binding "$PROJECT" --condition=None \
    --member="serviceAccount:$SA" --role="$role" >/dev/null
done
g secrets add-iam-policy-binding "$DB_SECRET" \
  --member="serviceAccount:$SA" --role=roles/secretmanager.secretAccessor >/dev/null
g storage buckets add-iam-policy-binding "gs://$BUCKET" \
  --member="serviceAccount:$SA" --role=roles/storage.objectAdmin >/dev/null

echo "== 2. Starting the database"
if [ "$(job_state)" = "ENABLED" ]; then
  g scheduler jobs pause "$MONITOR_JOB" --location="$REGION"
  PAUSED_MONITOR=1
fi
if [ "$(db_policy)" != "ALWAYS" ]; then
  g sql instances patch "$DB_INSTANCE" --activation-policy=ALWAYS
else
  echo "   already running"
fi

echo "== 3. Building the 3NF database hw6 from hw5"
[ -x .venv/bin/python ] || python3 -m venv .venv
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -r requirements.txt
.venv/bin/python migrate_schema.py

echo "== 4. Creating VM $VM to train the models"
g storage rm "$OUT/**" >/dev/null 2>&1 || true      # clear the previous run's output
if g compute instances describe "$VM" --zone="$ZONE" >/dev/null 2>&1; then
  g compute instances delete "$VM" --zone="$ZONE"
fi
g compute instances create "$VM" \
  --zone="$ZONE" --machine-type="$MACHINE" \
  --image-family=debian-12 --image-project=debian-cloud \
  --service-account="$SA" --scopes=cloud-platform \
  --metadata-from-file=startup-script=startup_models.sh,models-code=models.py,dbconn-code=dbconn.py,requirements=requirements.txt

echo "== 5. Waiting for the results (usually 5-10 minutes; limit $TIMEOUT_MIN)"
deadline=$(( $(date +%s) + TIMEOUT_MIN * 60 ))
result=""
while [ "$(date +%s)" -lt "$deadline" ]; do
  if g storage ls "$OUT/run_error.log" >/dev/null 2>&1; then result=error; break; fi
  if g storage ls "$OUT/summary.txt" >/dev/null 2>&1; then result=ok; break; fi
  printf "   %s still running...\n" "$(date +%H:%M:%S)"
  sleep 30
done

cleanup   # stop the database and delete the VM before printing

echo
if [ "$result" = ok ]; then
  echo "== Output files in $OUT"
  g storage ls "$OUT/"
  echo
  echo "== $OUT/summary.txt"
  g storage cat "$OUT/summary.txt"
  tmp=$(mktemp -d)
  for f in model1_country_test_predictions.csv model2_income_test_predictions.csv; do
    # Download whole files: piping `storage cat` into head makes gcloud report a hash error.
    g storage cp "$OUT/$f" "$tmp/$f" >/dev/null 2>&1
    echo
    echo "== $OUT/$f (first 10 of $(tail -n +2 "$tmp/$f" | wc -l) test rows)"
    head -n 11 "$tmp/$f"
  done
  rm -rf "$tmp"
elif [ "$result" = error ]; then
  echo "== The models VM failed. Its log ($OUT/run_error.log):"
  g storage cat "$OUT/run_error.log" > /tmp/hw6_run_error.log 2>/dev/null || true
  tail -n 40 /tmp/hw6_run_error.log
  exit 1
else
  echo "== Timed out after $TIMEOUT_MIN minutes without results."
  exit 1
fi
