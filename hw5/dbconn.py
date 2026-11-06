"""Connect to the HW5 Cloud SQL database from your laptop or Cloud Shell.

Used by setup_schema.py and db_tool.py. It borrows your gcloud login
(`gcloud auth print-access-token`), so no `application-default login` is
needed, and reads the database password from Secret Manager.
"""
import contextlib
import os
import subprocess

from google.cloud.sql.connector import Connector
from google.oauth2.credentials import Credentials

PROJECT = "project-f131ec20-0df6-4cfa-bf0"
REGION = "us-central1"
DB_INSTANCE = "hw5-db"
DB_NAME = "hw5"
DB_USER = "hw5app"
DB_SECRET = "hw5-db-pass"
INSTANCE_CONNECTION_NAME = f"{PROJECT}:{REGION}:{DB_INSTANCE}"


def gcloud(*args):
    result = subprocess.run(["gcloud", *args, f"--project={PROJECT}"],
                            check=True, capture_output=True, text=True)
    return result.stdout.strip()


@contextlib.contextmanager
def connect(db=DB_NAME):
    """Yields an autocommit pymysql connection. db=None connects to no database."""
    password = os.environ.get("DB_PASS") or gcloud(
        "secrets", "versions", "access", "latest", f"--secret={DB_SECRET}")
    token = gcloud("auth", "print-access-token")
    connector = Connector(credentials=Credentials(token))
    conn = None
    try:
        conn = connector.connect(INSTANCE_CONNECTION_NAME, "pymysql",
                                 user=DB_USER, password=password, db=db,
                                 autocommit=True)
        yield conn
    finally:
        if conn is not None:
            conn.close()
        connector.close()
