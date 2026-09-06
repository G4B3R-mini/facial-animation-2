<# .SYNOPSIS
Copy the maintained runtime and generic editor setup into a Unity project.
Existing differing source files require -UpdateExisting; .meta GUIDs are preserved.
#>
[CmdletBinding()]
param([Parameter(Mandatory,Position=0)][string]$UnityProject, [switch]$UpdateExisting)
$ErrorActionPreference = 'Stop'
$project = (Resolve-Path -LiteralPath $UnityProject).Path
if (-not (Test-Path -LiteralPath (Join-Path $project 'ProjectSettings/ProjectVersion.txt'))) { throw 'Not a Unity project: ProjectSettings/ProjectVersion.txt missing.' }
$names = @('ConversationalGaze','ConversationExpressionDriver','FaceMeshUtil','RhubarbVisemePlayer',
    'SpeechAnalysis','SpeechGestureDriver','SpeechPerformanceProfile','SubtleBodyDriver','RuntimeLipSyncService')
$operations = @()
foreach ($name in $names + @('CharacterPipelineSetup','CharacterRhubarb')) {
    $relative = if ($name -in @('CharacterPipelineSetup','CharacterRhubarb')) { "Editor/$name.cs" } else { "$name.cs" }
    $source = Join-Path $PSScriptRoot "unity/$relative"
    $matches = @(Get-ChildItem -LiteralPath (Join-Path $project 'Assets') -Filter "$name.cs" -Recurse -File)
    if ($matches.Count -gt 1) { throw "Multiple $name.cs files found. Resolve duplicate classes before installation." }
    $destination = if ($matches.Count) { $matches[0].FullName } else { Join-Path $project "Assets/TripoFaceRig/$relative" }
    if ((Test-Path -LiteralPath $destination) -and ((Get-FileHash -LiteralPath $source).Hash -ne (Get-FileHash -LiteralPath $destination).Hash) -and -not $UpdateExisting) {
        throw "Existing source differs: $destination. Review the diff; rerun with -UpdateExisting to replace source while retaining its .meta GUID."
    }
    $operations += [pscustomobject]@{ Source=$source; Destination=$destination }
}
foreach ($operation in $operations) {
    [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($operation.Destination)) | Out-Null
    Copy-Item -LiteralPath $operation.Source -Destination $operation.Destination
}
Write-Host 'Installed maintained Unity components. Let Unity compile, import FBX + textures + WAV + Rhubarb JSON, configure Humanoid, then open Tools > Tripo Face Rig > Character Pipeline.'
