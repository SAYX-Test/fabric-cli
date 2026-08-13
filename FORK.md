# SAYX-Test fork of the Microsoft Fabric CLI

This is a fork of [microsoft/fabric-cli](https://github.com/microsoft/fabric-cli). It
tracks upstream and carries a small set of fixes we needed while automating Fabric from
the terminal. Everything here is intended to go upstream eventually, so the diff is kept
deliberately small.

Upstream docs stay authoritative for how the CLI works:
<https://microsoft.github.io/fabric-cli/>.

---

## Install

```bash
pip install git+https://github.com/SAYX-Test/fabric-cli.git@main
```

Requires Python 3.10 to 3.13. To go back to the released version:

```bash
pip install --force-reinstall ms-fabric-cli
```

Check which one you are on:

```bash
python -m fabric_cli --version
```

---

## What this fork changes

| # | Change | Why it matters |
|---|---|---|
| 1 | Fixes the parent directory check in `get_command_context` | The expression put `and` inside `os.path.exists()`, so it tested file descriptor 1 rather than the directory. It printed `RuntimeWarning: bool is used as a file descriptor` and returned the wrong answer. |
| 2 | Adds `python -m fabric_cli` | The `fab` launcher is not always usable. See "Running it" below. |
| 3 | `import` infers the definition format | `export` writes `notebook-content.py`, `import` defaulted to `ipynb`, so export then import failed with `InvalidNotebookContent`. Round trips now work without `--format`. |
| 4 | `export -o` creates its output directory | It previously failed with `No such file or directory`, even though it creates item subfolders under that directory anyway. |
| 5 | `job run` accepts a Dataflow | `fab job run x.Dataflow` now triggers a Gen2 refresh. Previously this needed a raw `api -X post .../jobs/instances?jobType=Refresh` call and a hand written poller. |

Files touched:

- `src/fabric_cli/core/fab_handle_context.py`
- `src/fabric_cli/__main__.py` (new)
- `src/fabric_cli/utils/fab_item_util.py`
- `src/fabric_cli/commands/fs/impor/fab_fs_import_item.py`
- `src/fabric_cli/utils/fab_storage.py`
- `src/fabric_cli/core/fab_types.py`
- `src/fabric_cli/core/fab_config/command_support.yaml`

---

## Running it

Use either form:

```bash
fab --version
python -m fabric_cli --version
```

Prefer `python -m fabric_cli` on a managed Windows build. Microsoft Defender Attack
Surface Reduction blocks newly created executables that lack reputation, and the `fab.exe`
launcher that pip generates is exactly that. The symptom is bare and unhelpful:

```
C:\> fab auth login
Access is denied.
```

Confirm it with the event log rather than guessing:

```powershell
Get-WinEvent -LogName "Microsoft-Windows-Windows Defender/Operational" -MaxEvents 40 |
  Where-Object { $_.Id -eq 1121 } | Select-Object -First 1 -ExpandProperty Message
```

Rule `01443614-CD74-433A-B99E-2ECDC07BFC25` is "Block executable files from running unless
they meet a prevalence, age, or trusted list criterion". The Python module entry point
sidesteps it, because `python.exe` is already trusted.

A PowerShell profile function makes this invisible:

```powershell
function fab { python -m fabric_cli @args }
```

---

## TLS interception

On a network that inspects TLS, calls fail part way through an operation:

```
[UnexpectedError] ... SSLError(SSLCertVerificationError(1,
'[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: self-signed certificate in
certificate chain'))
```

The proxy presents a certificate whose root sits in the Windows certificate store, which
`certifi` does not consult. The first calls succeed and a later redirect fails, which makes
this look like an intermittent fault rather than a trust problem.

Build a bundle that holds both, then point Python at it:

```powershell
$out = "$HOME\.fab\corp-ca-bundle.pem"
New-Item -ItemType Directory -Force -Path (Split-Path $out) | Out-Null
Copy-Item (python -c "import certifi; print(certifi.where())") $out -Force
foreach ($store in 'Cert:\LocalMachine\Root', 'Cert:\CurrentUser\Root', 'Cert:\LocalMachine\CA') {
    Get-ChildItem $store | ForEach-Object {
        $b64 = [Convert]::ToBase64String($_.RawData, 'InsertLineBreaks')
        Add-Content $out "`n-----BEGIN CERTIFICATE-----`n$b64`n-----END CERTIFICATE-----"
    }
}
[Environment]::SetEnvironmentVariable('REQUESTS_CA_BUNDLE', $out, 'User')
[Environment]::SetEnvironmentVariable('SSL_CERT_FILE', $out, 'User')
```

Open a new shell afterwards. This helps any Python tool that talks to Fabric or Power BI,
not only this CLI.

---

## Things the CLI still cannot do

Worth knowing before you plan automation around it:

- **No T-SQL and no DAX.** `fab table` covers load, optimize, schema and vacuum only.
  Reading data needs a separate client, such as `pyodbc` with an Entra access token.
- **Connection objects.** Items are referenced by id and work well. Anything needing a
  *connection* (a dataflow output destination, a semantic model refresh activity in a
  pipeline) needs that connection created first. Some can be created through
  `api -X post connections`, for example a `PowerBIDatasets` connection using
  `WorkspaceIdentity` credentials. Others need one pass through the portal. Export the item
  afterwards to capture the connection id for reuse.
- **Lakehouse SQL endpoint lag.** After a Spark write, the SQL endpoint takes a moment to
  sync. A first query can fail with `Invalid object name` or error 3961. Retry rather than
  treating it as a fault. A warehouse has no such lag.

---

## Development

```bash
git clone https://github.com/SAYX-Test/fabric-cli.git
cd fabric-cli
pip install -r requirements-dev.txt
pip install -e .
```

Run the checks that upstream runs:

```bash
python -m pytest tests/test_core tests/test_utils tests/test_parsers
python -m black src/ tests/
python -m mypy src/ tests/ --ignore-missing-imports
```

Note: `tests/test_utils/test_fab_ui.py::test_print_error_format_text_success` fails on
upstream `main` as well. It is not caused by anything in this fork.

---

## Staying in sync with upstream

```bash
git remote add upstream https://github.com/microsoft/fabric-cli.git   # once
git fetch upstream
git rebase upstream/main
```

Rebase rather than merge, so our commits stay individually reviewable and easy to submit
upstream.

## Sending a change upstream

Upstream expects an issue first. Their process, from `AGENTS.md` and `CONTRIBUTING.md`:

1. Search the issues, then open one if it is new.
2. Wait for the `help-wanted` label before starting.
3. Comment with your intended approach and wait for acknowledgement.
4. Open the PR with `- Resolves #<issue>` at the top of the description.
5. Add a changie entry with `changie new`.

Each change here is a separate commit with its own changie entry, so a single fix can be
cherry-picked onto a clean branch off `upstream/main`.
