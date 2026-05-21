param(
    [switch]$SkipInstaller,
    [switch]$NoVersionPrompt,
    [string]$Version
)

$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
$specPath = Join-Path $repoRoot 'build\pyinstaller\ied_launcher.spec'
$issPath = Join-Path $repoRoot 'build\installer\IEDSimulator.iss'
$bundleRoot = Join-Path $repoRoot 'dist-build'
$bundleDir = Join-Path $bundleRoot 'IEC61850_IED_Sim_Launcher'
$workPath = Join-Path $repoRoot 'build\pyinstaller_work'
$installerRoot = Join-Path $repoRoot 'dist-installer'
$installerTempRoot = Join-Path $repoRoot 'build\installer_output'

function Get-InstallerVersion {
    param(
        [string]$Path
    )

    foreach ($line in Get-Content $Path) {
        if ($line -match '^\s*#define\s+MyAppVersion\s+"(?<version>\d+\.\d+\.\d+)"$') {
            return $Matches['version']
        }
    }

    throw "Could not find MyAppVersion in $Path"
}

function Set-InstallerVersion {
    param(
        [string]$Path,
        [string]$NewVersion
    )

    $lines = Get-Content $Path
    $updated = $false

    for ($index = 0; $index -lt $lines.Count; $index++) {
        if ($lines[$index] -match '^\s*#define\s+MyAppVersion\s+"(?<version>\d+\.\d+\.\d+)"$') {
            $indent = ([regex]::Match($lines[$index], '^\s*')).Value
            $lines[$index] = '{0}#define MyAppVersion "{1}"' -f $indent, $NewVersion
            $updated = $true
            break
        }
    }

    if (-not $updated) {
        throw "Could not update MyAppVersion in $Path"
    }

    Set-Content -Path $Path -Value $lines
}

function Test-IsInteractiveSession {
    try {
        return [Environment]::UserInteractive -and -not [Console]::IsInputRedirected -and -not [Console]::IsOutputRedirected
    }
    catch {
        return $false
    }
}

function Read-DefaultAnswer {
    param(
        [string]$Prompt,
        [bool]$DefaultYes
    )

    $suffix = if ($DefaultYes) { '[Y/n]' } else { '[y/N]' }

    if (-not (Test-IsInteractiveSession)) {
        $defaultLabel = if ($DefaultYes) { 'yes' } else { 'no' }
        Write-Host "$Prompt $suffix (non-interactive session detected, using default: $defaultLabel)"
        return $DefaultYes
    }

    try {
        $response = Read-Host "$Prompt $suffix"
    }
    catch [System.Management.Automation.PSInvalidOperationException] {
        $defaultLabel = if ($DefaultYes) { 'yes' } else { 'no' }
        Write-Host "$Prompt $suffix (prompt unavailable in this host, using default: $defaultLabel)"
        return $DefaultYes
    }

    if ([string]::IsNullOrWhiteSpace($response)) {
        return $DefaultYes
    }

    return $response.Trim().StartsWith('y', [System.StringComparison]::OrdinalIgnoreCase)
}

function Resolve-InstallerVersion {
    param(
        [string]$CurrentVersion,
        [string]$ExplicitVersion,
        [switch]$SkipPrompt
    )

    if ($ExplicitVersion) {
        if ($ExplicitVersion -notmatch '^\d+\.\d+\.\d+$') {
            throw "Version must use the format major.minor.patch, got '$ExplicitVersion'"
        }

        return $ExplicitVersion
    }

    if ($SkipPrompt) {
        return $CurrentVersion
    }

    $parts = $CurrentVersion.Split('.')
    $major = [int]$parts[0]
    $minor = [int]$parts[1]
    $patch = [int]$parts[2]

    Write-Host "Current installer version: $CurrentVersion"

    if (Read-DefaultAnswer -Prompt 'Increment major version?' -DefaultYes:$false) {
        return '{0}.0.0' -f ($major + 1)
    }

    if (Read-DefaultAnswer -Prompt 'Increment minor version?' -DefaultYes:$false) {
        return '{0}.{1}.0' -f $major, ($minor + 1)
    }

    if (Read-DefaultAnswer -Prompt 'Increment patch version?' -DefaultYes:$true) {
        return '{0}.{1}.{2}' -f $major, $minor, ($patch + 1)
    }

    return $CurrentVersion
}

function Publish-Installer {
    param(
        [string]$BuiltInstallerPath,
        [string]$DestinationPath
    )

    $destinationDir = Split-Path -Parent $DestinationPath
    if (-not (Test-Path $destinationDir)) {
        New-Item -ItemType Directory -Path $destinationDir | Out-Null
    }

    try {
        if (Test-Path $DestinationPath) {
            Remove-Item $DestinationPath -Force
        }

        Move-Item $BuiltInstallerPath $DestinationPath -Force
        return $DestinationPath
    }
    catch {
        $timestamp = Get-Date -Format 'yyyyMMdd_HHmmss'
        $fallbackName = '{0}_{1}{2}' -f [System.IO.Path]::GetFileNameWithoutExtension($DestinationPath), $timestamp, [System.IO.Path]::GetExtension($DestinationPath)
        $fallbackPath = Join-Path $destinationDir $fallbackName
        Move-Item $BuiltInstallerPath $fallbackPath -Force
        Write-Warning ("Could not replace {0}. Published new installer as {1}. Details: {2}" -f $DestinationPath, $fallbackPath, $_.Exception.Message)
        return $fallbackPath
    }
}

function Resolve-IsccPath {
    $command = Get-Command ISCC -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }

    $candidates = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe'),
        'C:\Program Files (x86)\Inno Setup 6\ISCC.exe',
        'C:\Program Files\Inno Setup 6\ISCC.exe'
    )

    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) {
            return $candidate
        }
    }

    return $null
}

if (Test-Path $bundleRoot) {
    Remove-Item $bundleRoot -Recurse -Force
}

if (Test-Path $workPath) {
    Remove-Item $workPath -Recurse -Force
}

Write-Host 'Building launcher bundle with PyInstaller...'
& py -m PyInstaller --noconfirm --distpath $bundleRoot --workpath $workPath $specPath

if (-not (Test-Path (Join-Path $bundleDir 'IEC61850_IED_Sim_Launcher.exe'))) {
    throw 'PyInstaller build did not produce IEC61850_IED_Sim_Launcher.exe'
}

if ($SkipInstaller) {
    Write-Host "Bundle built successfully at $bundleDir"
    exit 0
}

$currentVersion = Get-InstallerVersion -Path $issPath
$targetVersion = Resolve-InstallerVersion -CurrentVersion $currentVersion -ExplicitVersion $Version -SkipPrompt:$NoVersionPrompt

if ($targetVersion -ne $currentVersion) {
    Write-Host "Updating installer version: $currentVersion -> $targetVersion"
    Set-InstallerVersion -Path $issPath -NewVersion $targetVersion
}
else {
    Write-Host "Installer version unchanged: $targetVersion"
}

$isccPath = Resolve-IsccPath
if (-not $isccPath) {
    throw 'Inno Setup compiler (ISCC.exe) was not found. Install Inno Setup 6 or run this script with -SkipInstaller.'
}

$installerBaseName = "IED_Simulator_Setup_$targetVersion"
$tempOutputDir = Join-Path $installerTempRoot $targetVersion
$tempInstallerPath = Join-Path $tempOutputDir ($installerBaseName + '.exe')
$finalInstallerPath = Join-Path $installerRoot ($installerBaseName + '.exe')

$outputDirArg = '/DMyAppOutputDir=' + $tempOutputDir
$outputBaseArg = '/DMyAppOutputBaseFilename=' + $installerBaseName
$bundleArg = '/DMyAppBundleDir=' + $bundleDir

if (Test-Path $tempOutputDir) {
    Remove-Item $tempOutputDir -Recurse -Force
}

New-Item -ItemType Directory -Path $tempOutputDir | Out-Null

Write-Host 'Building installer with Inno Setup...'
& $isccPath $bundleArg $outputDirArg $outputBaseArg $issPath

if (-not (Test-Path $tempInstallerPath)) {
    throw "Inno Setup build did not produce $tempInstallerPath"
}

$publishedInstaller = Publish-Installer -BuiltInstallerPath $tempInstallerPath -DestinationPath $finalInstallerPath

Write-Host "Installer build completed: $publishedInstaller"