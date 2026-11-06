#!/bin/bash
# CS528 HW5: tears down what setup.sh created, so nothing keeps billing.
#   - deletes the three VMs
#   - releases the static IP and removes the firewall rule
#   - STOPS (does not delete) the Cloud SQL instance
#   - re-enables the hourly database monitor
# Service accounts, Pub/Sub topics, the secret and the monitor function cost
# nothing while idle and are kept, so setup.sh can reuse them.
set -euo pipefail
cd "$(dirname "$0")"
source ./config.sh

echo "== 1. Deleting VMs"
vms=()
for vm in "$SERVER_VM" "$SERVICE2_VM" "$CLIENT_VM"; do
  if vm_exists "$vm"; then vms+=("$vm"); else echo "   $vm not found"; fi
done
if [ "${#vms[@]}" -gt 0 ]; then
  g compute instances delete "${vms[@]}" --zone="$ZONE"
fi

echo "== 2. Releasing static IP '$IP_NAME'"
if g compute addresses describe "$IP_NAME" --region="$REGION" >/dev/null 2>&1; then
  g compute addresses delete "$IP_NAME" --region="$REGION"
else
  echo "   not found"
fi

echo "== 3. Removing firewall rule '$FIREWALL_RULE'"
if g compute firewall-rules describe "$FIREWALL_RULE" >/dev/null 2>&1; then
  g compute firewall-rules delete "$FIREWALL_RULE"
else
  echo "   not found"
fi

echo "== 4. Stopping Cloud SQL instance '$DB_INSTANCE' (kept, not deleted)"
if db_exists; then
  if [ "$(db_policy)" = "ALWAYS" ]; then
    g sql instances patch "$DB_INSTANCE" --activation-policy=NEVER
  else
    echo "   already stopped"
  fi
else
  echo "   not found"
fi

echo "== 5. Re-enabling the hourly database monitor"
case "$(job_state)" in
  PAUSED)  g scheduler jobs resume "$MONITOR_JOB" --location="$REGION" ;;
  ENABLED) echo "   already enabled" ;;
  *)       echo "   not found" ;;
esac

echo "Cleanup complete."
