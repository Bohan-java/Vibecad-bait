$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..')).TrimEnd('\', '/')
$manifest = Get-Content -LiteralPath (Join-Path $projectRoot 'public/manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$native = Get-Content -LiteralPath (Join-Path $projectRoot 'public/game-preview/manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$report = Get-Content -LiteralPath (Join-Path $projectRoot 'validation/iff-current.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$candidate = Get-Item -LiteralPath (Join-Path $projectRoot 'output/arena_700_int.iff')
if (-not $report.archive_crc_verified -or $report.after_d3d.failed.Count -ne 0) { throw 'Current archive has not passed validation.' }
if ($candidate.Length -ne $report.output_bytes -or $native.iff.sha256 -ne $report.output_sha256) { throw 'Current IFF and preview do not match.' }
if (-not (Test-Path -LiteralPath (Join-Path $projectRoot "public/builds/$($manifest.build_id)/scene.glb"))) { throw 'Current source preview is missing.' }
$targets = [Collections.Generic.List[string]]::new()
foreach ($name in @('.build-staging','tools/__pycache__')) {
    $directory = Join-Path $projectRoot $name
    if (Test-Path -LiteralPath $directory) { Get-ChildItem -LiteralPath $directory -Force | ForEach-Object { $targets.Add($_.FullName) } }
}
Get-ChildItem -LiteralPath (Join-Path $projectRoot 'public/builds') -Directory | Where-Object Name -ne $manifest.build_id | ForEach-Object { $targets.Add($_.FullName) }
# R12 retains only the six views decoded from the final current IFF. Earlier
# source previews and superseded native screenshots can otherwise mislead QA.
if ($report.revision -eq 'R12' -and (Test-Path -LiteralPath (Join-Path $projectRoot 'validation/r12-native-visual-validation.json'))) {
    $visual = Get-Content -LiteralPath (Join-Path $projectRoot 'validation/r12-native-visual-validation.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($visual.iff_sha256 -ne $report.output_sha256) { throw 'R12 visual report belongs to another IFF.' }
    Get-ChildItem -LiteralPath (Join-Path $projectRoot 'validation') -File | Where-Object { $_.Extension -in @('.png','.jpg') -and $_.Name -notlike 'current-context-*' -and $_.Name -ne 'r12-context-open.png' } | ForEach-Object { $targets.Add($_.FullName) }
}
if ($report.half_court_orientation -and $report.half_court_orientation.world_yaw_degrees -eq 180) {
    $oldVisualPath = Join-Path $projectRoot 'validation/r12-native-visual-validation.json'
    if (Test-Path -LiteralPath $oldVisualPath) {
        $oldVisual = Get-Content -LiteralPath $oldVisualPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($oldVisual.iff_sha256 -ne $report.output_sha256) {
            # The current interactive preview was decoded from the new IFF.
            # Do not retain old-direction still renders under current names.
            Get-ChildItem -LiteralPath (Join-Path $projectRoot 'validation') -File -Filter 'current-context-*.png' | ForEach-Object { $targets.Add($_.FullName) }
            $targets.Add($oldVisualPath)
        }
    }
}
if ($report.revision -eq 'R13') {
    $visualPath = Join-Path $projectRoot 'validation/r13-native-visual-validation.json'
    $visual = Get-Content -LiteralPath $visualPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($visual.iff_sha256 -ne $report.output_sha256 -or $visual.status -ne 'passed_offline_import_and_render') { throw 'R13 visual report does not match this delivery.' }
    foreach ($view in @('entry','sign','hardware','awning','paving','backboard')) {
        if (-not $visual.views.$view -or -not (Test-Path -LiteralPath $visual.views.$view.path)) { throw "Missing current R13 inspection view: $view" }
    }
    Get-ChildItem -LiteralPath (Join-Path $projectRoot 'validation') -File | Where-Object { $_.Extension -in @('.png','.jpg') -and $_.Name -notlike 'current-r13-*' } | ForEach-Object { $targets.Add($_.FullName) }
}
$textureRoot = Join-Path $projectRoot '.preview-runtime/textures'
if (Test-Path -LiteralPath $textureRoot) {
    Get-ChildItem -LiteralPath $textureRoot -Directory | Where-Object { $_.Name -notin @($manifest.build_id,$native.build_id) } | ForEach-Object { $targets.Add($_.FullName) }
}
Get-ChildItem -LiteralPath (Join-Path $projectRoot 'logs') -File | Where-Object Name -ne "$($manifest.build_id).log" | ForEach-Object { $targets.Add($_.FullName) }
Get-ChildItem -LiteralPath (Join-Path $projectRoot 'preview') -File -Filter '*.json' | Where-Object Name -ne 'texture-runtime-report.json' | ForEach-Object { $targets.Add($_.FullName) }
$browserReportPath = Join-Path $projectRoot 'preview/texture-runtime-report.json'
if (Test-Path -LiteralPath $browserReportPath) {
    $browserReport = Get-Content -LiteralPath $browserReportPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($browserReport.build_id -notin @($manifest.build_id,$native.build_id)) { $targets.Add($browserReportPath) }
}
foreach ($name in @('recovery','tools/render_native_iff.py','tools/repair_resource_ids.py',
                    'validation/container-current.json','validation/details-validation.json',
                    'validation/scene-current.json','validation/iff-codec-probe.json','validation/current-support-detail.png',
                    'validation/current-detail-validation.json','validation/floor-overlay-current.json',
                    'validation/r08-alignment-current.json','validation/r08-material-audit.json',
                    'validation/r09-material-rig-audit.json',
                    'validation/r10_bitcode_probe.py',
                    'validation/r10-PS.66823e7969ce912a.shader.ir.txt',
                    'validation/r10-PS.c8eff3dddf2459dc.shader.ir.txt',
                    'validation/r10-PS.964b07872198a129.shader.ir.txt',
                    'tools/audit_r08_alignment.py','validation/native-glass-texture.png',
                    'validation/floor-artwork-current.png',
                    'validation/current-hoop-front.png','validation/current-hoop-side.png','validation/current-hoop-detail.png',
                    'validation/current-web-hoop-front.jpg','validation/current-web-hoop-side.jpg','validation/current-web-hoop-back.jpg','validation/current-web-preview.jpg',
                    'validation/current-web-fence-A.png','validation/current-web-ground.png',
                    'validation/current-web-hoop-back.png','validation/current-web-hoop-front.png','validation/current-web-hoop-side.png',
                    'validation/current-web-open-floor.png','validation/current-web-streetlight.png',
                    'validation/current-web-preview.png',
                    'validation/current-chilis-detail.png','validation/current-fence-detail.png','validation/current-garden-detail.png')) {
    $target = Join-Path $projectRoot $name
    if (Test-Path -LiteralPath $target) { $targets.Add($target) }
}
$serviceLogs = @(Get-ChildItem -LiteralPath (Join-Path $projectRoot '.preview-runtime') -File -Filter 'service-*.log')
foreach ($serviceLog in $serviceLogs) {
    # The launch-log UUID differs from the server's own instance UUID.
    # Active redirected logs are held open by the running service and retained.
    try {
        $probe = [IO.File]::Open($serviceLog.FullName,[IO.FileMode]::Open,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
        $probe.Dispose()
        $targets.Add($serviceLog.FullName)
    } catch [IO.IOException] { continue }
}
$deleted = @()
foreach ($target in @($targets | Select-Object -Unique)) {
    $resolved = (Resolve-Path -LiteralPath $target).ProviderPath
    if (-not $resolved.StartsWith($projectRoot + '\',[StringComparison]::OrdinalIgnoreCase)) { throw "Target outside project: $resolved" }
    $ancestor = $resolved
    while ($ancestor.Length -ge $projectRoot.Length) {
        $entry = Get-Item -LiteralPath $ancestor -Force
        if ($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Reparse point refused: $ancestor" }
        if ($ancestor -eq $projectRoot) { break }
        $ancestor = Split-Path -Parent $ancestor
    }
    $entry = Get-Item -LiteralPath $resolved -Force
    $children = if ($entry.PSIsContainer) { @(Get-ChildItem -LiteralPath $resolved -Recurse -Force) } else { @($entry) }
    if (@($children | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }).Count) { throw "Reparse child refused: $resolved" }
    $bytes = ($children | Where-Object { -not $_.PSIsContainer } | Measure-Object -Property Length -Sum).Sum
    $deleted += [pscustomobject]@{ path=$resolved; bytes=[long]$bytes }
    Remove-Item -LiteralPath $resolved -Recurse -Force
}
$result = [ordered]@{ action='latest_only_cleanup_completed'; project_root=$projectRoot; completed_at_utc=[DateTime]::UtcNow.ToString('o'); current_source_build=$manifest.build_id; current_game_preview=$native.build_id; current_iff_sha256=$report.output_sha256; deleted=$deleted; deleted_bytes=($deleted | Measure-Object -Property bytes -Sum).Sum }
$result | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $projectRoot 'validation/cleanup-current.json') -Encoding UTF8
Write-Output "Removed $($deleted.Count) obsolete entries; $($result.deleted_bytes) bytes. Latest IFF, previews, source and references retained."
