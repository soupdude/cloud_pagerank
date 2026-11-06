#!/bin/bash
# CS528 HW5: provisions everything, in one command. Safe to run more than once;
# anything that already exists is reused (a stopped database is started).
#
#   ./setup.sh
#
# Needs: gcloud logged in as a project Owner (gcloud auth login), python3 with venv.
set -euo pipefail
cd "$(dirname "$0")"
source ./config.sh

echo "== 1. Enabling APIs (first run takes a minute)"
g services enable compute.googleapis.com pubsub.googleapis.com logging.googleapis.com \
  monitoring.googleapis.com storage.googleapis.com iam.googleapis.com \
  sqladmin.googleapis.com secretmanager.googleapis.com cloudfunctions.googleapis.com \
  cloudbuild.googleapis.com run.googleapis.com eventarc.googleapis.com \
  artifactregistry.googleapis.com cloudscheduler.googleapis.com

echo "== 2. Service accounts"
created=0
for name in "$SERVER_SA_NAME" "$SERVICE2_SA_NAME" "$MONITOR_SA_NAME"; do
  if g iam service-accounts describe "${name}@${PROJECT}.iam.gserviceaccount.com" >/dev/null 2>&1; then
    echo "   $name exists"
  else
    g iam service-accounts create "$name" --display-name="CS528 HW5 $name"
    created=1
  fi
done
# New service accounts take a few seconds before they can be granted roles.
if [ "$created" = 1 ]; then sleep 20; fi

echo "== 3. Pub/Sub topics"
g pubsub topics describe "$TOPIC" >/dev/null 2>&1 || g pubsub topics create "$TOPIC"
g pubsub subscriptions describe "$SUBSCRIPTION" >/dev/null 2>&1 \
  || g pubsub subscriptions create "$SUBSCRIPTION" --topic="$TOPIC"
g pubsub topics describe "$MONITOR_TOPIC" >/dev/null 2>&1 || g pubsub topics create "$MONITOR_TOPIC"

echo "== 4. Database password in Secret Manager"
if ! g secrets describe "$DB_SECRET" >/dev/null 2>&1; then
  openssl rand -base64 24 | tr -d '/+=\n' \
    | g secrets create "$DB_SECRET" --replication-policy=automatic --data-file=-
fi
DB_PASS=$(g secrets versions access latest --secret="$DB_SECRET")

echo "== 5. Least-privilege roles"
# Web server: read the bucket, publish to Service 2's topic, read the DB password,
# connect to Cloud SQL, write logs and metrics.
g storage buckets add-iam-policy-binding "gs://$BUCKET" \
  --member="serviceAccount:$SERVER_SA" --role=roles/storage.objectViewer >/dev/null
g pubsub topics add-iam-policy-binding "$TOPIC" \
  --member="serviceAccount:$SERVER_SA" --role=roles/pubsub.publisher >/dev/null
g secrets add-iam-policy-binding "$DB_SECRET" \
  --member="serviceAccount:$SERVER_SA" --role=roles/secretmanager.secretAccessor >/dev/null
for role in roles/cloudsql.client roles/logging.logWriter roles/monitoring.metricWriter; do
  g projects add-iam-policy-binding "$PROJECT" --condition=None \
    --member="serviceAccount:$SERVER_SA" --role="$role" >/dev/null
done
# Service 2: pull from its subscription only.
g pubsub subscriptions add-iam-policy-binding "$SUBSCRIPTION" \
  --member="serviceAccount:$SERVICE2_SA" --role=roles/pubsub.subscriber >/dev/null
# Monitor function: read and update (start/stop) Cloud SQL instances.
g projects add-iam-policy-binding "$PROJECT" --condition=None \
  --member="serviceAccount:$MONITOR_SA" --role=roles/cloudsql.editor >/dev/null

echo "== 6. Firewall: allow HTTP (port 80) to VMs tagged '$TAG'"
g compute firewall-rules describe "$FIREWALL_RULE" >/dev/null 2>&1 \
  || g compute firewall-rules create "$FIREWALL_RULE" --network=default \
       --direction=INGRESS --allow=tcp:80 --source-ranges=0.0.0.0/0 --target-tags="$TAG"

echo "== 7. Local Python environment for the database scripts (.venv)"
[ -x .venv/bin/python ] || python3 -m venv .venv
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -r requirements-local.txt

# --- Cloud SQL: start it if it exists; otherwise create it and its schema. ---
setup_database() {
  if db_exists; then
    echo "   instance '$DB_INSTANCE' exists"
    if [ "$(db_policy)" != "ALWAYS" ]; then
      echo "   starting it (a minute or two)"
      g sql instances patch "$DB_INSTANCE" --activation-policy=ALWAYS
    else
      echo "   already running"
    fi
  else
    echo "   creating instance '$DB_INSTANCE' (takes 5-10 minutes)"
    g sql instances create "$DB_INSTANCE" \
      --database-version=MYSQL_8_4 --edition=enterprise --tier="$DB_TIER" \
      --region="$REGION" --availability-type=zonal \
      --storage-type=SSD --storage-size=10 --no-backup \
      --root-password="$DB_PASS"
  fi

  # The app user always gets the password stored in Secret Manager.
  if g sql users list --instance="$DB_INSTANCE" --format='value(name)' | grep -qx "$DB_USER"; then
    g sql users set-password "$DB_USER" --host=% --instance="$DB_INSTANCE" --password="$DB_PASS"
  else
    g sql users create "$DB_USER" --host=% --instance="$DB_INSTANCE" --password="$DB_PASS"
  fi

  if g sql databases describe "$DB_NAME" --instance="$DB_INSTANCE" >/dev/null 2>&1; then
    echo "   database '$DB_NAME' exists; skipping schema creation"
  else
    echo "   creating database '$DB_NAME' and its tables"
    DB_PASS="$DB_PASS" .venv/bin/python setup_schema.py
  fi
}
echo "== 8. Cloud SQL"
setup_database

echo "== 9. Static IP '$IP_NAME'"
if ! g compute addresses describe "$IP_NAME" --region="$REGION" >/dev/null 2>&1; then
  g compute addresses create "$IP_NAME" --region="$REGION"
fi
IP=$(g compute addresses describe "$IP_NAME" --region="$REGION" --format='value(address)')
echo "   $IP"

echo "== 10. VMs"
if vm_exists "$SERVER_VM"; then
  echo "   $SERVER_VM exists, skipping (./manage.sh redeploy-server updates its code)"
else
  g compute instances create "$SERVER_VM" \
    --zone="$ZONE" --machine-type="$SERVER_MACHINE" \
    --image-family=debian-12 --image-project=debian-cloud \
    --service-account="$SERVER_SA" --scopes=cloud-platform \
    --tags="$TAG" --address="$IP" \
    --metadata-from-file=startup-script=startup.sh,server-code=server.py,server-requirements=requirements-server.txt
fi

if vm_exists "$SERVICE2_VM"; then
  echo "   $SERVICE2_VM exists, skipping"
else
  g compute instances create "$SERVICE2_VM" \
    --zone="$ZONE" --machine-type=e2-micro \
    --image-family=debian-12 --image-project=debian-cloud \
    --service-account="$SERVICE2_SA" --scopes=cloud-platform \
    --metadata-from-file=startup-script=startup_service2.sh,service2-code=service2/main.py,service2-requirements=service2/requirements.txt
fi

if vm_exists "$CLIENT_VM"; then
  echo "   $CLIENT_VM exists, skipping"
else
  # Debian 13: the provided http-client needs glibc 2.38. No service account:
  # it only sends HTTP requests.
  g compute instances create "$CLIENT_VM" \
    --zone="$ZONE" --machine-type="$CLIENT_MACHINE" \
    --image-family=debian-13 --image-project=debian-cloud \
    --no-service-account --no-scopes
fi
INTERNAL_IP=$(g compute instances describe "$SERVER_VM" --zone="$ZONE" \
  --format='value(networkInterfaces[0].networkIP)')

echo "== 11. Database monitor (hourly Cloud Function)"
if g functions describe "$MONITOR_FN" --region="$REGION" >/dev/null 2>&1; then
  echo "   function exists (./manage.sh deploy-monitor redeploys it)"
else
  g functions deploy "$MONITOR_FN" --gen2 --region="$REGION" --runtime=python312 \
    --source=db_monitor --entry-point=stop_db_if_running \
    --trigger-topic="$MONITOR_TOPIC" \
    --service-account="$MONITOR_SA" --trigger-service-account="$MONITOR_SA" \
    --set-env-vars="PROJECT=$PROJECT,DB_INSTANCE=$DB_INSTANCE" \
    --memory=256Mi --max-instances=1
fi
# The Pub/Sub trigger calls the function as MONITOR_SA.
g functions add-invoker-policy-binding "$MONITOR_FN" --region="$REGION" \
  --member="serviceAccount:$MONITOR_SA" >/dev/null
if [ -z "$(job_state)" ]; then
  g scheduler jobs create pubsub "$MONITOR_JOB" --location="$REGION" \
    --schedule="0 * * * *" --time-zone="America/New_York" \
    --topic="$MONITOR_TOPIC" --message-body="check"
fi
# You're about to work with the database, so pause the monitor until cleanup.sh.
if [ "$(job_state)" = "ENABLED" ]; then
  g scheduler jobs pause "$MONITOR_JOB" --location="$REGION"
fi
echo "   monitor is PAUSED while you work; cleanup.sh (or ./manage.sh monitor-resume) re-enables it"

cat <<EOF

Done. The VMs need 2-3 minutes after first boot to install and start their programs.

  Web server (external):   http://$IP/12k-files/5.html
  Web server (internal):   $INTERNAL_IP   <- the clients on $CLIENT_VM use this
  Database rows:           .venv/bin/python db_tool.py show
  Server logs:             ./manage.sh server-logs

When you're finished, run ./cleanup.sh. It stops the database (it is expensive).
EOF
