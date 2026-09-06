# Shared by rig.ps1 and lipsync.ps1. Paths in local config are repo-relative;
# paths explicitly passed on the command line are relative to the caller.
function Read-PipelineConfig([string]$Path) {
    if (Test-Path -LiteralPath $Path -PathType Leaf) {
        return Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
    }
    return [pscustomobject]@{}
}

function Get-PipelineSetting($Config, [string]$Name, [string]$Explicit, [string]$Root) {
    if ($Explicit) { return $Explicit }
    $property = $Config.PSObject.Properties[$Name]
    if ($property -and $property.Value) {
        $value = [string]$property.Value
        if ($Name -in @('rig', 'profile') -or $value.Contains('/') -or $value.Contains('\')) {
            if (-not [IO.Path]::IsPathRooted($value)) { return Join-Path $Root $value }
        }
        return $value
    }
    return $null
}

function Resolve-PipelineFile([string]$Path, [string]$Label) {
    if (-not $Path -or -not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Label not found: '$Path'. Supply its path or configure pipeline.local.json."
    }
    return (Get-Item -LiteralPath $Path).FullName
}

function Resolve-PipelineTool([string]$Explicit, [string]$EnvName, [string]$Command) {
    $value = $Explicit
    if (-not $value) { $value = [Environment]::GetEnvironmentVariable($EnvName) }
    if (-not $value) { $value = $Command }
    if (Test-Path -LiteralPath $value -PathType Leaf) { return (Get-Item -LiteralPath $value).FullName }
    $found = Get-Command -Name $value -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($found) { return $found.Source }
    $install = switch ($Command) {
        'blender' { 'Download/install Blender from https://www.blender.org/download/ (tested: 5.1.1).' }
        'rhubarb' { 'Download your OS archive from https://github.com/DanielSWolf/rhubarb-lip-sync/releases and extract the ENTIRE archive, keeping recognizer resources beside the executable.' }
        default { 'Install the requested executable.' }
    }
    throw "$Command not found. $install Pass -$Command, set $EnvName, or add its executable directory to PATH."
}

function Resolve-PipelineOutput([string]$Path, [string[]]$Inputs) {
    $full = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Path)
    if ([IO.Path]::GetExtension($full) -ine '.blend') { throw 'Output must end in .blend.' }
    if ($Inputs -icontains $full) { throw 'Output must not overwrite an input file.' }
    [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($full)) | Out-Null
    return $full
}

function Assert-PipelineRhubarbResources([string]$Executable, [string]$Recognizer) {
    $resources = Join-Path ([IO.Path]::GetDirectoryName($Executable)) 'res/sphinx'
    if ($Recognizer -eq 'pocketSphinx' -and -not (Test-Path -LiteralPath $resources -PathType Container)) {
        throw "Rhubarb recognizer resources missing: $resources. Download https://github.com/DanielSWolf/rhubarb-lip-sync/releases and extract the complete archive beside the executable; keep res/sphinx intact."
    }
}
