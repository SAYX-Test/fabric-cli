"""Run a DAX query against a semantic model, using the Fabric CLI's own login.

Not part of the Fabric CLI. See FIELD-NOTES.md.

The Power BI scope is one the CLI's broker login does hand out, so no second login is
needed here, unlike the SQL path in fabsql.py.

Usage:
    python dax_query.py --dataset <model-id> --dax "EVALUATE ROW(\\"x\\", 1)"
    python dax_query.py --dataset <model-id> --file query.dax

Find the model id with:
    fab get "<ws>.Workspace/<model>.SemanticModel" -q id

Prefer --file. Shells mangle the double quotes DAX needs for named columns.
"""

import argparse
import sys

import requests

from fabric_cli.core.fab_auth import FabAuth

POWERBI_SCOPE = "https://analysis.windows.net/powerbi/api/.default"
EXECUTE_QUERIES = "https://api.powerbi.com/v1.0/myorg/datasets/{dataset}/executeQueries"


def print_rows(rows: list[dict]) -> None:
    if not rows:
        print("(no rows)")
        return

    columns = list(rows[0].keys())
    printable = [
        ["NULL" if row.get(c) is None else str(row.get(c)) for c in columns]
        for row in rows
    ]

    widths = [len(c) for c in columns]
    for row in printable:
        widths = [max(w, len(v)) for w, v in zip(widths, row)]

    print(" | ".join(c.ljust(w) for c, w in zip(columns, widths)))
    print("-+-".join("-" * w for w in widths))
    for row in printable:
        print(" | ".join(v.ljust(w) for v, w in zip(row, widths)))
    print(f"({len(rows)} rows)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dataset", required=True, help="Semantic model (dataset) id")
    parser.add_argument("--dax", help="Inline DAX query")
    parser.add_argument("--file", help="Path to a file holding the DAX query")
    args = parser.parse_args()

    if args.file:
        with open(args.file, "r", encoding="utf-8") as handle:
            dax = handle.read()
    elif args.dax:
        dax = args.dax
    else:
        parser.error("give --dax or --file")

    token = FabAuth().get_access_token([POWERBI_SCOPE], interactive_renew=False)
    if not token:
        sys.exit("No Power BI token. Run 'fab auth login' first.")

    response = requests.post(
        EXECUTE_QUERIES.format(dataset=args.dataset),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json={
            "queries": [{"query": dax}],
            "serializerSettings": {"includeNulls": True},
        },
        timeout=180,
    )

    if response.status_code != 200:
        print(f"status: {response.status_code}")
        print(response.text[:2000])
        sys.exit(1)

    print_rows(response.json()["results"][0]["tables"][0].get("rows", []))


if __name__ == "__main__":
    main()
