"""Look at the HW5 tables from your laptop or Cloud Shell.

  python db_tool.py show [--limit N]   row counts + the newest rows of each table
  python db_tool.py stats              the statistics for part 7 of the report
  python db_tool.py reset --yes        empty both tables (e.g. before the load test)

Run it with the venv that setup.sh creates:  .venv/bin/python db_tool.py show
"""
import argparse

from dbconn import connect


def print_table(cur, sql, title=None):
    cur.execute(sql)
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description]
    if title:
        print(f"\n{title}")
    print(f"  SQL: {' '.join(sql.split())}")
    cells = [[("NULL" if v is None else str(v)) for v in r] for r in rows]
    widths = [max([len(c)] + [len(r[i]) for r in cells]) for i, c in enumerate(cols)]
    line = "  +" + "+".join("-" * (w + 2) for w in widths) + "+"
    print(line)
    print("  | " + " | ".join(c.ljust(w) for c, w in zip(cols, widths)) + " |")
    print(line)
    for r in cells:
        print("  | " + " | ".join(v.ljust(w) for v, w in zip(r, widths)) + " |")
    print(line)
    print(f"  ({len(rows)} row{'s' if len(rows) != 1 else ''})")
    return rows


def show(cur, limit):
    print_table(cur, "SELECT (SELECT COUNT(*) FROM requests) AS requests_rows, "
                     "(SELECT COUNT(*) FROM failed_requests) AS failed_requests_rows",
                "Row counts")
    print_table(cur, f"SELECT * FROM requests ORDER BY id DESC LIMIT {limit}",
                f"Newest {limit} rows of requests")
    print_table(cur, f"SELECT * FROM failed_requests ORDER BY id DESC LIMIT {limit}",
                f"Newest {limit} rows of failed_requests")


def stats(cur):
    print_table(cur, "SELECT SUM(status_code = 200) AS successful, "
                     "SUM(status_code <> 200) AS unsuccessful, COUNT(*) AS total "
                     "FROM requests",
                "1. Successful vs unsuccessful requests")
    print_table(cur, "SELECT error_code, COUNT(*) AS requests FROM failed_requests "
                     "GROUP BY error_code ORDER BY requests DESC",
                "   Unsuccessful requests by error code (failed_requests table)")
    print_table(cur, "SELECT SUM(is_banned) AS from_banned_countries FROM requests",
                "2. Requests from banned countries")
    print_table(cur, "SELECT gender, COUNT(*) AS requests FROM requests "
                     "WHERE gender IS NOT NULL GROUP BY gender ORDER BY requests DESC",
                "3. Requests by gender")
    print_table(cur, "SELECT country, COUNT(*) AS requests FROM requests "
                     "WHERE country IS NOT NULL GROUP BY country "
                     "ORDER BY requests DESC, country LIMIT 5",
                "4. Top 5 countries")
    print_table(cur, "SELECT age AS age_group, COUNT(*) AS requests FROM requests "
                     "WHERE age IS NOT NULL GROUP BY age "
                     "ORDER BY requests DESC, age LIMIT 3",
                "5. Age groups with the most requests (first row is the answer)")
    print_table(cur, "SELECT income AS income_group, COUNT(*) AS requests FROM requests "
                     "WHERE income IS NOT NULL GROUP BY income "
                     "ORDER BY requests DESC, income LIMIT 3",
                "6. Income groups with the most requests (first row is the answer)")


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p_show = sub.add_parser("show")
    p_show.add_argument("--limit", type=int, default=5)
    sub.add_parser("stats")
    p_reset = sub.add_parser("reset")
    p_reset.add_argument("--yes", action="store_true", help="really delete all rows")
    args = parser.parse_args()

    with connect() as conn:
        cur = conn.cursor()
        if args.command == "show":
            show(cur, args.limit)
        elif args.command == "stats":
            stats(cur)
        elif args.command == "reset":
            if not args.yes:
                parser.error("reset deletes every row; add --yes to confirm")
            cur.execute("TRUNCATE TABLE failed_requests")
            cur.execute("TRUNCATE TABLE requests")
            print("Both tables emptied.")


if __name__ == "__main__":
    main()
