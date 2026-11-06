#!/bin/bash
# shellcheck disable=SC2034  # variables are used by the scripts that source this file
# Shared settings for setup.sh, cleanup.sh and manage.sh (sourced, not run).
# The project ID is hardcoded on purpose, as the assignment requires.

PROJECT="project-f131ec20-0df6-4cfa-bf0"
REGION="us-central1"
ZONE="us-central1-b"
BUCKET="cs528-12kfiles-bucket-thomas"

# Pub/Sub path to Service 2 (same names as HW4, since Service 2 is unmodified)
TOPIC="forbidden-requests"
SUBSCRIPTION="forbidden-sub"

# Service accounts
SERVER_SA_NAME="hw5-sa"           # web server
SERVICE2_SA_NAME="hw5-sa2"        # Service 2
MONITOR_SA_NAME="hw5-monitor-sa"  # database-stopping Cloud Function
SERVER_SA="${SERVER_SA_NAME}@${PROJECT}.iam.gserviceaccount.com"
SERVICE2_SA="${SERVICE2_SA_NAME}@${PROJECT}.iam.gserviceaccount.com"
MONITOR_SA="${MONITOR_SA_NAME}@${PROJECT}.iam.gserviceaccount.com"

# Cloud SQL
DB_INSTANCE="hw5-db"
DB_NAME="hw5"
DB_USER="hw5app"
DB_SECRET="hw5-db-pass"           # Secret Manager secret holding the password
DB_TIER="db-g1-small"             # shared core, 1.7 GB RAM

# VMs and networking
SERVER_VM="web-server-hw5"
SERVER_MACHINE="e2-medium"        # 2 vCPUs, 4 GB: room for 2 concurrent clients
SERVICE2_VM="hw5-service2"
CLIENT_VM="hw5-client"
CLIENT_MACHINE="e2-small"
IP_NAME="hw5-server-ip"
TAG="hw5-http"
FIREWALL_RULE="hw5-allow-http"

# Database monitor (Cloud Scheduler -> Pub/Sub -> Cloud Function)
MONITOR_FN="hw5-db-monitor"
MONITOR_TOPIC="hw5-db-monitor-tick"
MONITOR_JOB="hw5-db-monitor-hourly"

g() { gcloud --project="$PROJECT" --quiet "$@"; }
vm_exists() { g compute instances describe "$1" --zone="$ZONE" >/dev/null 2>&1; }
db_exists() { g sql instances describe "$DB_INSTANCE" >/dev/null 2>&1; }
db_policy() { g sql instances describe "$DB_INSTANCE" --format='value(settings.activationPolicy)'; }
job_state() { g scheduler jobs describe "$MONITOR_JOB" --location="$REGION" --format='value(state)' 2>/dev/null || true; }
