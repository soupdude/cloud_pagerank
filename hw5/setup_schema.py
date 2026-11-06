"""Create the HW5 database and its tables. Safe to run more than once.

Called by setup.sh after it creates the Cloud SQL instance.
"""
from dbconn import DB_NAME, connect

TABLES = [
    # One row per request the web server receives, successful or not.
    """
    CREATE TABLE IF NOT EXISTS requests (
        id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        country        VARCHAR(64),
        client_ip      VARCHAR(45),          -- long enough for IPv6
        gender         VARCHAR(16),
        age            VARCHAR(16),          -- an age group, e.g. '46-55'
        income         VARCHAR(16),          -- an income group, e.g. '60k-100k'
        is_banned      BOOLEAN NOT NULL DEFAULT FALSE,
        time_of_day    DATETIME NOT NULL,    -- from the X-time header
        requested_file VARCHAR(255),
        status_code    SMALLINT NOT NULL,
        PRIMARY KEY (id)
    ) ENGINE=InnoDB
    """,
    # One row per request that returned anything other than 200.
    """
    CREATE TABLE IF NOT EXISTS failed_requests (
        id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        request_time   DATETIME NOT NULL,
        requested_file VARCHAR(255),
        error_code     SMALLINT NOT NULL,
        PRIMARY KEY (id)
    ) ENGINE=InnoDB
    """,
]


def main():
    with connect(db=None) as conn:
        cur = conn.cursor()
        cur.execute(f"CREATE DATABASE IF NOT EXISTS {DB_NAME} "
                    "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
        cur.execute(f"USE {DB_NAME}")
        for statement in TABLES:
            cur.execute(statement)
        cur.execute("SHOW TABLES")
        print("Tables in", DB_NAME + ":", ", ".join(r[0] for r in cur.fetchall()))


if __name__ == "__main__":
    main()
