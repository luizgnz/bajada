param([Parameter(Mandatory=$true)][string]$Installer)
$ErrorActionPreference = 'Stop'
$Reports = Join-Path $PSScriptRoot 'validation-results'
New-Item -ItemType Directory -Force $Reports | Out-Null
$Destination = Join-Path $env:TEMP 'Bajada prueba Áé\Aplicación'
$OS = Get-CimInstance Win32_OperatingSystem
@{ caption=$OS.Caption; version=$OS.Version; architecture=$OS.OSArchitecture;
   installer_sha256=(Get-FileHash $Installer -Algorithm SHA256).Hash;
   signature=(Get-AuthenticodeSignature $Installer).Status.ToString();
   smart_app_control=(Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\CI\Policy' -ErrorAction SilentlyContinue).VerifiedAndReputablePolicyState
} | ConvertTo-Json | Set-Content "$Reports/environment.json" -Encoding utf8
function Invoke-Install([string]$File, [string]$Name) {
    $Log = Join-Path $Reports "$Name.log"
    $Process = Start-Process $File -ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/TASKS=""',"/DIR=`"$Destination`"","/LOG=`"$Log`"") -PassThru
    if (-not $Process.WaitForExit(180000)) { Stop-Process -Id $Process.Id -Force; throw 'El instalador no terminó.' }
    $Process.Refresh()
    if ($Process.ExitCode -ne 0) { throw "Falló $Name ($($Process.ExitCode))." }
}
# Verify the original published installer, then replace it with the candidate.
$Old = Join-Path $env:TEMP 'Bajada-original.exe'
Invoke-WebRequest 'https://github.com/luizgnz/bajada/releases/download/v0.7.0/Bajada-Setup.exe' -OutFile $Old -MaximumRetryCount 3
if ((Get-FileHash $Old -Algorithm SHA256).Hash.ToLower() -ne 'ae26dd735aa635c0d614070db4cdaa999de398c6fc82444eb0e733db874832e7') { throw 'El instalador original no coincide con su SHA256.' }
Invoke-Install $Old 'original-install'
$OriginalExe = Join-Path $Destination 'DescargaFacil.exe'
$SavedPath = $env:PATH
try {
    $env:PATH = "$env:SystemRoot\System32;$env:SystemRoot"
    $Check = Start-Process $OriginalExe -ArgumentList '--self-check' -PassThru
    if (-not $Check.WaitForExit(60000)) { Stop-Process -Id $Check.Id -Force; throw 'La comprobación original no terminó.' }
    $Check.Refresh()
    @{ self_check_exit=$Check.ExitCode; embedded_ffmpeg=(Test-Path "$Destination/_internal/vendor/ffmpeg.exe");
       embedded_ffprobe=(Test-Path "$Destination/_internal/vendor/ffprobe.exe"); downloader='DescargaFacil.exe --engine';
       external_tools_on_path=$false } | ConvertTo-Json | Set-Content "$Reports/original-components.json" -Encoding utf8
    if ($Check.ExitCode -ne 0) { throw 'El instalador publicado tiene componentes defectuosos.' }
} finally { $env:PATH=$SavedPath }
Invoke-Install $Installer 'upgrade-install'
& "$PSScriptRoot/validate-windows.ps1" -AppDirectory $Destination -ReportDirectory "$Reports/integration" -YoutubeUrl 'https://www.youtube.com/watch?v=jNQXAC9IVRw'
# A removed component must be detected and restored by reinstalling.
$Ffmpeg = Join-Path $Destination '_internal/vendor/ffmpeg.exe'
Remove-Item $Ffmpeg
$Check = Start-Process $OriginalExe -ArgumentList '--self-check' -PassThru
if (-not $Check.WaitForExit(60000)) { Stop-Process -Id $Check.Id -Force; throw 'La comprobación de daños no terminó.' }
$Check.Refresh()
if ($Check.ExitCode -eq 0) { throw 'La app no detectó FFmpeg ausente.' }
Invoke-Install $Installer 'repair-install'
$Check = Start-Process $OriginalExe -ArgumentList '--self-check' -PassThru
if (-not $Check.WaitForExit(60000)) { Stop-Process -Id $Check.Id -Force; throw 'La comprobación de reparación no terminó.' }
$Check.Refresh()
if ($Check.ExitCode -ne 0) { throw 'La reinstalación no restauró los componentes.' }
$DownloadFolder = Join-Path $env:USERPROFILE 'Videos/Bajada'
if (-not (Test-Path $DownloadFolder)) { throw 'El instalador no creó la carpeta de descargas.' }
$Sentinel = Join-Path $DownloadFolder 'conservar-prueba.txt'
'Conservar archivos de usuario' | Set-Content $Sentinel
$Uninstall = Start-Process (Join-Path $Destination 'unins000.exe') -ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART') -PassThru
if (-not $Uninstall.WaitForExit(60000)) { Stop-Process -Id $Uninstall.Id -Force; throw 'La desinstalación no terminó.' }
$Uninstall.Refresh()
if ($Uninstall.ExitCode -ne 0 -or (Test-Path $OriginalExe) -or -not (Test-Path $Sentinel)) { throw 'La desinstalación no conservó los datos o no retiró la app.' }
@{ upgrade=$true; missing_component_detected=$true; repair=$true; uninstall_preserves_downloads=$true; success=$true } | ConvertTo-Json | Set-Content "$Reports/installer.json" -Encoding utf8
