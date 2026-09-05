[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [ValidateSet("Install", "Remove")]
    [string]$Action = "Install",
    [ValidatePattern("^(?:[01]\d|2[0-3]):[0-5]\d$")]
    [string]$Time = "03:00",
    [string]$ProjectDir = "",
    [string]$Python = ""
)

$ErrorActionPreference = "Stop"
$TaskName = "HuntAlpha Local DB Backup"

if (-not $ProjectDir) {
    $ProjectDir = Split-Path -Parent $PSScriptRoot
}
$ProjectDir = (Resolve-Path -LiteralPath $ProjectDir).Path
if (-not (Test-Path -LiteralPath (Join-Path $ProjectDir "manage.py") -PathType Leaf)) {
    throw "ProjectDir must contain manage.py."
}

if ($Action -eq "Remove") {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        if ($PSCmdlet.ShouldProcess($TaskName, "Remove scheduled task")) {
            Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
            Write-Output "Removed: $TaskName"
        }
    } else {
        Write-Output "Not installed: $TaskName"
    }
    exit 0
}

if (-not $Python) {
    $Python = (Get-Command python -ErrorAction Stop).Source
} else {
    $Python = (Resolve-Path -LiteralPath $Python).Path
}

$timeValue = [DateTime]::ParseExact($Time, "HH:mm", [Globalization.CultureInfo]::InvariantCulture)
$action = New-ScheduledTaskAction -Execute $Python -Argument "-X utf8 manage.py backup_local_db" -WorkingDirectory $ProjectDir
$trigger = New-ScheduledTaskTrigger -Daily -At $timeValue
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

if ($PSCmdlet.ShouldProcess($TaskName, "Create or update daily scheduled task at $Time")) {
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Description "HuntAlpha local SQLite backup; invokes manage.py backup_local_db" -Force | Out-Null
    Write-Output "Installed: $TaskName at $Time"
    Write-Output "ProjectDir: $ProjectDir"
}
