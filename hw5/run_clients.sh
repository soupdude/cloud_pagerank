#!/bin/bash
# Runs ON the client VM. Starts two http-clients at once, with the same random
# seed, against the web server. They keep running if you disconnect.
#
#   ./run_clients.sh SERVER_INTERNAL_IP [REQUESTS_PER_CLIENT] [SEED]
#
# Progress:  tail -f client1.log client2.log
# Finished:  both logs end with an "ended" line.
set -euo pipefail
SERVER="${1:?usage: ./run_clients.sh SERVER_INTERNAL_IP [REQUESTS] [SEED]}"
N="${2:-50000}"
SEED="${3:-528}"
cd "$(dirname "$0")"
chmod +x ./http-client

for i in 1 2; do
  nohup bash -c "echo \"started \$(date '+%F %T')\"; \
    ./http-client -d '$SERVER' -p 80 -b '' -w 12k-files -n '$N' -i 11999 -r '$SEED' -v; \
    echo \"ended \$(date '+%F %T')\"" > "client$i.log" 2>&1 < /dev/null &
  echo "client $i started (pid $!), logging to client$i.log"
done
echo "Both clients use seed $SEED and send $N requests each."
