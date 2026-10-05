$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (-not [Environment]::Is64BitProcess) { throw 'Usa Windows de 64 bits.' }
python -m venv .venv
if ($LASTEXITCODE -ne 0) { throw 'No se pudo crear el entorno de Python.' }
$Python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
& $Python -m pip install -r requirements-lock.txt pyinstaller pytest
if ($LASTEXITCODE -ne 0) { throw 'No se pudieron instalar las dependencias.' }
& $Python -m pytest tests -q
if ($LASTEXITCODE -ne 0) { throw 'Las pruebas fallaron.' }
New-Item -ItemType Directory -Force vendor, build-tools | Out-Null
$Headers = @{ 'User-Agent' = 'Bajada-Build' }
$FfmpegRelease = Invoke-RestMethod 'https://api.github.com/repos/BtbN/FFmpeg-Builds/releases/latest' -Headers $Headers
$FfmpegAsset = $FfmpegRelease.assets | Where-Object { $_.name -eq 'ffmpeg-n8.1-latest-win64-lgpl-shared-8.1.zip' } | Select-Object -First 1
if (-not $FfmpegAsset) { throw 'No se encontró la compilación LGPL de FFmpeg esperada.' }
Invoke-WebRequest -MaximumRetryCount 3 -TimeoutSec 120 $FfmpegAsset.browser_download_url -OutFile build-tools/ffmpeg.zip
Expand-Archive build-tools/ffmpeg.zip build-tools/ffmpeg -Force
$FfmpegFolder = (Get-ChildItem build-tools/ffmpeg -Directory | Select-Object -First 1).FullName
Copy-Item "$FfmpegFolder\bin\*" vendor -Recurse -Force
foreach ($Notice in @('LICENSE.txt', 'LICENSE', 'README.txt', 'README.md')) {
    if (Test-Path "$FfmpegFolder\$Notice") { Copy-Item "$FfmpegFolder\$Notice" "vendor/FFMPEG-$Notice" }
}
if (Test-Path "$FfmpegFolder\licenses") { Copy-Item "$FfmpegFolder\licenses" vendor/ffmpeg-licenses -Recurse -Force }
$FfmpegVersion = & vendor/ffmpeg.exe -version
$FfmpegVersion | Set-Content vendor/FFMPEG-BUILD.txt -Encoding utf8
$BuildTag = Invoke-RestMethod 'https://api.github.com/repos/BtbN/FFmpeg-Builds/git/ref/tags/latest' -Headers $Headers
$BuildRevision = $BuildTag.object.sha
if ($BuildTag.object.type -eq 'tag') { $BuildRevision = (Invoke-RestMethod "https://api.github.com/repos/BtbN/FFmpeg-Builds/git/tags/$BuildRevision" -Headers $Headers).object.sha }
$FfmpegSourceRevision = 'n8.1'
if (($FfmpegVersion -join ' ') -match '-g([0-9a-f]{7,40})') { $FfmpegSourceRevision = $Matches[1] }
@("FFmpeg source: https://github.com/FFmpeg/FFmpeg/archive/$FfmpegSourceRevision.tar.gz",
  "FFmpeg build recipes and dependency source locations: https://github.com/BtbN/FFmpeg-Builds/tree/$BuildRevision",
  "FFmpeg build recipes archive: https://github.com/BtbN/FFmpeg-Builds/archive/$BuildRevision.tar.gz") | Set-Content vendor/component-sources.txt -Encoding utf8
$DenoRelease = Invoke-RestMethod 'https://api.github.com/repos/denoland/deno/releases/latest' -Headers $Headers
$DenoAsset = $DenoRelease.assets | Where-Object { $_.name -eq 'deno-x86_64-pc-windows-msvc.zip' } | Select-Object -First 1
Invoke-WebRequest -MaximumRetryCount 3 -TimeoutSec 120 $DenoAsset.browser_download_url -OutFile build-tools/deno.zip
Expand-Archive build-tools/deno.zip vendor -Force
Invoke-WebRequest -MaximumRetryCount 3 -TimeoutSec 120 "https://raw.githubusercontent.com/denoland/deno/$($DenoRelease.tag_name)/LICENSE.md" -OutFile vendor/DENO-LICENSE.md
"Deno source: https://github.com/denoland/deno/archive/refs/tags/$($DenoRelease.tag_name).tar.gz" | Add-Content vendor/component-sources.txt -Encoding utf8
New-Item -ItemType Directory -Force licenses | Out-Null
Invoke-WebRequest -MaximumRetryCount 3 -TimeoutSec 120 'https://www.gnu.org/licenses/lgpl-3.0.txt' -OutFile licenses/LGPL-3.0.txt
Invoke-WebRequest -MaximumRetryCount 3 -TimeoutSec 120 'https://www.gnu.org/licenses/gpl-3.0.txt' -OutFile licenses/GPL-3.0.txt
& $Python collect-licenses.py licenses
if ($LASTEXITCODE -ne 0) { throw 'No se pudieron preparar los avisos de los componentes.' }
& $Python -m PyInstaller --noconfirm --clean --onedir --console --name DescargaFacil --icon assets/bajada.ico --collect-all yt_dlp --collect-all yt_dlp_ejs --add-data 'vendor;vendor' --add-data 'licenses;licenses' --add-data 'THIRD-PARTY.md;.' --add-data 'LICENSE;.' main.py
if ($LASTEXITCODE -ne 0) { throw 'No se pudo crear la aplicación.' }
& $Python create-manifest.py dist/DescargaFacil/_internal
if ($LASTEXITCODE -ne 0) { throw 'No se pudo preparar la comprobación de componentes.' }
& (Join-Path $PSScriptRoot 'validate-windows.ps1') -AppDirectory (Join-Path $PSScriptRoot 'dist\DescargaFacil')
# Windows executable has a console subsystem so the download child can emit progress.
# The graphical parent detaches its console in main.py; children retain redirected output.
$Compiler = Get-Command ISCC.exe -ErrorAction SilentlyContinue
if (-not $Compiler) {
    $CompilerPath = 'C:\Program Files (x86)\Inno Setup 6\ISCC.exe'
    if (-not (Test-Path $CompilerPath)) { throw 'Instala Inno Setup 6 para crear el instalador. La app está en dist/DescargaFacil.' }
} else { $CompilerPath = $Compiler.Source }
& $CompilerPath installer/setup.iss
if ($LASTEXITCODE -ne 0) { throw 'No se pudo crear el instalador.' }
$TestInstall = Join-Path $PSScriptRoot 'build-tools\installed-test'
$Installer = Join-Path $PSScriptRoot 'dist\installer\Bajada-Setup.exe'
$InstallCheck = Start-Process -FilePath $Installer -ArgumentList @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/TASKS=""', "/DIR=`"$TestInstall`"") -Wait -PassThru
if ($InstallCheck.ExitCode -ne 0) { throw 'Falló la instalación de prueba.' }
& (Join-Path $PSScriptRoot 'validate-windows.ps1') -AppDirectory $TestInstall
Write-Host 'Instalador listo en dist/installer/Bajada-Setup.exe'

$Digest = (Get-FileHash $Installer -Algorithm SHA256).Hash.ToLower()
"$Digest  Bajada-Setup.exe" | Set-Content (Join-Path $PSScriptRoot 'dist/installer/SHA256SUMS.txt') -Encoding ascii
