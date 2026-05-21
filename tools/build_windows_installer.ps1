param(
    [switch]$SkipInstaller
)

$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
$specPath = Join-Path $repoRoot 'build\pyinstaller\ied_launcher.spec'
$issPath = Join-Path $repoRoot 'build\installer\IEDSimulator.iss'
$bundleRoot = Join-Path $repoRoot 'dist-build'
$bundleDir = Join-Path $bundleRoot 'IEC61850_IED_Sim_Launcher'
$workPath = Join-Path $repoRoot 'build\pyinstaller_work'

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

$isccPath = Resolve-IsccPath
if (-not $isccPath) {
    throw 'Inno Setup compiler (ISCC.exe) was not found. Install Inno Setup 6 or run this script with -SkipInstaller.'
}

$bundleArg = '/DMyAppBundleDir=' + $bundleDir

Write-Host 'Building installer with Inno Setup...'
& $isccPath $bundleArg $issPath

Write-Host 'Installer build completed.'