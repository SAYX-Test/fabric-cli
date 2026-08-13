# fork-tools

Helper scripts that sit beside the CLI. **They are not part of the Fabric CLI** and are
excluded from anything we send upstream. They cover the two gaps the CLI leaves: it runs
no T-SQL and no DAX.

See [FIELD-NOTES.md](../FIELD-NOTES.md) for the reasoning behind each one.

| Script | What it does |
|---|---|
| `fabsql.py` | Runs T-SQL against a warehouse or a lakehouse SQL analytics endpoint |
| `dax_query.py` | Runs a DAX query against a semantic model |
| `build-ca-bundle.ps1` | Builds a CA bundle for networks that inspect TLS |

## Requirements

```bash
pip install pyodbc requests
```

`fabsql.py` also needs a SQL Server ODBC driver (18 preferred, 17 works) and the Azure CLI.

## Examples

```bash
# T-SQL against a warehouse
python fork-tools/fabsql.py --server <host>.datawarehouse.fabric.microsoft.com \
    --database my_warehouse --sql "SELECT TOP 10 * FROM dbo.customers"

# A multi-batch script, GO separated
python fork-tools/fabsql.py --server <host> --database my_warehouse --file build.sql

# DAX against a semantic model
python fork-tools/dax_query.py --dataset <model-id> --file query.dax
```

`fabsql.py` needs an `az` login for the SQL token, because the CLI's broker login will not
issue one. Keep it isolated so it cannot disturb your other work:

```powershell
$env:AZURE_CONFIG_DIR = "$HOME\.azure-fabric"
az login --tenant <tenant-id> --allow-no-subscriptions
python fork-tools/fabsql.py --azure-config-dir "$HOME\.azure-fabric" --server ... --database ...
```

`dax_query.py` needs no second login. It reuses the Fabric CLI's own token.
