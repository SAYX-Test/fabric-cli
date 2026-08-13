# Build a CA bundle holding certifi's roots plus the Windows certificate store.
#
# Needed on networks that inspect TLS. The proxy presents a certificate whose root sits
# only in the Windows store, which certifi does not consult, so calls fail with
# "self-signed certificate in certificate chain" part way through an operation.
#
# Usage:
#   .\build-ca-bundle.ps1                       # writes to ~/.fab/corp-ca-bundle.pem
#   .\build-ca-bundle.ps1 -Persist              # also sets the env vars for your user
#
# Open a new shell after using -Persist.

param(
    [string]$OutFile = (Join-Path $HOME ".fab\corp-ca-bundle.pem"),
    [switch]$Persist
)

$ErrorActionPreference = "Stop"

$certifiPath = python -c "import certifi; print(certifi.where())"
if (-not $certifiPath) {
    throw "Could not locate certifi. Is Python on PATH?"
}

New-Item -ItemType Directory -Force -Path (Split-Path $OutFile) | Out-Null
Copy-Item -Path $certifiPath -Destination $OutFile -Force
Write-Output "base bundle: $certifiPath"

$added = 0
foreach ($store in 'Cert:\LocalMachine\Root', 'Cert:\CurrentUser\Root', 'Cert:\LocalMachine\CA') {
    try {
        foreach ($cert in Get-ChildItem $store -ErrorAction Stop) {
            $b64 = [Convert]::ToBase64String($cert.RawData, 'InsertLineBreaks')
            Add-Content -Path $OutFile -Value "`n$($cert.Subject)`n-----BEGIN CERTIFICATE-----`n$b64`n-----END CERTIFICATE-----"
            $added++
        }
    }
    catch {
        Write-Output "skipped $store : $($_.Exception.Message)"
    }
}

Write-Output "added $added certificates from the Windows store"
Write-Output "bundle: $OutFile"

if ($Persist) {
    [Environment]::SetEnvironmentVariable('REQUESTS_CA_BUNDLE', $OutFile, 'User')
    [Environment]::SetEnvironmentVariable('SSL_CERT_FILE', $OutFile, 'User')
    Write-Output "set REQUESTS_CA_BUNDLE and SSL_CERT_FILE for the current user"
    Write-Output "open a new shell for these to take effect"
}
else {
    Write-Output ""
    Write-Output "To use for this session:"
    Write-Output "  `$env:REQUESTS_CA_BUNDLE = `"$OutFile`""
    Write-Output "  `$env:SSL_CERT_FILE = `"$OutFile`""
}
