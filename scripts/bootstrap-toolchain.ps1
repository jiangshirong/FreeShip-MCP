param([string]$InstallDirectory = (Join-Path $PSScriptRoot '..\.toolchain\lazarus'))
$ErrorActionPreference = 'Stop'
$cache = Join-Path $PSScriptRoot '..\.toolchain'
New-Item -ItemType Directory -Force -Path $cache | Out-Null
$installer = Join-Path $cache 'lazarus-3.2-fpc-3.2.2-win64.exe'
$url = 'https://download.lazarus-ide.org/Lazarus%20Windows%2064%20bits/Lazarus%203.2/lazarus-3.2-fpc-3.2.2-win64.exe'
$sha256 = '78605F116251C60595108FCF41004EE3DDC0B5CC7C22143E52A53FA1ED629D54'
if (!(Test-Path -LiteralPath $installer)) {
    Invoke-WebRequest -Uri $url -OutFile $installer
}
if ((Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash -ne $sha256) {
    throw 'Toolchain installer checksum mismatch; remove the cached download and retry.'
}
$destination = [IO.Path]::GetFullPath($InstallDirectory)
# Silent command-line installation; this does not launch or operate the IDE.
$taskInstaller = Start-Process -FilePath $installer -ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/NOICONS','/SP-',('/DIR="' + $destination + '"')) -WindowStyle Hidden -PassThru -Wait
if ($taskInstaller.ExitCode -ne 0) { throw "Toolchain installation failed ($($taskInstaller.ExitCode))." }
