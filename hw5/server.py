"""CS528 HW5 - Service 1 web server.

Builds on HW4: serves the 12k files from Cloud Storage, logs errors to Cloud
Logging, and reports banned-country requests to Service 2 through Pub/Sub.

New in HW5:
  * Every request is recorded in Cloud SQL (table `requests`). Requests that
    fail (status other than 200) are also recorded in `failed_requests`.
  * Each request runs in four separately timed stages (time.perf_counter_ns):
        1. parse_request_info()  - read the request line, headers and body
        2. read_file()           - download the file from Cloud Storage
        3. send_text_response()  - write the response to the client
        4. insert_request()      - write the row(s) to the database
    One CSV row per request is appended to TIMINGS_FILE.
  * A fixed pool of worker threads, so concurrent clients are served in
    parallel and each thread reuses its own Cloud Storage client.
"""
import csv
import functools
import json
import logging
import os
import re
import signal
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Optional
from urllib.parse import unquote, urlsplit

import sqlalchemy
from google.api_core.exceptions import NotFound
from google.cloud import logging as gcp_logging
from google.cloud import pubsub_v1, secretmanager, storage

PROJECT = "project-f131ec20-0df6-4cfa-bf0"
REGION = "us-central1"
BUCKET = "cs528-12kfiles-bucket-thomas"
PREFIX = "12k-files/"
TOPIC = "forbidden-requests"

DB_INSTANCE = "hw5-db"
DB_NAME = "hw5"
DB_USER = "hw5app"
DB_SECRET = "hw5-db-pass"
INSTANCE_CONNECTION_NAME = f"{PROJECT}:{REGION}:{DB_INSTANCE}"

HOST = "0.0.0.0"
PORT = int(os.environ.get("PORT", "8080"))          # 80 on the VM
WORKERS = int(os.environ.get("WORKERS", "16"))      # worker threads
TIMINGS_FILE = os.environ.get("TIMINGS_FILE", "timings.csv")
# Optional: point at another database for local testing (e.g. sqlite:///t.db).
DB_URL = os.environ.get("DB_URL")

# ---------------------------------------------------------------- logging --

gcp_logging.Client(project=PROJECT).setup_logging(log_level=logging.INFO)
logger = logging.getLogger("hw5-service1")

LEVELS = {"INFO": logging.INFO, "WARNING": logging.WARNING,
          "ERROR": logging.ERROR, "CRITICAL": logging.CRITICAL}


def log(severity, message, **fields):
    """Write one structured log entry to Cloud Logging."""
    logger.log(LEVELS[severity], message, extra={"json_fields": fields})


def norm(s):
    return s.strip().lower().replace("_", " ").replace("-", " ")


FORBIDDEN = {norm(c) for c in [
    "North Korea", "Iran", "Cuba", "Myanmar", "Iraq",
    "Libya", "Sudan", "Zimbabwe", "Syria",
]}

# ---------------------------------------------------------- cloud clients --

_local = threading.local()


def get_bucket():
    """One Cloud Storage client per worker thread, created on first use."""
    bucket = getattr(_local, "bucket", None)
    if bucket is None:
        bucket = _local.bucket = storage.Client(project=PROJECT).bucket(BUCKET)
    return bucket


publisher = pubsub_v1.PublisherClient()   # thread-safe, shared
topic_path = publisher.topic_path(PROJECT, TOPIC)


def _publish_done(future):
    try:
        future.result()
    except Exception as e:  # noqa: BLE001 - report any publish failure
        log("ERROR", "pubsub publish failed", error=str(e))


def report_forbidden(country, path):
    """Send the banned request to Service 2 without blocking the response."""
    data = json.dumps({"country": country, "path": path}).encode()
    publisher.publish(topic_path, data).add_done_callback(_publish_done)

# --------------------------------------------------------------- database --


@functools.lru_cache(maxsize=1)
def db_password():
    """Database password, read once from Secret Manager."""
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{PROJECT}/secrets/{DB_SECRET}/versions/latest"
    return client.access_secret_version(name=name).payload.data.decode().strip()


def make_engine():
    if DB_URL:
        return sqlalchemy.create_engine(DB_URL)

    # The Cloud SQL Python Connector authorizes with the VM's service account
    # (Cloud SQL Client role) and encrypts the connection; no IP allow-listing.
    from google.cloud.sql.connector import Connector
    connector = Connector()

    def getconn():
        return connector.connect(INSTANCE_CONNECTION_NAME, "pymysql",
                                 user=DB_USER, password=db_password(), db=DB_NAME)

    # One pooled connection per worker thread; connections are opened lazily,
    # so the web server still starts (and serves files) if the DB is stopped.
    return sqlalchemy.create_engine("mysql+pymysql://", creator=getconn,
                                    pool_size=WORKERS, max_overflow=2,
                                    pool_pre_ping=True, pool_recycle=1800)


engine = make_engine()

INSERT_REQUEST = sqlalchemy.text(
    "INSERT INTO requests (country, client_ip, gender, age, income, is_banned,"
    " time_of_day, requested_file, status_code) VALUES (:country, :client_ip,"
    " :gender, :age, :income, :is_banned, :time_of_day, :requested_file,"
    " :status_code)")
INSERT_FAILED = sqlalchemy.text(
    "INSERT INTO failed_requests (request_time, requested_file, error_code)"
    " VALUES (:request_time, :requested_file, :error_code)")

_last_db_error_log = 0.0
_db_error_lock = threading.Lock()


def log_db_error(e):
    """Log database failures at most once every 10 s, so a stopped database
    doesn't flood Cloud Logging with one entry per request."""
    global _last_db_error_log
    with _db_error_lock:
        now = time.monotonic()
        if now - _last_db_error_log < 10:
            return
        _last_db_error_log = now
    log("ERROR", "database insert failed", error=str(e)[:500])

# ---------------------------------------------------------------- timings --


def us(ns):
    """Nanoseconds -> microseconds for the CSV (blank when a stage didn't run)."""
    return "" if ns is None else round(ns / 1000, 1)


class TimingLog:
    FIELDS = ["method", "status", "parse_us", "read_us", "send_us", "db_us",
              "total_us"]

    def __init__(self, path):
        new = not os.path.exists(path) or os.path.getsize(path) == 0
        self._f = open(path, "a", newline="")
        self._w = csv.writer(self._f)
        self._lock = threading.Lock()
        self._n = 0
        if new:
            self._w.writerow(self.FIELDS)
            self._f.flush()

    def record(self, *row):
        with self._lock:
            self._w.writerow(row)
            self._n += 1
            if self._n % 200 == 0:
                self._f.flush()

    def close(self):
        with self._lock:
            self._f.flush()
            self._f.close()


timings = TimingLog(TIMINGS_FILE)

# ---------------------------------------------------------------- helpers --


@dataclass
class RequestInfo:
    method: str
    path: str
    file: str
    country: Optional[str]
    client_ip: str
    gender: Optional[str]
    age: Optional[str]
    income: Optional[str]
    time_of_day: datetime
    is_banned: bool


def resolve_file_name(name):
    """Map the client's 12k-files/N.html paths to the bucket's file_N.txt."""
    name = name.lstrip("/").removeprefix("12k-files/")
    m = re.fullmatch(r"(\d+)\.html", name)
    return f"file_{m.group(1)}.txt" if m else name


def parse_time(value):
    """X-time looks like '2026-10-08 04:00:00'. Fall back to the server's UTC
    clock for requests without it (e.g. curl)."""
    if value:
        try:
            return datetime.strptime(value.strip(), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


def clip(value, n):
    return None if value is None else value[:n]


def read_file(name):
    """Stage 2: one round trip to Cloud Storage."""
    return get_bucket().blob(PREFIX + name).download_as_text()


def insert_request(info, status):
    """Stage 4: record the request, plus a failed_requests row if it failed."""
    try:
        with engine.begin() as conn:   # one transaction for both rows
            conn.execute(INSERT_REQUEST, {
                "country": clip(info.country, 64),
                "client_ip": clip(info.client_ip, 45),
                "gender": clip(info.gender, 16),
                "age": clip(info.age, 16),
                "income": clip(info.income, 16),
                "is_banned": info.is_banned,
                "time_of_day": info.time_of_day,
                "requested_file": clip(info.file, 255),
                "status_code": status,
            })
            if status != 200:
                conn.execute(INSERT_FAILED, {
                    "request_time": info.time_of_day,
                    "requested_file": clip(info.file, 255),
                    "error_code": status,
                })
    except Exception as e:  # noqa: BLE001 - never crash a request over the DB
        log_db_error(e)

# ---------------------------------------------------------------- handler --


class Handler(BaseHTTPRequestHandler):
    timeout = 30   # seconds; a stalled client can't hold a worker forever

    def log_message(self, format, *args):
        pass  # silence the built-in per-request access log

    def handle_one(self):
        t0 = time.perf_counter_ns()
        info = self.parse_request_info()                       # stage 1
        t1 = time.perf_counter_ns()
        status, text, read_ns = self.process(info)             # stage 2 inside
        t2 = time.perf_counter_ns()
        self.send_text_response(text, status,                  # stage 3
                                include_body=self.command != "HEAD")
        t3 = time.perf_counter_ns()
        insert_request(info, status)                           # stage 4
        t4 = time.perf_counter_ns()
        timings.record(self.command, status, us(t1 - t0), us(read_ns),
                       us(t3 - t2), us(t4 - t3), us(t4 - t0))

    do_GET = do_POST = do_PUT = do_DELETE = do_HEAD = handle_one
    do_CONNECT = do_OPTIONS = do_TRACE = do_PATCH = handle_one

    # Stage 1 ------------------------------------------------------------

    def parse_request_info(self):
        h = self.headers

        def header(name):
            value = (h.get(name) or "").strip()
            return value or None

        if self.command == "POST":
            name = self.read_post_file_name()
        else:
            name = unquote(urlsplit(self.path).path)
        country = header("X-country")
        return RequestInfo(
            method=self.command,
            path=self.path,
            file=resolve_file_name(name),
            country=country,
            client_ip=header("X-client-IP") or self.client_address[0],
            gender=header("X-gender"),
            age=header("X-age"),
            income=header("X-income"),
            time_of_day=parse_time(header("X-time")),
            is_banned=bool(country) and norm(country) in FORBIDDEN,
        )

    def read_post_file_name(self):
        # Expected payload: {"file": "file_5.txt"} or {"file": "12k-files/5.html"}
        try:
            length = int(self.headers.get("Content-Length", 0) or 0)
            raw = self.rfile.read(length) if length > 0 else b""
            return str(json.loads(raw).get("file", ""))
        except (ValueError, AttributeError):
            return ""  # bad Content-Length, invalid JSON, or not a JSON object

    # Decide the response (calls stage 2) --------------------------------

    def process(self, info):
        """Returns (status, body text, Cloud Storage read time in ns or None)."""
        client = info.client_ip
        if info.method not in ("GET", "POST"):
            log("ERROR", "501 not implemented",
                method=info.method, path=info.path, client=client)
            return 501, "Not implemented", None

        if info.is_banned:
            log("CRITICAL", "forbidden country request", country=info.country,
                path=info.path, method=info.method, client=client)
            report_forbidden(info.country, info.path)
            return 400, "Permission denied", None

        if not info.file.endswith(".txt") or "/" in info.file:
            log("WARNING", "404 invalid file name",
                file=info.file, method=info.method, client=client)
            return 404, "File not found", None

        start = time.perf_counter_ns()
        try:
            status, text = 200, read_file(info.file)
        except NotFound:
            log("WARNING", "404 file not found",
                file=info.file, method=info.method, client=client)
            status, text = 404, "File not found"
        except Exception as e:  # noqa: BLE001 - permissions, network, ...
            log("ERROR", "500 storage error",
                file=info.file, error=str(e), client=client)
            status, text = 500, "Internal server error"
        return status, text, time.perf_counter_ns() - start

    # Stage 3 ------------------------------------------------------------

    def send_text_response(self, text, status_code=200, include_body=True):
        body = text.encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))  # bytes, not chars
        self.end_headers()
        if include_body:
            self.wfile.write(body)
        self.wfile.flush()

# ----------------------------------------------------------------- server --


class PooledHTTPServer(HTTPServer):
    """HTTPServer that hands each connection to a fixed pool of threads."""
    allow_reuse_address = True
    request_queue_size = 128

    def __init__(self, address, handler, workers):
        super().__init__(address, handler)
        self.pool = ThreadPoolExecutor(max_workers=workers,
                                       thread_name_prefix="worker")

    def process_request(self, request, client_address):
        self.pool.submit(self._work, request, client_address)

    def _work(self, request, client_address):
        try:
            self.finish_request(request, client_address)
        except Exception:  # noqa: BLE001
            self.handle_error(request, client_address)
        finally:
            self.shutdown_request(request)

    def server_close(self):
        super().server_close()
        self.pool.shutdown(wait=True)


def _stop(signum, frame):
    raise KeyboardInterrupt  # systemd stop -> flush timings and exit cleanly


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, _stop)
    server = PooledHTTPServer((HOST, PORT), Handler, WORKERS)
    print(f"Serving on {HOST}:{PORT} with {WORKERS} workers", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        timings.close()
