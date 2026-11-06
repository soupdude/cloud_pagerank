"""Build the 3NF database `hw6` from the HW5 tables, then check the result.

    python migrate_schema.py

Runs schema_3nf.sql (drops and rebuilds hw6; the hw5 tables are only read),
then prints row counts and consistency checks.
"""
import pathlib

from dbconn import connect

SQL_FILE = pathlib.Path(__file__).with_name("schema_3nf.sql")

CHECKS = [
    # (description, query, expected value or None to just report)
    ("IPs recorded with more than one country in hw5 (must be 0 for client_ip -> country)",
     "SELECT COUNT(*) FROM (SELECT client_ip FROM hw5.requests WHERE country IS NOT NULL "
     "GROUP BY client_ip HAVING COUNT(DISTINCT country) > 1) t", 0),
    ("Countries recorded as both banned and not banned (must be 0 for country -> is_banned)",
     "SELECT COUNT(*) FROM (SELECT country FROM hw5.requests WHERE country IS NOT NULL "
     "GROUP BY country HAVING COUNT(DISTINCT is_banned) > 1) t", 0),
    ("hw5.requests rows", "SELECT COUNT(*) FROM hw5.requests", None),
    ("hw6.requests rows (must equal hw5.requests)", "SELECT COUNT(*) FROM hw6.requests", "same"),
    ("hw6.client_ips rows (distinct IPs)", "SELECT COUNT(*) FROM hw6.client_ips", None),
    ("hw6.countries rows", "SELECT COUNT(*) FROM hw6.countries", None),
    ("hw5.failed_requests rows", "SELECT COUNT(*) FROM hw5.failed_requests", None),
    ("hw6.failed_requests rows (must equal hw5.failed_requests)",
     "SELECT COUNT(*) FROM hw6.failed_requests", "same"),
    ("Requests whose country or banned flag differs after joining the new tables (must be 0)",
     "SELECT COUNT(*) FROM hw5.requests o "
     "JOIN hw6.requests n ON n.request_id = o.id "
     "JOIN hw6.client_ips i ON i.client_ip = n.client_ip "
     "LEFT JOIN hw6.countries c ON c.country_id = i.country_id "
     "WHERE NOT (o.country <=> c.name) OR o.is_banned <> COALESCE(c.is_banned, FALSE)", 0),
]


def statements(sql):
    lines = [line for line in sql.splitlines() if not line.strip().startswith("--")]
    return [s.strip() for s in "\n".join(lines).split(";") if s.strip()]


def main():
    with connect() as conn:
        cur = conn.cursor()
        for stmt in statements(SQL_FILE.read_text()):
            first_line = " ".join(stmt.split())[:70]
            cur.execute(stmt)
            print(f"ok   {first_line}{' ...' if len(stmt) > 70 else ''}"
                  f"{f'  ({cur.rowcount} rows)' if stmt.upper().startswith('INSERT') else ''}")

        print("\nChecks")
        failed = 0
        previous = None
        for label, query, expected in CHECKS:
            cur.execute(query)
            value = cur.fetchone()[0]
            if expected == "same":
                good = value == previous
            elif expected is None:
                good = True
            else:
                good = value == expected
            failed += not good
            print(f"  {'PASS' if good else 'FAIL'}  {label}: {value}")
            previous = value
        if failed:
            raise SystemExit(f"{failed} check(s) failed")
        print("Migration complete: database hw6 is ready.")


if __name__ == "__main__":
    main()
