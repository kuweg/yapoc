$ErrorActionPreference = 'Stop'
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    throw 'Install Node.js 22+ and Docker Desktop, then run this installer again.'
}
& node (Join-Path $PSScriptRoot 'install.mjs') @args
exit $LASTEXITCODE
