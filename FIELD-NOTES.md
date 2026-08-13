# Field notes: errors we hit and how we resolved them

Notes from automating Microsoft Fabric with this CLI on a managed corporate build. Each
entry gives the symptom as it actually appears, the real cause, and the fix. Several of
these errors name the wrong thing, so the point of this document is to save you the hour
of chasing the wrong cause.

Install and fork specifics live in [FORK.md](./FORK.md).

---

## Quick index

| Symptom | Real cause | Section |
|---|---|---|
| `Access is denied.` running `fab` | Defender ASR blocks the launcher | [FORK.md](./FORK.md#running-it) |
| `SSLCertVerificationError: self-signed certificate in certificate chain` | TLS inspection, certifi does not see the corporate root | [FORK.md](./FORK.md#tls-interception) |
| `403 FeatureNotAvailable` creating any item | No Fabric licence, or a tenant setting is off | [Licence and tenant](#licence-and-tenant-settings) |
| `403 InsufficientScopes` | You lack the admin role for that endpoint | [Licence and tenant](#licence-and-tenant-settings) |
| `IncorrectConfiguration` from the broker on a SQL token | The WAM broker refuses the SQL resource | [SQL access](#getting-a-sql-token) |
| `Unable to get authority configuration for https://login.microsoftonline.com/<guid>` | Stored tenant in `auth.json` is wrong | [Broken session](#a-broken-cli-session) |
| `InvalidNotebookContent ... Unexpected character encountered ... #` | `.py` definition sent as `ipynb` | [Definition formats](#item-definition-formats) |
| `Invalid object name` then error `3961` right after a Spark write | Lakehouse SQL endpoint has not synced | [SQL endpoint lag](#lakehouse-sql-endpoint-lag) |
| `RequestValidationFailed: 'ExternalReferences' cannot be null` | Pipeline activity needs a connection id | [Pipelines](#pipeline-activity-json) |
| `ActionUserFailure` on a dataflow refresh | Output destination connection is not bound | [Dataflows](#dataflow-output-destinations) |

---

## Licence and tenant settings

Fabric returns different codes for "you may not" and "this is switched off". The
distinction is the fastest diagnostic available.

- **`FeatureNotAvailable`** means the feature is off for you. Creating any item returns
  this when your account has no Fabric licence, or when a tenant setting excludes you.
  It is **not** a workspace permission problem. Confirm by trying the same operation in
  your personal workspace: if that fails too, no workspace ACL is involved.
- **`InsufficientScopes`** means you lack the role for that endpoint, for example calling
  `admin/tenantsettings` without Fabric Administrator.

Check your effective workspace role before assuming a permission fault:

```bash
fab acl ls "<workspace>.Workspace" -l
```

Remember that group membership grants roles. An account absent from that list may still be
Admin through a group. Verify with Graph:

```bash
az rest --method POST --uri "https://graph.microsoft.com/v1.0/me/getMemberGroups" \
  --body '{"securityEnabledOnly":true}' --headers "Content-Type=application/json"
```

Tenant settings that bite, both needing a Fabric Administrator:

- **Users can create Fabric items.** Off, or scoped to a group, produces
  `FeatureNotAvailable` on every create.
- **Service principals can use Fabric APIs.** Off, or scoped to a group, produces `401`
  for service principals and workspace identities even when they hold a workspace role.

---

## A broken CLI session

Symptom, on every command:

```
[UnexpectedError] Unable to get authority configuration for
https://login.microsoftonline.com/<guid>
```

The tenant recorded in `~/.config/fab/auth.json` is wrong or stale. Inspect it:

```bash
python -c "from fabric_cli.core.fab_auth import FabAuth; a=FabAuth(); print(a.auth_file); print(a.get_tenant_id())"
```

Fix by logging in again against the tenant you want:

```bash
fab auth logout
fab auth login -t <tenant-id>
```

`fab auth login` needs a real console. It fails with `No Windows console found` when run
from an automation harness or any process without one, so do this in a terminal.

---

## Getting a SQL token

The CLI signs in through the Windows WAM broker. The broker hands out the Power BI scope
happily but refuses `https://database.windows.net/`:

```
broker_error ... Status_IncorrectConfiguration
```

No refresh token is written to disk either, so you cannot mint one from the CLI cache
without the broker. Use a separate `az` login in its own config directory, which keeps
your other repos and windows untouched:

```powershell
$env:AZURE_CONFIG_DIR = "$HOME\.azure-fabric"
az login --tenant <tenant-id> --allow-no-subscriptions
az account get-access-token --resource https://database.windows.net/ --query accessToken -o tsv
```

`fork-tools/fabsql.py` wraps this. It works against a warehouse or a lakehouse SQL
endpoint, since both are databases on the same server host.

Find the server and database:

```bash
fab get "<ws>.Workspace/<lakehouse>.Lakehouse" -q properties     # sqlEndpointProperties
fab get "<ws>.Workspace/<warehouse>.Warehouse" -q properties     # connectionString
```

The database name is the item name. `fab get` is not supported on a `.SQLEndpoint` item, so
read the endpoint from the parent lakehouse.

---

## Lakehouse SQL endpoint lag

After a Spark write creates a Delta table, the SQL analytics endpoint takes up to about a
minute to catch up. During that window you get either:

```
Invalid object name 'dbo.<table>'
```

or, more confusingly:

```
3961: Snapshot isolation transaction failed ... the object accessed by the statement has
been modified by a DDL statement in another concurrent transaction
```

Both mean the same thing. Wait and retry, or poll `INFORMATION_SCHEMA.TABLES` until the
table appears. **A warehouse has no such lag**: it is read/write over T-SQL, so a job that
writes and immediately reads should prefer a warehouse over a lakehouse.

---

## Item definition formats

The CLI reads and writes item definitions as folders. Formats we have confirmed:

| Item | Files |
|---|---|
| Notebook | `.platform`, `notebook-content.py` (or `.ipynb`) |
| Semantic model | `.platform`, `definition.pbism`, `definition/{database,model,expressions}.tmdl`, `definition/tables/*.tmdl`, `definition/cultures/*.tmdl` |
| Report | `.platform`, `definition.pbir`, `report.json`, `StaticResources/...` |
| Dataflow | `.platform`, `mashup.pq`, `queryMetadata.json` |
| Data pipeline | `.platform`, `pipeline-content.json` |

**On the released CLI**, a `.py` notebook definition must be imported with an explicit
format, otherwise the service rejects it:

```bash
fab import "<ws>.Workspace/nb.Notebook" -i ./nb.Notebook --format ".py" -f
```

This fork infers it, so the flag is optional here.

The fastest way to learn any format is to export a working item and copy its shape:

```bash
fab export "<ws>.Workspace/<item>" -o ./exports -f
```

A Direct Lake semantic model over a warehouse needs `expressions.tmdl` pointing at the
warehouse and each table partition declared as an entity:

```
partition <table> = entity
    mode: directLake
    source
        entityName: <table>
        schemaName: dbo
        expressionSource: DatabaseQuery
```

Direct Lake reads at query time, so no refresh is needed for the data to be current.

A report binds to its model through `definition.pbir`:

```json
{
    "datasetReference": {
        "byConnection": {
            "connectionString": "Data Source=powerbi://api.powerbi.com/v1.0/myorg/<workspace>;initial catalog=<model>;integrated security=ClaimsToken;semanticmodelid=<model-id>"
        }
    }
}
```

---

## Pipeline activity JSON

Pipelines reference Fabric items by id, so no connection object is needed for these two.

Dataflow refresh:

```json
{
    "name": "Refresh dataflow",
    "type": "RefreshDataflow",
    "typeProperties": {
        "dataflowId": "<dataflow-id>",
        "workspaceId": "<workspace-id>",
        "dataflowType": "DataflowFabric",
        "notifyOption": "NoNotification"
    }
}
```

Stored procedure against a warehouse:

```json
{
    "name": "Run procedure",
    "type": "SqlServerStoredProcedure",
    "typeProperties": { "storedProcedureName": "[dbo].[usp_example]" },
    "linkedService": {
        "name": "<warehouse-name>",
        "properties": {
            "type": "DataWarehouse",
            "typeProperties": {
                "artifactId": "<warehouse-id>",
                "endpoint": "<server>.datawarehouse.fabric.microsoft.com",
                "workspaceId": "<workspace-id>"
            },
            "annotations": []
        }
    }
}
```

Semantic model refresh is the exception. It **requires** a connection:

```json
{
    "name": "Refresh semantic model",
    "type": "PBISemanticModelRefresh",
    "typeProperties": {
        "method": "post",
        "waitOnCompletion": true,
        "operationType": "SemanticModelRefresh",
        "commitMode": "Transactional",
        "groupId": "<workspace-id>",
        "datasetId": "<model-id>"
    },
    "externalReferences": { "connection": "<connection-id>" }
}
```

Omit `externalReferences` and the import is rejected with
`RequestValidationFailed: 'ExternalReferences' cannot be null`.

### Scheduling

Set the timezone by name so daylight saving is handled for you:

```bash
fab job run-sch "<ws>.Workspace/<pipeline>.DataPipeline" -i schedule.json
```

```json
{
    "enabled": true,
    "configuration": {
        "startDateTime": "2026-08-14T00:00:00",
        "endDateTime": "2027-08-14T00:00:00",
        "localTimeZoneId": "New Zealand Standard Time",
        "type": "Daily",
        "times": ["09:00"]
    }
}
```

---

## Connections

Most CLI work needs no connection object. Two things do: a dataflow **output destination**
and the semantic model refresh activity.

List what exists and what each type accepts:

```bash
fab ls .connections -l
fab api "connections/supportedConnectionTypes" -P "showAllCreationMethods=true"
```

A `PowerBIDatasets` connection can be created without interactive consent when the
workspace has an identity, because it accepts `WorkspaceIdentity` credentials:

```bash
fab api -X post connections -i connection.json
```

```json
{
    "connectivityType": "ShareableCloud",
    "displayName": "pbi-datasets",
    "connectionDetails": {
        "type": "PowerBIDatasets",
        "creationMethod": "PowerBIDatasets.Actions",
        "parameters": []
    },
    "privacyLevel": "Organizational",
    "credentialDetails": {
        "singleSignOnType": "None",
        "connectionEncryption": "NotEncrypted",
        "skipTestConnection": false,
        "credentials": { "credentialType": "WorkspaceIdentity" }
    }
}
```

Check the workspace has an identity first:

```bash
fab api "workspaces/<workspace-id>" -q "text.workspaceIdentity"
```

The identity then needs a workspace role, which is a separate call:

```bash
fab api -X post "workspaces/<workspace-id>/roleAssignments" -i role.json
```

```json
{ "principal": { "id": "<servicePrincipalId>", "type": "ServicePrincipal" }, "role": "Member" }
```

**Known unresolved.** Even with the connection created and Member granted, we still see
`401 Unauthorized` on the semantic model refresh activity. The remaining suspect is the
tenant setting "Service principals can use Fabric APIs". Reading it needs Fabric
Administrator, which we do not hold, so this is unconfirmed. Note also that a Direct Lake
model needs no refresh, so this activity is often unnecessary.

## Dataflow output destinations

A dataflow that only transforms data refreshes cleanly from the CLI. One that writes to a
destination fails with a generic error until its connection is bound:

```
ActionUserFailure: Something went wrong, please try again later.
```

The `connectionId` in `queryMetadata.json` is not the connection GUID from
`fab ls .connections`. It is a mashup datasource id in the form
`{"ClusterId":"...","DatasourceId":"..."}` and we found no way to mint it from the CLI.

Bind the destination once in the portal, then export the item. The exported
`queryMetadata.json` carries the correct `connectionId`, which you can then commit and
redeploy from the CLI for good.

---

## Things the CLI does not do

- **No T-SQL and no DAX.** `fab table` covers load, optimize, schema and vacuum only. Use
  `fork-tools/fabsql.py` and `fork-tools/dax_query.py`.
- **`job run` on a dataflow** works in this fork. On the released CLI use
  `fab api -X post "workspaces/<ws>/items/<id>/jobs/instances" -P jobType=Refresh` and poll
  `.../jobs/instances/<job-id>`.
- **`-q` quoting.** A JMESPath expression containing a quoted key, such as
  `headers."x-ms-job-id"`, does not survive shell quoting reliably. Filter the output
  instead.
- **`--output_format json`** wraps the payload as `result.data[0].text`, which differs from
  the default output shape. Account for it when parsing.
