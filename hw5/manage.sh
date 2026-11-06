#!/bin/bash
# Start, stop and inspect the HW5 resources.  Run ./manage.sh with no arguments
# for the list of commands.
set -euo pipefail
cd "$(dirname "$0")"
source ./config.sh

usage() {
  cat <<'EOF'
Usage: ./manage.sh COMMAND

Database
  db-start          start the Cloud SQL instance
  db-stop           stop the Cloud SQL instance (data is kept)
  db-status         show whether it is running

Database monitor (hourly Cloud Function that stops the database)
  monitor-pause     pause it while you're actively using the database
  monitor-resume    re-enable it when you're done
  monitor-run       trigger it once now
  monitor-logs      show its recent log entries
  deploy-monitor    redeploy the function after changing db_monitor/

VMs
  vms-start         start the three VMs
  vms-stop          stop the three VMs without deleting them
  redeploy-server   ship the current server.py to the web server and reboot it
  server-logs       last 30 lines of the web server's output
  service2-logs     last 30 lines of Service 2's output

Load test
  copy-client PATH  copy the provided http-client and run_clients.sh to the client VM
  load-test [N]     start 2 clients x N requests (default 50000) on the client VM
  client-status     show the last lines of both client logs
  fetch-timings     download the server's timings to ./timings.csv
  reset-timings     delete the server's timings file (before a fresh run)
EOF
}

server_internal_ip() {
  g compute instances describe "$SERVER_VM" --zone="$ZONE" \
    --format='value(networkInterfaces[0].networkIP)'
}

case "${1:-}" in
  db-start)        g sql instances patch "$DB_INSTANCE" --activation-policy=ALWAYS ;;
  db-stop)         g sql instances patch "$DB_INSTANCE" --activation-policy=NEVER ;;
  db-status)       g sql instances describe "$DB_INSTANCE" \
                     --format='table(name,state,settings.activationPolicy,settings.tier)' ;;

  monitor-pause)   g scheduler jobs pause "$MONITOR_JOB" --location="$REGION" ;;
  monitor-resume)  g scheduler jobs resume "$MONITOR_JOB" --location="$REGION" ;;
  monitor-run)     g scheduler jobs run "$MONITOR_JOB" --location="$REGION"
                   echo "Triggered. See ./manage.sh monitor-logs in about a minute." ;;
  monitor-logs)    g functions logs read "$MONITOR_FN" --region="$REGION" --limit=20 ;;
  deploy-monitor)  g functions deploy "$MONITOR_FN" --gen2 --region="$REGION" --runtime=python312 \
                     --source=db_monitor --entry-point=stop_db_if_running \
                     --trigger-topic="$MONITOR_TOPIC" \
                     --service-account="$MONITOR_SA" --trigger-service-account="$MONITOR_SA" \
                     --set-env-vars="PROJECT=$PROJECT,DB_INSTANCE=$DB_INSTANCE" \
                     --memory=256Mi --max-instances=1 ;;

  vms-start)       g compute instances start "$SERVER_VM" "$SERVICE2_VM" "$CLIENT_VM" --zone="$ZONE" ;;
  vms-stop)        g compute instances stop "$SERVER_VM" "$SERVICE2_VM" "$CLIENT_VM" --zone="$ZONE" ;;
  redeploy-server) g compute instances add-metadata "$SERVER_VM" --zone="$ZONE" \
                     --metadata-from-file=server-code=server.py,server-requirements=requirements-server.txt
                   g compute instances reset "$SERVER_VM" --zone="$ZONE"
                   echo "Rebooting; the startup script restarts the server with the new code." ;;
  server-logs)     g compute ssh "$SERVER_VM" --zone="$ZONE" \
                     --command='sudo journalctl -u hw5-server -n 30 --no-pager' ;;
  service2-logs)   g compute ssh "$SERVICE2_VM" --zone="$ZONE" \
                     --command='sudo journalctl -u hw5-service2 -n 30 --no-pager' ;;

  copy-client)     src="${2:?usage: ./manage.sh copy-client PATH_TO_http-client}"
                   g compute scp "$src" run_clients.sh "$CLIENT_VM":~ --zone="$ZONE" ;;
  load-test)       ip=$(server_internal_ip)
                   g compute ssh "$CLIENT_VM" --zone="$ZONE" \
                     --command="~/run_clients.sh $ip ${2:-50000}" ;;
  client-status)   g compute ssh "$CLIENT_VM" --zone="$ZONE" \
                     --command='for f in client1.log client2.log; do echo "== $f ($(grep -cE "^[0-9]{3} " $f) responses)"; tail -n 3 $f; done' ;;
  fetch-timings)   g compute ssh "$SERVER_VM" --zone="$ZONE" \
                     --command='sudo cat /var/lib/hw5/timings.csv' > timings.csv
                   echo "Saved timings.csv ($(($(wc -l < timings.csv) - 1)) requests)."
                   echo "Summarize with: python3 analyze_timings.py timings.csv" ;;
  reset-timings)   g compute ssh "$SERVER_VM" --zone="$ZONE" \
                     --command='sudo systemctl stop hw5-server && sudo rm -f /var/lib/hw5/timings.csv && sudo systemctl start hw5-server' ;;

  *)               usage; exit 1 ;;
esac
