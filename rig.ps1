<#
.SYNOPSIS
Build a face rig and measurement report from a prepared Blender source.
.EXAMPLE
.\rig.ps1 .\work\character\source.blend -MouthMode aperture -SealRest 0.5
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory, Position=0)][string]$Source,
    [string]$Output,
    [string]$Object = 'head',
    [string]$Teeth = 'upper_jaw,lower_jaw',
    [string]$Tongue = 'tongue',
    [ValidateSet('auto','aperture','invaginated')][string]$MouthMode = 'auto',
    [ValidateSet('Keep','Split','Auto')][string]$SeamMode = 'Keep',
    [ValidateRange(0,1)][double]$SealRest = 1.0,
    [switch]$Align,
    [switch]$WeldCoincident,
    [switch]$NoTongue,
    [switch]$Basic,
    [string]$Blender
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'scripts/pipeline-common.ps1')
$config = Read-PipelineConfig (Join-Path $PSScriptRoot 'pipeline.local.json')
$blenderPath = Resolve-PipelineTool (Get-PipelineSetting $config 'blender' $Blender $PSScriptRoot) 'BLENDER_PATH' 'blender'
$sourcePath = Resolve-PipelineFile $Source 'Source .blend'
if ([IO.Path]::GetExtension($sourcePath) -ine '.blend') { throw 'Source must be a prepared .blend file.' }
if (-not $Output) {
    $Output = Join-Path ([IO.Path]::GetDirectoryName($sourcePath)) ([IO.Path]::GetFileNameWithoutExtension($sourcePath) + '_rig.blend')
}
$outputPath = Resolve-PipelineOutput $Output @($sourcePath)
$reportPath = [IO.Path]::ChangeExtension($outputPath, '.json')
$arguments = @('--background', $sourcePath, '--python-exit-code', '1',
    '--python', (Join-Path $PSScriptRoot 'autorig.py'), '--', '--obj', $Object,
    '--mouth-mode', $MouthMode, '--seal-rest', $SealRest.ToString([Globalization.CultureInfo]::InvariantCulture),
    '--out', $outputPath, '--json', $reportPath)
if ($Teeth) { $arguments += @('--teeth', $Teeth) }
if ($NoTongue) { $arguments += '--no-tongue' }
elseif ($Tongue) { $arguments += @('--tongue-object', $Tongue) }
if ($SeamMode -eq 'Keep') { $arguments += '--no-split-seam' }
if ($SeamMode -eq 'Split') { $arguments += '--split-seam' }
if ($Align) { $arguments += '--align' }
if ($WeldCoincident) { $arguments += '--weld-coincident' }
if (-not $Basic) { $arguments += '--arkit' }
& $blenderPath @arguments
if ($LASTEXITCODE -ne 0) {
    throw "Build/checks did not pass (exit $LASTEXITCODE). Review Blender output; if saved, inspect $reportPath and $outputPath."
}
if (-not (Test-Path -LiteralPath $reportPath -PathType Leaf) -or -not (Test-Path -LiteralPath $outputPath -PathType Leaf)) {
    throw 'Blender did not produce both the rig and report.'
}
Write-Host "Saved: $outputPath"
Write-Host "Report: $reportPath"
Write-Host 'Inspect neutral, jaw opening and blink before treating this as an approved rig.'
