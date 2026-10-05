param([Parameter(Mandatory=$true)][string]$AppDirectory, [string]$ReportDirectory, [string]$YoutubeUrl)
$ErrorActionPreference = 'Stop'
$Executable = Join-Path $AppDirectory 'DescargaFacil.exe'
$Resources = Join-Path $AppDirectory '_internal'
if (-not $ReportDirectory) { $ReportDirectory = Join-Path $AppDirectory 'validation' }
New-Item -ItemType Directory -Force $ReportDirectory | Out-Null
foreach ($File in @('vendor\ffmpeg.exe', 'vendor\ffprobe.exe', 'vendor\deno.exe', 'vcruntime140.dll')) {
    if (-not (Test-Path (Join-Path $Resources $File))) { throw "Componente no incluido: $File" }
}
function Invoke-BoundedApp([string[]]$Arguments, [int]$Seconds=60) {
    $Process = Start-Process -FilePath $Executable -ArgumentList $Arguments -PassThru
    if (-not $Process.WaitForExit($Seconds * 1000)) {
        & "$env:SystemRoot\System32\taskkill.exe" /PID $Process.Id /T /F | Out-Null
        throw "La app no terminó en $Seconds segundos: $Arguments"
    }
    $Process.Refresh()
    if ($Process.ExitCode -ne 0) { throw "La app falló ($($Process.ExitCode)): $Arguments" }
}
$SavedPath = $env:PATH
$SavedPlatform = $env:QT_QPA_PLATFORM
try {
    $env:PATH = "$env:SystemRoot\System32;$env:SystemRoot"
    Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue
    Invoke-BoundedApp @('--self-check')
    Invoke-BoundedApp @('--engine', '--version')
    Invoke-BoundedApp @('--smoke-test')
    $Report = Join-Path $ReportDirectory 'report.json'
    $Fixture = Join-Path $PSScriptRoot 'tests\fixtures\prueba.mp4'
    $Arguments = @('--integration-test', '--report', "`"$Report`"", '--fixture', "`"$Fixture`"")
    if ($YoutubeUrl) { $Arguments += @('--youtube-test', "`"$YoutubeUrl`"") }
    Invoke-BoundedApp $Arguments 600
    $Result = Get-Content $Report -Raw | ConvertFrom-Json
    if (-not $Result.success -or -not $Result.frozen) { throw 'Falló la descarga/conversión con la app instalada.' }
    Write-Host (Get-Content $Report -Raw)
} finally {
    $env:PATH = $SavedPath
    $env:QT_QPA_PLATFORM = $SavedPlatform
}
