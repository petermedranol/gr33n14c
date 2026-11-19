# Wrapper around KiCad's CLI so you don't type the full path.
# Usage:
#   .\kcli.ps1 version
#   .\kcli.ps1 pcb drc   ..\greeniac\greeniac.kicad_pcb
#   .\kcli.ps1 pcb export svg --output out.svg ..\greeniac\greeniac.kicad_pcb
param([Parameter(ValueFromRemainingArguments = $true)] $Args)

$cli = "C:\Program Files\KiCad\10.0\bin\kicad-cli.exe"
if (-not (Test-Path $cli)) {
    Write-Error "kicad-cli not found at $cli"
    exit 1
}
& $cli @Args
exit $LASTEXITCODE
