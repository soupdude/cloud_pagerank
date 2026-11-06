"""CS528 HW5 - Cloud Function that stops the Cloud SQL instance if it's running.

Cloud Scheduler publishes to a Pub/Sub topic every hour, which triggers this
function. "Stopping" a Cloud SQL instance means setting its activation policy
to NEVER; the instance and its data are kept, and only storage is billed.

Pause the schedule while you're actively using the database:
    ./manage.sh monitor-pause      (and ./manage.sh monitor-resume afterwards)
"""
import json
import os

import functions_framework
from googleapiclient import discovery

PROJECT = os.environ.get("PROJECT", "project-f131ec20-0df6-4cfa-bf0")
INSTANCE = os.environ.get("DB_INSTANCE", "hw5-db")


def log(severity, message, **fields):
    # Cloud Run turns JSON lines with a "severity" field into structured logs.
    print(json.dumps({"severity": severity, "message": message, **fields}),
          flush=True)


@functions_framework.cloud_event
def stop_db_if_running(cloud_event):
    sqladmin = discovery.build("sqladmin", "v1beta4", cache_discovery=False)
    instance = sqladmin.instances().get(project=PROJECT, instance=INSTANCE).execute()
    state = instance.get("state")                                # e.g. RUNNABLE
    policy = instance.get("settings", {}).get("activationPolicy")  # ALWAYS / NEVER

    if policy != "ALWAYS":
        log("INFO", "database is not running; nothing to do",
            instance=INSTANCE, state=state, activation_policy=policy)
        return

    op = sqladmin.instances().patch(
        project=PROJECT, instance=INSTANCE,
        body={"settings": {"activationPolicy": "NEVER"}},
    ).execute()
    log("NOTICE", "database was running; stop requested",
        instance=INSTANCE, state=state, operation=op.get("name"))
