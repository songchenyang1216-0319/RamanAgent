param(
    [string]$OutputName = "RamanAgent_clean.zip"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = (Resolve-Path (Join-Path $ScriptDir "..")).Path
$Destination = Join-Path $ProjectRoot $OutputName

if (Test-Path -LiteralPath $Destination) {
    Remove-Item -LiteralPath $Destination -Force
}

$ExcludePatterns = @(
    "(^|\\)\.env$",
    "(^|\\)\.env\..*$",
    "(^|\\)\.git(\\|$)",
    "(^|\\)workspace(\\|$)",
    "(^|\\)outputs(\\|$)",
    "(^|\\)\.pytest-tmp(\\|$)",
    "(^|\\)\.pytest_cache(\\|$)",
    "(^|\\)__pycache__(\\|$)",
    "\.pyc$"
)

Push-Location $ProjectRoot
try {
    $Files = Get-ChildItem -Recurse -File | Where-Object {
        $RelativePath = $_.FullName.Substring($ProjectRoot.Length).TrimStart("\")
        if ($RelativePath -eq $OutputName) {
            return $false
        }
        foreach ($Pattern in $ExcludePatterns) {
            if ($RelativePath -match $Pattern) {
                return $false
            }
        }
        return $true
    } | ForEach-Object {
        $_.FullName.Substring($ProjectRoot.Length).TrimStart("\")
    }

    Compress-Archive -Path $Files -DestinationPath $Destination -Force
    Write-Host ("Exported clean archive to {0}" -f $Destination)
}
finally {
    Pop-Location
}
