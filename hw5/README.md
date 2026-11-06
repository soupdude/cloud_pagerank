# CS528 HW5: Cloud SQL, instrumentation and load testing

HW5 builds on the HW4 web server (Service 1) and Service 2:

- **Web server** (`server.py`, VM `web-server-hw5`): serves the 12k files from Cloud Storage. It now records every request in Cloud SQL, and records failed requests in a separate table. It also times each stage of a request.
- **Service 2** (`service2/main.py`, VM `hw5-service2`): unchanged from HW4. It prints banned-country requests it receives from Pub/Sub.
- **Database** (Cloud SQL for MySQL 8.4, instance `hw5-db`, database `hw5`).
- **Database monitor** (`db_monitor/main.py`): a Cloud Function that Cloud Scheduler triggers every hour through Pub/Sub. It stops the database if it is running.
- **Client VM** (`hw5-client`): runs the two provided `http-client`s for the load test.

## Files

| File | What it does |
|---|---|
| `setup.sh` | Creates or starts everything (APIs, service accounts, roles, secret, Pub/Sub, firewall, Cloud SQL and its schema, static IP, VMs, monitor) |
| `cleanup.sh` | Deletes the VMs, releases the static IP, removes the firewall rule, **stops** (doesn't delete) the database, and re-enables the monitor |
| `startup.sh` | Web server VM startup script: installs once, then refreshes the code and restarts the service on every boot |
| `startup_service2.sh` | The same, for the Service 2 VM |
| `setup_schema.py` | Creates the `hw5` database and its two tables (called by `setup.sh`) |
| `manage.sh` | Starts and stops resources, pauses and resumes the monitor, runs the load test, fetches timings |
| `config.sh` | Names and the hardcoded project ID, shared by the scripts |
| `server.py`, `requirements-server.txt` | The modified web server |
| `service2/` | The unmodified Service 2 |
| `db_monitor/` | The Cloud Function that stops the database |
| `db_tool.py`, `dbconn.py` | Show the tables, compute the part 7 statistics, empty the tables |
| `analyze_timings.py` | Summarizes the part 6 timings |
| `run_clients.sh` | Runs on the client VM: starts both clients with the same seed |

## Configure and run

### Prerequisites
- `gcloud` logged in as the project owner (`gcloud auth login`).
- `python3` with `venv`. On Debian or Ubuntu, `sudo apt install python3-venv`. Cloud Shell has both.
- The scripts must be executable: `chmod +x *.sh`. Commit them that way, since git keeps the executable bit.

### 1. Provision everything

```bash
cd hw5
./setup.sh
```

The first run takes about 15 minutes, mostly creating the Cloud SQL instance. Later runs start the stopped database and skip everything that already exists. `setup.sh` pauses the database monitor, because you are about to use the database. `cleanup.sh` turns it back on.

Allow 2–3 minutes after the VMs are created for the startup scripts to finish. Check with `./manage.sh server-logs`, which should show `Serving on 0.0.0.0:80 with 16 workers`.

### 2. curl demo (part 4)

Set `IP` to the external IP that `setup.sh` printed. Then show the tables before and after each request, and screenshot each step:

```bash
.venv/bin/python db_tool.py show                              # before
curl -i http://$IP/12k-files/5.html                           # 200
.venv/bin/python db_tool.py show
curl -i http://$IP/nope.txt                                   # 404
.venv/bin/python db_tool.py show
curl -i -X DELETE http://$IP/12k-files/5.html                 # 501
.venv/bin/python db_tool.py show
```

The 200 adds a row to `requests` only. Each error adds a row to `requests` and a row to `failed_requests`. curl sends no `X-*` headers, so those columns are NULL, `client_ip` is your laptop's address, and `time_of_day` is the server's clock. A banned-country request also makes a good error example: `curl -i -H "X-country: Iran" http://$IP/12k-files/5.html` returns 400.

### 3. Load test: 2 clients × 50,000 requests (part 5)

```bash
.venv/bin/python db_tool.py reset --yes     # start the statistics from empty tables
./manage.sh reset-timings                   # and the timings
./manage.sh copy-client ~/Downloads/http-client
./manage.sh load-test 50000                 # both clients, same seed (528), internal IP
./manage.sh client-status                   # check progress now and then
```

Both clients run in the background on the client VM, so you can close your laptop. When each log ends with an `ended` line, the run is finished.

### 4. Timings (part 6)

```bash
./manage.sh fetch-timings
python3 analyze_timings.py timings.csv
```

### 5. Statistics (part 7)

```bash
.venv/bin/python db_tool.py stats
```

The output prints each SQL query with its result, so you can copy both into the report.

### 6. Tear down

```bash
./cleanup.sh
```

The database monitor stops the database within an hour if it is ever left running. Pause it during long runs with `./manage.sh monitor-pause`, and resume it afterwards with `./manage.sh monitor-resume`. To test it, start the database, then run `./manage.sh monitor-run` and `./manage.sh monitor-logs`.

## Database schema

```sql
CREATE TABLE requests (
    id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    country        VARCHAR(64),
    client_ip      VARCHAR(45),
    gender         VARCHAR(16),
    age            VARCHAR(16),
    income         VARCHAR(16),
    is_banned      BOOLEAN NOT NULL DEFAULT FALSE,
    time_of_day    DATETIME NOT NULL,
    requested_file VARCHAR(255),
    status_code    SMALLINT NOT NULL,
    PRIMARY KEY (id)
);

CREATE TABLE failed_requests (
    id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    request_time   DATETIME NOT NULL,
    requested_file VARCHAR(255),
    error_code     SMALLINT NOT NULL,
    PRIMARY KEY (id)
);
```

Each column comes from a request header the client sends. A capture of one request shows them:

| Column | Source |
|---|---|
| `country` | `X-country` |
| `client_ip` | `X-client-IP` (falls back to the TCP peer address) |
| `gender` | `X-gender` |
| `age` | `X-age` (an age group, e.g. `46-55`) |
| `income` | `X-income` (an income group, e.g. `60k-100k`) |
| `time_of_day` | `X-time`, e.g. `2026-10-08 04:00:00` (falls back to the server's UTC time) |
| `is_banned` | Computed: `X-country` is on the banned list |
| `requested_file` | Request path (GET) or JSON body (POST), mapped to `file_N.txt` |
| `status_code` | The status the server returned |

**Design notes**
- Both tables use a surrogate auto-increment primary key, because two requests can share every other value. Running both clients with the same seed produces exactly such pairs.
- `requests` is deliberately not in 3NF. `is_banned` depends on `country`, not on the key (a transitive dependency). Normalizing it would add a join to every insert and to the statistics queries. Instead, the table is denormalized for write speed and simple queries, the trade-off described in Lecture 13.
- `failed_requests` holds only the time, the file and the error code, as the assignment specifies. Failed requests are also in `requests`, so the statistics can cover every request.

## How the server talks to the database
- The VM's service account (`hw5-sa`) has the **Cloud SQL Client** role. The server connects through the **Cloud SQL Python Connector**, which authorizes with IAM and encrypts the connection. No IP allow-listing is needed.
- The database password is generated by `setup.sh` and kept in **Secret Manager** (`hw5-db-pass`). Only `hw5-sa` can read it, and it never appears in the code, the repository or the VM's metadata.
- The connection uses the instance's public IP. A private IP is more secure but needs VPC peering. Either way, the connector rejects anything not authorized through IAM.
- The other roles on `hw5-sa` are the same least-privilege set as in HW4: read the one bucket, publish to the one topic, and write logs and metrics.

## Handling 2 concurrent clients (part 5)
- The server uses a fixed pool of 16 worker threads, where HW4 handled one request at a time. Each thread keeps its own Cloud Storage client and pooled database connection. Most of a request's time is spent waiting on Cloud Storage and the database, so threads overlap that waiting well, despite Python's GIL.
- The VM is an `e2-medium` (2 vCPUs, 4 GB RAM): one vCPU per client, with plenty of memory headroom.
- Pub/Sub publishing no longer waits for confirmation (`.result()`); a callback logs any failure. This removes the blocking that HW4 flagged.

## Instrumentation (part 6)
Each request runs in four separate functions, each timed with `time.perf_counter_ns()`:

| Stage | Function |
|---|---|
| Process the request and extract headers | `parse_request_info()` |
| Read the file from Cloud Storage | `read_file()` |
| Send the response | `send_text_response()` |
| Insert into the database | `insert_request()` |

Each request appends one CSV row to `/var/lib/hw5/timings.csv` on the server. The database insert happens after the response is sent, so it doesn't add to the client's wait.

## Report checklist
- [ ] Setup and run steps (this README)
- [ ] Database schema (above)
- [ ] Screenshots of the curl demo, showing the tables before and after each request (section 2)
- [ ] Part 6: the `analyze_timings.py` table, with a sentence on which stage dominates
- [ ] Part 7: the `db_tool.py stats` output
- [ ] Total cloud spend (Billing → Reports, filtered to the project), or `billing_report.pdf` the next day
