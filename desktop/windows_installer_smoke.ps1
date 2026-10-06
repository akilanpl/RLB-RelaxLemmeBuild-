# Disposable Windows CI only. Never run upgrade/uninstall automation on a user's profile.
param([Parameter(Mandatory=$true)][string]$Installer)
$ErrorActionPreference = 'Stop'
if ($env:CI -ne 'true' -or $env:OS -ne 'Windows_NT') { throw 'This installer check requires a disposable Windows CI user.' }
$Installer = (Resolve-Path $Installer).Path
$InstallDir = Join-Path $env:RUNNER_TEMP 'RLB-install-smoke'
$AppExe = Join-Path $InstallDir 'RLB.exe'
$Project = Join-Path $env:RUNNER_TEMP 'RLB-project-preservation-smoke'
New-Item -ItemType Directory -Force -Path $Project | Out-Null
$ProjectFile = Join-Path $Project 'user-work.txt'
Set-Content -NoNewline -Path $ProjectFile -Value 'preserve selected project'
function RunInstaller {
  $process = Start-Process -FilePath $Installer -ArgumentList @('/S', "/D=$InstallDir") -PassThru -Wait
  if ($process.ExitCode -ne 0) { throw "Installer returned $($process.ExitCode)" }
  if (!(Test-Path $AppExe)) { throw 'Installed executable is missing.' }
}
function LaunchAndWait {
  $logPaths = @((Join-Path $env:APPDATA 'rlb-desktop\logs\desktop.log'), (Join-Path $env:APPDATA 'RLB\logs\desktop.log'))
  $oldLengths = @{}
  foreach ($file in $logPaths) { $oldLengths[$file] = if (Test-Path $file) { (Get-Content -Raw $file).Length } else { 0 } }
  $process = Start-Process -FilePath $AppExe -PassThru
  $deadline = (Get-Date).AddSeconds(90)
  do {
    foreach ($file in $logPaths) {
      if (Test-Path $file) {
        $content = Get-Content -Raw $file
        if ($content.Length -gt $oldLengths[$file] -and $content.Substring($oldLengths[$file]) -match 'Desktop ready:') {
          return @{ Process = $process; UserData = (Split-Path (Split-Path $file)); Log = $file }
        }
      }
    }
    $process.Refresh()
    if ($process.HasExited) { throw 'Installed RLB exited before first-launch readiness.' }
    Start-Sleep -Milliseconds 500
  } while ((Get-Date) -lt $deadline)
  throw 'Installed RLB did not reach first-launch readiness.'
}
function QuitRLB($process) {
  Start-Process -FilePath $AppExe -ArgumentList '--quit-for-update' -Wait
  Wait-Process -Id $process.Id -Timeout 45 -ErrorAction SilentlyContinue
  $process.Refresh()
  if (!$process.HasExited) { throw 'Installed RLB failed to quit cleanly.' }
}
RunInstaller
& python "$PSScriptRoot\smoke_packaged.py" --resources "$InstallDir\resources"
if ($LASTEXITCODE -ne 0) { throw 'Installed runtime assets failed their process checks.' }
$launch = LaunchAndWait
if (!(Test-Path (Join-Path $launch.UserData 'credentials\provider-key.bin'))) { throw 'OS-protected provider key was not initialized.' }
$sentinel = Join-Path $launch.UserData 'upgrade-preservation-smoke.txt'
Set-Content -NoNewline -Path $sentinel -Value 'preserve RLB per-user data'
$runtime = Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -eq "$InstallDir\resources\backend\rlb-runtime.exe" }
if (!$runtime) { throw 'Installed worker/runtime is not running.' }
$listeners = Get-NetTCPConnection -State Listen | Where-Object { $_.OwningProcess -in @($runtime.ProcessId) }
if (!$listeners -or ($listeners | Where-Object { $_.LocalAddress -notin @('127.0.0.1', '::1') })) { throw 'Local runtime is not exclusively loopback-bound.' }
$launch.Process.Refresh()
if (!$launch.Process.CloseMainWindow()) { throw 'Installed app did not expose its first-launch window.' }
Start-Sleep -Seconds 1
$launch.Process.Refresh()
if ($launch.Process.HasExited) { throw 'Closing the window terminated background work.' }
# Upgrade while the app is running: setup must use the authenticated shutdown handoff.
RunInstaller
if ((Get-Content -Raw $sentinel) -ne 'preserve RLB per-user data') { throw 'Upgrade changed per-user data.' }
$launch = LaunchAndWait
QuitRLB $launch.Process
$uninstaller = Get-ChildItem $InstallDir -Filter '*Uninstall*.exe' | Select-Object -First 1
if (!$uninstaller) { throw 'Uninstaller is missing.' }
$uninstall = Start-Process -FilePath $uninstaller.FullName -ArgumentList '/S' -PassThru -Wait
if ($uninstall.ExitCode -ne 0) { throw 'Uninstall failed.' }
if ((Get-Content -Raw $sentinel) -ne 'preserve RLB per-user data') { throw 'Uninstall removed per-user data.' }
if ((Get-Content -Raw $ProjectFile) -ne 'preserve selected project') { throw 'Installer/uninstaller changed user work.' }
Write-Output 'PASS: Windows installer, installed runtime assets, first launch, OS credential storage, loopback binding, close-to-background, upgrade, clean quit and data-preserving uninstall.'
