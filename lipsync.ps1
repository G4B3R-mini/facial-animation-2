<#
.SYNOPSIS
Generate Rhubarb timings and animate an approved face rig.
.EXAMPLE
.\lipsync.ps1 -Audio './work/dialogue.wav' -Rig './work/character/source_rig.blend'
.EXAMPLE
.\lipsync.ps1 './work/dialogue.wav' -Output './work/character/talking.blend'
.EXAMPLE
.\lipsync.ps1 './work/dialogue.wav' -Recognizer phonetic
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory, Position = 0)]
    [string]$Audio,
    [string]$Output,
    [string]$Rig,
    [string]$Profile,
    [string]$Object,
    [ValidateSet('pocketSphinx', 'phonetic')]
    [string]$Recognizer = 'pocketSphinx',
    [ValidateRange(1, 120)]
    [int]$Fps = 30,
    [string]$Blender,
    [string]$Rhubarb
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'scripts/pipeline-common.ps1')
$config = Read-PipelineConfig (Join-Path $PSScriptRoot 'pipeline.local.json')

function Resolve-InputFile([string]$Path, [string]$Label) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Label not found: $Path"
    }
    return (Get-Item -LiteralPath $Path).FullName
}

$audioPath = Resolve-InputFile $Audio 'Audio clip'
if ([IO.Path]::GetExtension($audioPath) -ine '.wav') {
    throw 'Rhubarb requires a WAV clip. Export your audio as WAV first.'
}
$rigPath = Resolve-PipelineFile (Get-PipelineSetting $config 'rig' $Rig $PSScriptRoot) 'Rig (-Rig)'
# An explicitly selected rig must not inherit another character's local profile.
$profileSetting = $Profile
if (-not $Rig) { $profileSetting = Get-PipelineSetting $config 'profile' $Profile $PSScriptRoot }
$profilePath = $null
if ($profileSetting) { $profilePath = Resolve-PipelineFile $profileSetting 'Measurement profile (-Profile)' }
$blenderPath = Resolve-PipelineTool (Get-PipelineSetting $config 'blender' $Blender $PSScriptRoot) 'BLENDER_PATH' 'blender'
$rhubarbPath = Resolve-PipelineTool (Get-PipelineSetting $config 'rhubarb' $Rhubarb $PSScriptRoot) 'RHUBARB_PATH' 'rhubarb'
Assert-PipelineRhubarbResources $rhubarbPath $Recognizer
$animatePath = Resolve-InputFile (
    Join-Path $PSScriptRoot 'scripts/face_pipeline/reanimate.py'
) 'Animation script'

if (-not $Output) {
    $clipName = [IO.Path]::GetFileNameWithoutExtension($audioPath)
    $rigName = [IO.Path]::GetFileNameWithoutExtension($rigPath)
    $Output = Join-Path ([IO.Path]::GetDirectoryName($rigPath)) "${rigName}_${clipName}_lipsync.blend"
}
$outputPath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Output)
if ([IO.Path]::GetExtension($outputPath) -ine '.blend') {
    throw '-Output must end in .blend.'
}
$cuesPath = [IO.Path]::ChangeExtension($outputPath, '.rhubarb.json')
foreach ($inputPath in @($audioPath, $rigPath, $profilePath, $blenderPath, $rhubarbPath, $animatePath)) {
    if ($outputPath -ieq $inputPath -or $cuesPath -ieq $inputPath) {
        throw 'Choose an output path that does not overwrite an input file.'
    }
}
$outputDirectory = [IO.Path]::GetDirectoryName($outputPath)
[IO.Directory]::CreateDirectory($outputDirectory) | Out-Null

Write-Host '1/2 Generating Rhubarb mouth timings...'
& $rhubarbPath -r $Recognizer -f json -o $cuesPath $audioPath
if ($LASTEXITCODE -ne 0) {
    throw "Rhubarb failed (exit $LASTEXITCODE). See the error above. For missing recognizer data, extract the complete distribution from https://github.com/DanielSWolf/rhubarb-lip-sync/releases including res/sphinx. Animation was not started."
}
if (-not (Test-Path -LiteralPath $cuesPath -PathType Leaf)) {
    throw 'Rhubarb did not produce a timing file.'
}
$cues = Get-Content -LiteralPath $cuesPath -Raw | ConvertFrom-Json
if (-not $cues.PSObject.Properties['mouthCues']) {
    throw 'Rhubarb output is missing mouthCues.'
}

Write-Host '2/2 Animating the rig and adding the audio...'
$blenderArguments = @(
    '--background', $rigPath, '--python-exit-code', '1',
    '--python', $animatePath, '--', $outputPath,
    '--cues', $cuesPath,
    '--audio', $audioPath, '--fps', "$Fps"
)
if ($profilePath) { $blenderArguments += @('--profile', $profilePath) }
if ($Object) { $blenderArguments += @('--obj', $Object) }
& $blenderPath @blenderArguments
if ($LASTEXITCODE -ne 0) {
    throw "Blender failed (exit $LASTEXITCODE). See its error above."
}
if (-not (Test-Path -LiteralPath $outputPath -PathType Leaf)) {
    throw 'Blender did not save the animated rig.'
}

Write-Host "`nSaved: $outputPath"
Write-Host "Timings: $cuesPath"
Write-Host 'Open the .blend file and press Space to play.'
