<# .SYNOPSIS
Report all missing prerequisites and installation instructions for a pipeline stage.
#>
[CmdletBinding()]
param(
    [ValidateSet('Head','Export','Unity')][string]$Stage = 'Head',
    [string]$Blender, [string]$Rhubarb, [string]$UnityProject,
    [ValidateSet('pocketSphinx','phonetic')][string]$Recognizer = 'pocketSphinx'
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'scripts/pipeline-common.ps1')
$config = Read-PipelineConfig (Join-Path $PSScriptRoot 'pipeline.local.json')
$missing = @()
$names = @('blender')
if ($Stage -eq 'Unity') { $names = @() }
if ($Stage -eq 'Head') { $names += 'rhubarb' }
foreach ($name in $names) {
    try {
        $explicit = if ($name -eq 'blender') { $Blender } else { $Rhubarb }
        $tool = Resolve-PipelineTool (Get-PipelineSetting $config $name $explicit $PSScriptRoot) ($name.ToUpper() + '_PATH') $name
        $version = & $tool --version 2>&1
        if ($LASTEXITCODE -ne 0) { throw "$name could not run: $version" }
        if ($name -eq 'rhubarb') { Assert-PipelineRhubarbResources $tool $Recognizer }
        Write-Host "OK $name : $tool ($($version | Select-Object -First 1))"
    } catch { $missing += $_.Exception.Message }
}
if ($Stage -eq 'Unity') {
    if (-not $UnityProject -or -not (Test-Path -LiteralPath (Join-Path $UnityProject 'ProjectSettings/ProjectVersion.txt'))) {
        $missing += 'Unity project missing. Install Unity Hub from https://unity.com/download and open/create a project. Pass -UnityProject <project-folder>; use its ProjectSettings/ProjectVersion.txt editor version.'
    } else { Write-Host "OK Unity project: $UnityProject" }
}
if ($missing.Count) {
    foreach ($item in $missing) { Write-Host "MISSING: $item" -ForegroundColor Yellow }
    throw "$($missing.Count) prerequisite(s) missing. Install/configure these and rerun doctor.ps1."
}
Write-Host 'Prerequisites found. The actual Rhubarb run also checks recognizer resources. MCP is optional for file processing; live playback requires a connected editor.'
