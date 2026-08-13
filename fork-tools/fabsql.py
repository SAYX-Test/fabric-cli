"""Run T-SQL against a Fabric warehouse or lakehouse SQL analytics endpoint.

Not part of the Fabric CLI. See FIELD-NOTES.md.

The CLI signs in through the Windows WAM broker, which refuses the
https://database.windows.net/ resource and writes no refresh token to disk. So the
token comes from an az login instead. Keep that login in its own AZURE_CONFIG_DIR so
it cannot clobber the az session in your other repos or windows.

Setup:
    $env:AZURE_CONFIG_DIR = "$HOME\\.azure-fabric"
    az login --tenant <tenant-id> --allow-no-subscriptions

Usage:
    python fabsql.py --server <host> --database <db> --sql "SELECT 1"
    python fabsql.py --server <host> --database <db> --file script.sql

Find the server with:
    fab get "<ws>.Workspace/<warehouse>.Warehouse" -q properties
    fab get "<ws>.Workspace/<lakehouse>.Lakehouse" -q properties

Batches in a file may be separated by a line holding only GO.
"""

import argparse
import json
import os
import struct
import subprocess
import sys

import pyodbc

SQL_RESOURCE = "https://database.windows.net/"
SQL_COPT_SS_ACCESS_TOKEN = 1256
DEFAULT_DRIVER = "ODBC Driver 18 for SQL Server"
FALLBACK_DRIVER = "ODBC Driver 17 for SQL Server"


def pick_driver(preferred: str | None) -> str:
    """Return an installed SQL Server ODBC driver, preferring the newest."""
    installed = set(pyodbc.drivers())
    for candidate in (preferred, DEFAULT_DRIVER, FALLBACK_DRIVER):
        if candidate and candidate in installed:
            return candidate
    sys.exit(
        "No SQL Server ODBC driver found. Install 'ODBC Driver 18 for SQL Server'. "
        f"Drivers present: {sorted(installed)}"
    )


def get_token(azure_config_dir: str | None) -> str:
    env = dict(os.environ)
    if azure_config_dir:
        env["AZURE_CONFIG_DIR"] = os.path.expanduser(azure_config_dir)

    result = subprocess.run(
        ["az", "account", "get-access-token", "--resource", SQL_RESOURCE, "-o", "json"],
        capture_output=True,
        text=True,
        shell=True,
        env=env,
    )
    if result.returncode != 0:
        sys.exit(
            "az could not issue a SQL token. Run 'az login --tenant <id> "
            f"--allow-no-subscriptions' first.\n{result.stderr.strip()}"
        )
    return json.loads(result.stdout)["accessToken"]


def split_batches(text: str) -> list[str]:
    batches: list[str] = []
    current: list[str] = []
    for line in text.splitlines():
        if line.strip().upper() == "GO":
            if current:
                batches.append("\n".join(current))
            current = []
        else:
            current.append(line)
    if current and "".join(current).strip():
        batches.append("\n".join(current))
    return batches


def print_rows(cursor) -> None:
    columns = [c[0] for c in cursor.description]
    rows = [
        ["NULL" if value is None else str(value) for value in row]
        for row in cursor.fetchall()
    ]

    widths = [len(c) for c in columns]
    for row in rows:
        widths = [max(w, len(v)) for w, v in zip(widths, row)]

    print(" | ".join(c.ljust(w) for c, w in zip(columns, widths)))
    print("-+-".join("-" * w for w in widths))
    for row in rows:
        print(" | ".join(v.ljust(w) for v, w in zip(row, widths)))
    print(f"({len(rows)} rows)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--server", required=True, help="SQL endpoint host name")
    parser.add_argument("--database", required=True, help="Warehouse or lakehouse name")
    parser.add_argument("--sql", help="Inline T-SQL to run")
    parser.add_argument("--file", help="Path to a .sql file to run")
    parser.add_argument("--driver", help="ODBC driver name to force")
    parser.add_argument(
        "--azure-config-dir",
        help="AZURE_CONFIG_DIR holding the az login to use for the token",
    )
    args = parser.parse_args()

    if args.file:
        with open(args.file, "r", encoding="utf-8") as handle:
            text = handle.read()
    elif args.sql:
        text = args.sql
    else:
        parser.error("give --sql or --file")

    # The driver wants the token as UTF-16-LE with a 4-byte length prefix.
    raw = get_token(args.azure_config_dir).encode("utf-16-le")
    token_struct = struct.pack("=i", len(raw)) + raw

    connection_string = (
        f"Driver={{{pick_driver(args.driver)}}};"
        f"Server={args.server},1433;"
        f"Database={args.database};"
        "Encrypt=yes;TrustServerCertificate=no;Connection Timeout=60;"
    )

    with pyodbc.connect(
        connection_string,
        attrs_before={SQL_COPT_SS_ACCESS_TOKEN: token_struct},
        autocommit=True,
    ) as connection:
        cursor = connection.cursor()
        for index, batch in enumerate(split_batches(text), start=1):
            if not batch.strip():
                continue
            cursor.execute(batch)
            while True:
                if cursor.description:
                    print_rows(cursor)
                if not cursor.nextset():
                    break
            print(f"-- batch {index} ok")


if __name__ == "__main__":
    main()
