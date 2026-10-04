param([Parameter(Mandatory=$true)][string]$AppDirectory)
$ErrorActionPreference = 'Stop'
$Executable = Join-Path $AppDirectory 'DescargaFacil.exe'
$Resources = Join-Path $AppDirectory '_internal'
foreach ($File in @('vendor\ffmpeg.exe', 'vendor\ffprobe.exe', 'vendor\deno.exe', 'vcruntime140.dll')) {
    if (-not (Test-Path (Join-Path $Resources $File))) { throw "Componente no incluido: $File" }
}
# Test the packaged application without Python, FFmpeg or Deno on PATH.
$SavedPath = $env:PATH
$SavedPlatform = $env:QT_QPA_PLATFORM
try {
    $env:PATH = "$env:SystemRoot\System32;$env:SystemRoot"
    $env:QT_QPA_PLATFORM = 'offscreen'
    $Check = Start-Process -FilePath $Executable -ArgumentList '--self-check' -NoNewWindow -Wait -PassThru
    if ($Check.ExitCode -ne 0) { throw 'La aplicación empaquetada no encuentra todos sus componentes.' }
    $Smoke = Start-Process -FilePath $Executable -ArgumentList '--smoke-test' -NoNewWindow -Wait -PassThru
    if ($Smoke.ExitCode -ne 0) { throw 'La interfaz empaquetada no pudo abrirse.' }
} finally {
    $env:PATH = $SavedPath
    $env:QT_QPA_PLATFORM = $SavedPlatform
}
