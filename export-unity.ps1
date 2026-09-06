<# .SYNOPSIS
Merge an artist-assembled face/body rig and export a neutral runtime FBX.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory,Position=0)][string]$Source,
    [Parameter(Mandatory)][string]$BodyArmature,
    [Parameter(Mandatory)][string]$FaceArmature,
    [Parameter(Mandatory)][string]$HeadBone,
    [string]$ApplyBodyBooleans,
    [string]$Output, [string]$Blender
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'scripts/pipeline-common.ps1')
$config = Read-PipelineConfig (Join-Path $PSScriptRoot 'pipeline.local.json')
$tool = Resolve-PipelineTool (Get-PipelineSetting $config 'blender' $Blender $PSScriptRoot) 'BLENDER_PATH' 'blender'
$inputPath = Resolve-PipelineFile $Source 'Assembled .blend'
if (-not $Output) { $Output = Join-Path ([IO.Path]::GetDirectoryName($inputPath)) ([IO.Path]::GetFileNameWithoutExtension($inputPath) + '_unity.blend') }
$out = Resolve-PipelineOutput $Output @($inputPath)
$fbx = [IO.Path]::ChangeExtension($out, '.fbx')
$arguments = @('--background', $inputPath, '--python-exit-code', '1', '--python',
    (Join-Path $PSScriptRoot 'scripts/face_pipeline/unity_prep.py'), '--',
    '--body-armature', $BodyArmature, '--face-armature', $FaceArmature,
    '--head-bone', $HeadBone, '--out', $out, '--fbx', $fbx)
if ($ApplyBodyBooleans) { $arguments += @('--apply-body-booleans', $ApplyBodyBooleans) }
& $tool @arguments
if ($LASTEXITCODE -ne 0) { throw 'Skeleton merge/export failed. Review the reported handoff issue.' }
if (-not (Test-Path -LiteralPath $out) -or -not (Test-Path -LiteralPath $fbx)) { throw 'Export outputs missing.' }
Write-Host "Saved: $out"
Write-Host "Unity FBX: $fbx (copy its textures too). Verify the Humanoid mapping and blendshape deformation in Unity."
