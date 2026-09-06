# Windows PowerShell bootstrap. Node 22+ and Docker Desktop use Linux containers.
$ErrorActionPreference = 'Stop'
$yapocRef = if ($env:YAPOC_REF) { $env:YAPOC_REF } else { 'main' }
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    throw 'Install Node.js 22+ from https://nodejs.org/en/download then run this command again.'
}
$yapocNodeVersion = (& node --version).TrimStart('v')
if ([version]$yapocNodeVersion -lt [version]'22.0.0') { throw 'Node.js 22 or newer is required.' }
$yapocTemporary = Join-Path ([System.IO.Path]::GetTempPath()) ('yapoc-' + [guid]::NewGuid().ToString() + '.mjs')
try {
    Invoke-WebRequest -UseBasicParsing -Uri "https://raw.githubusercontent.com/kuweg/yapoc/$yapocRef/installer/index.mjs" -OutFile $yapocTemporary
    & node $yapocTemporary --ref $yapocRef @args
    if ($LASTEXITCODE -ne 0) { throw "YAPOC installer exited with $LASTEXITCODE" }
} finally {
    Remove-Item -LiteralPath $yapocTemporary -ErrorAction SilentlyContinue
}
