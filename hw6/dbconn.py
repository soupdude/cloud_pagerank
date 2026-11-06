"""Connect to the Cloud SQL database (from the HW6 VM, or from your laptop).

Credentials: Application Default Credentials when available (on the VM, its
service account), otherwise your gcloud login (`gcloud auth print-access-token`).
The database password is read from Secret Manager.
"""
import contextlib
import os
import subprocess

import google.auth
from google.auth.exceptions import DefaultCredentialsError
from google.cloud import secretmanager
from google.cloud.sql.connector import Connector
from google.oauth2.credentials import Credentials

PROJECT = "project-f131ec20-0df6-4cfa-bf0"
REGION = "us-central1"
BUCKET = "cs528-12kfiles-bucket-thomas"
DB_INSTANCE = "hw5-db"
DB_USER = "hw5app"
DB_SECRET = "hw5-db-pass"
INSTANCE_CONNECTION_NAME = f"{PROJECT}:{REGION}:{DB_INSTANCE}"


def credentials():
    try:
        creds, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"])
        return creds
    except DefaultCredentialsError:
        token = subprocess.run(["gcloud", "auth", "print-access-token"],
                               check=True, capture_output=True, text=True).stdout.strip()
        return Credentials(token)


def db_password(creds):
    if os.environ.get("DB_PASS"):
        return os.environ["DB_PASS"]
    client = secretmanager.SecretManagerServiceClient(credentials=creds)
    name = f"projects/{PROJECT}/secrets/{DB_SECRET}/versions/latest"
    return client.access_secret_version(name=name).payload.data.decode().strip()


@contextlib.contextmanager
def connect(db=None):
    """Yields an autocommit pymysql connection to database `db` (None: no default)."""
    creds = credentials()
    connector = Connector(credentials=creds)
    conn = None
    try:
        conn = connector.connect(INSTANCE_CONNECTION_NAME, "pymysql",
                                 user=DB_USER, password=db_password(creds), db=db,
                                 autocommit=True)
        yield conn
    finally:
        if conn is not None:
            conn.close()
        connector.close()
