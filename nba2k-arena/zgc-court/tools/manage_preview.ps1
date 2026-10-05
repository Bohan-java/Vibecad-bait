param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('start', 'stop')]
    [string]$Action,
    [switch]$NoBrowser
)

# ASCII source keeps this launcher compatible with Windows PowerShell 5.1.
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..')).TrimEnd('\', '/')
$runtimeDirectory = Join-Path $projectRoot '.preview-runtime'
$projectConfig = Get-Content -LiteralPath (Join-Path $projectRoot 'config\project.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$previewPort = 4173
if ($projectConfig.preview.port) { $previewPort = [int]$projectConfig.preview.port }
if ($previewPort -lt 1024 -or $previewPort -gt 65535) { throw 'The configured preview port is invalid.' }

function Test-ProjectIdentity($Identity) {
    return $Identity -and $Identity.service -eq 'zgc-court-preview' -and
        [String]::Equals([IO.Path]::GetFullPath([string]$Identity.project_root).TrimEnd('\', '/'), $projectRoot, [StringComparison]::OrdinalIgnoreCase)
}

function Read-LiveIdentity([int]$Port) {
    try { return Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/identity" -TimeoutSec 2 -UseBasicParsing }
    catch { return $null }
}

if ($Action -eq 'stop') {
    if (-not (Test-Path -LiteralPath $runtimeDirectory)) { Write-Output 'No managed preview service is recorded for this project.'; exit 0 }
    $records = @(Get-ChildItem -LiteralPath $runtimeDirectory -Filter 'server-*.json' -File)
    foreach ($record in $records) {
        $state = Get-Content -LiteralPath $record.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
        if (-not (Test-ProjectIdentity $state)) { throw 'Service state belongs to another project; no process was stopped.' }
        $servicePort = [int]$state.port
        if ($servicePort -lt 1024 -or $servicePort -gt 65535) { throw 'Invalid service state port; no process was stopped.' }
        $live = Read-LiveIdentity $servicePort
        if (-not $live) {
            $recordedProcess = Get-Process -Id ([int]$state.pid) -ErrorAction SilentlyContinue
            if ($recordedProcess) { throw "The recorded server at port $servicePort is not responding. No process was stopped." }
            Write-Output "The recorded preview at port $servicePort is already stopped."
            continue
        }
        if (-not (Test-ProjectIdentity $live) -or $live.instance_id -ne $state.instance_id -or $live.pid -ne $state.pid) {
            throw 'The running service does not match this project record; no process was stopped.'
        }
        $headers = @{ 'X-ZGC-Control' = [string]$state.control_token }
        $result = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:$servicePort/api/shutdown" -Headers $headers -TimeoutSec 5 -UseBasicParsing
        if (-not $result.stopping -or $result.instance_id -ne $state.instance_id) { throw 'The preview service did not confirm shutdown.' }
        $stopped = $false
        for ($attempt = 0; $attempt -lt 20; $attempt++) {
            Start-Sleep -Milliseconds 150
            $remaining = Read-LiveIdentity $servicePort
            if (-not $remaining -or $remaining.instance_id -ne $state.instance_id) { $stopped = $true; break }
        }
        if (-not $stopped) { throw 'Preview shutdown is still pending; no other process was stopped.' }
        Write-Output "Stopped this project preview at port $servicePort."
    }
    exit 0
}

$url = "http://127.0.0.1:$previewPort"
$existing = Read-LiveIdentity $previewPort
if ($existing) {
    if (-not (Test-ProjectIdentity $existing)) { throw 'This port belongs to another project. Change preview.port in config/project.json.' }
    Write-Output "Preview is already running: $url"
    if (-not $NoBrowser) { Start-Process -FilePath $url }
    exit 0
}

$nodeCandidates = @(
    (Join-Path $projectRoot 'runtime\node.exe'),
    [string]$projectConfig.tools.node_path,
    (Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe')
)
$nodeExecutable = $nodeCandidates | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) } | Select-Object -First 1
if (-not $nodeExecutable) {
    $nodeCommand = Get-Command node.exe -ErrorAction SilentlyContinue
    if ($nodeCommand) { $nodeExecutable = $nodeCommand.Source }
}
if (-not $nodeExecutable) { throw 'Node.js 20 or later was not found. Configure tools.node_path or provide runtime/node.exe.' }

New-Item -ItemType Directory -Path $runtimeDirectory -Force | Out-Null
$launchId = [Guid]::NewGuid().ToString('N')
$stdoutLog = Join-Path $runtimeDirectory "service-$launchId.stdout.log"
$stderrLog = Join-Path $runtimeDirectory "service-$launchId.stderr.log"
$serverScript = Join-Path $projectRoot 'tools\serve.mjs'
# Start-Process creates an independent hidden Windows process. All state and logs
# stay inside this project; no scheduled task, registry entry or global install.
$processArguments = '"' + $serverScript + '" --port ' + $previewPort
$started = Start-Process -FilePath $nodeExecutable -ArgumentList $processArguments -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput $stdoutLog -RedirectStandardError $stderrLog -PassThru
$ready = $false
for ($attempt = 0; $attempt -lt 40; $attempt++) {
    Start-Sleep -Milliseconds 250
    $live = Read-LiveIdentity $previewPort
    if (Test-ProjectIdentity $live) {
        $statePath = Join-Path $runtimeDirectory "server-$previewPort.json"
        if (Test-Path -LiteralPath $statePath) {
            $readyState = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($readyState.instance_id -eq $live.instance_id) { $ready = $true; break }
        }
    }
    $started.Refresh()
    if ($started.HasExited) { break }
}
if (-not $ready) { throw "Preview did not become ready. Inspect $stderrLog and $stdoutLog" }
Write-Output "Preview is running independently: $url"
Write-Output 'Use Stop_Preview.bat to stop only this project service.'
if (-not $NoBrowser) { Start-Process -FilePath $url }
