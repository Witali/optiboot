#Requires -Version 7.2
# GPL-2.0-or-later. Final independent ISP check and EEPROM-only restoration.
# Default mode reads and plans. Only -Run permits an EEPROM write.
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$IspBackupDirectory,
    [Parameter(Mandatory)][string]$UsbResultDirectory,
    [string]$AvrdudePath = 'avrdude',
    [string]$AvrdudeConfig = '',
    [string]$OutputDirectory = '',
    [switch]$Run
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$sourceDir = $PSScriptRoot
$repoRoot = [IO.Path]::GetFullPath((Join-Path $sourceDir '../../..'))
$expectedBootHash = 'ff0b46f3276f4a8c75a0b765d263eac5ae93f5fe6bd1dddafa572ca49aff959d'
$IspBackupDirectory = [IO.Path]::GetFullPath($IspBackupDirectory)
$UsbResultDirectory = [IO.Path]::GetFullPath($UsbResultDirectory)
if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $OutputDirectory = Join-Path $repoRoot ('.worktree/nano-mini512-final-isp-' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfff'))
}
$taskDir = [IO.Path]::GetFullPath($OutputDirectory)
$rootPrefix = $repoRoot.TrimEnd('\','/') + [IO.Path]::DirectorySeparatorChar
$privatePrefix = [IO.Path]::GetFullPath((Join-Path $repoRoot '.worktree')).TrimEnd('\','/') + [IO.Path]::DirectorySeparatorChar
if ($taskDir.StartsWith($rootPrefix,[StringComparison]::OrdinalIgnoreCase) -and
    -not $taskDir.StartsWith($privatePrefix,[StringComparison]::OrdinalIgnoreCase)) {
    throw 'Board readouts inside this checkout must be under the ignored .worktree directory.'
}
if (Test-Path -LiteralPath $taskDir) { throw 'OutputDirectory must be new; existing evidence is never overwritten.' }
New-Item -ItemType Directory -Path $taskDir | Out-Null
$avrExe = (Get-Command $AvrdudePath -CommandType Application -ErrorAction Stop).Source
if ([string]::IsNullOrWhiteSpace($AvrdudeConfig)) {
    $candidate = [IO.Path]::GetFullPath((Join-Path (Split-Path $avrExe -Parent) '../etc/avrdude.conf'))
    if (Test-Path -LiteralPath $candidate) { $AvrdudeConfig = $candidate }
}
$baseArgs = @('-c','usbasp','-p','m328pb','-B','20','-q')
if (-not [string]::IsNullOrWhiteSpace($AvrdudeConfig)) {
    $baseArgs = @('-C',[IO.Path]::GetFullPath($AvrdudeConfig)) + $baseArgs
}
Set-Location -LiteralPath $taskDir
if (-not ('AvrProcessRunner' -as [type])) { Add-Type -LiteralPath (Join-Path $sourceDir 'AvrProcessRunner.cs') }

function Assert-SameBytes([byte[]]$Actual,[byte[]]$Expected,[string]$Name) {
    if ($Actual.Length-ne $Expected.Length) { throw ($Name+': size mismatch.') }
    for ($index=0;$index-lt $Expected.Length;$index++) {
        if ($Actual[$index]-ne $Expected[$index]) { throw ($Name+': content mismatch.') }
    }
}
function Assert-MiniIdentity([byte[]]$Flash,$Values) {
    foreach ($entry in @(@('signature','1E9516'),@('lfuse','FF'),@('hfuse','DE'),@('efuse','FD'),@('lock','CF'))) {
        if ($Values[$entry[0]]-ne $entry[1]) { throw ('Connected device configuration differs: '+$entry[0]+'.') }
    }
    if ($Flash.Length-ne 32768) { throw 'Incomplete ISP Flash readout.' }
    $boot=[byte[]]::new(512); [Array]::Copy($Flash,0x7E00,$boot,0,512)
    if ([Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($boot)).ToLowerInvariant()-ne $expectedBootHash) {
        throw 'Connected Boot image is not the pinned Mini experiment; refusing writes.'
    }
}
function Get-EepromDifferenceCounts([byte[]]$Original,[byte[]]$Current) {
    if ($Original.Length-ne 1024-or $Current.Length-ne 1024) { throw 'Complete 1024-byte EEPROM readouts are required.' }
    $total=0; $outside=0
    for ($index=0;$index-lt 1024;$index++) {
        if ($Original[$index]-ne $Current[$index]) {
            $total++
            if ($index-lt 1014) { $outside++ }
        }
    }
    return [pscustomobject]@{total=$total;outside_probe_range=$outside}
}
function Get-UsbQualificationFailures($Usb,[int]$UnexpectedEepromChanges) {
    $failures=[Collections.Generic.List[string]]::new()
    if ($null-ne $Usb.failure) { $failures.Add('USB_TEST_FAILURE') }
    if (-not $Usb.application_restored_and_verified) { $failures.Add('USB_APPLICATION_RESTORATION_NOT_REPORTED') }
    if (-not $Usb.runtime_configuration_verified) { $failures.Add('USB_RUNTIME_CONFIGURATION_NOT_VERIFIED') }
    if ($Usb.watchdog_cycles-ne 50-or $Usb.dtr_cycles-ne 20) { $failures.Add('USB_RESET_STRESS_INCOMPLETE') }
    if (@($Usb.checks).Count-eq 0-or @($Usb.checks | Where-Object {$_.result-ne 'PASS'}).Count-gt 0) {
        $failures.Add('USB_CHECK_RESULTS_INCOMPLETE')
    }
    if ($Usb.cold_start_requested-and -not $Usb.cold_start_passed) { $failures.Add('USB_COLD_START_FAILED') }
    if ($UnexpectedEepromChanges-gt 0) { $failures.Add('UNEXPECTED_EEPROM_CHANGES') }
    return ,$failures.ToArray()
}
function Invoke-Isp([string]$Label,[string[]]$Arguments) {
    [Console]::WriteLine('ISP stage: '+$Label)
    $code=[AvrProcessRunner]::Run($avrExe,$taskDir,[string[]]($baseArgs+$Arguments))
    if ($code-ne 0) { throw ('ISP operation failed: '+$Label+'.') }
}
function Read-IspState([string]$Prefix) {
    $arguments=@('-n','-D','-A')
    foreach ($memory in @('flash','eeprom','signature','lfuse','hfuse','efuse','lock')) {
        $arguments+=@('-U',($memory+':r:'+$Prefix+'-'+$memory+'.bin:r'))
    }
    Invoke-Isp ($Prefix+'-readback') $arguments
}
function Read-StateIdentity([string]$Prefix) {
    $values=@{}
    foreach ($memory in @('signature','lfuse','hfuse','efuse','lock')) {
        $values[$memory]=[Convert]::ToHexString([IO.File]::ReadAllBytes((Join-Path $taskDir ($Prefix+'-'+$memory+'.bin'))))
    }
    return $values
}

$isp=Get-Content -LiteralPath (Join-Path $IspBackupDirectory 'isp-result.json') -Raw | ConvertFrom-Json
$usb=Get-Content -LiteralPath (Join-Path $UsbResultDirectory 'usb-test-result.json') -Raw | ConvertFrom-Json
if ($isp.isp_programming-ne 'PASS'-or $isp.complete_flash_readback-ne 'PASS'-or $isp.eeprom_readback-ne 'PASS'-or
    $isp.edition-ne 'mini-experimental-512'-or $isp.boot_bytes-ne 512-or $isp.boot_start-ne '0x7E00'-or
    $isp.boot_sha256-ne $expectedBootHash) {
    throw 'A verified installation of the pinned Mini experiment is required.'
}
if ($usb.edition-ne 'mini-experimental-512'-or $usb.mcu-ne 'ATmega328PB'-or $usb.signature-ne '1E9516'-or
    $usb.boot_sha256-ne $expectedBootHash-or $usb.boot_bytes-ne 512-or $usb.boot_start-ne '0x7E00'-or
    $usb.application_bytes-ne 32256) {
    throw 'The USB result belongs to a different firmware profile.'
}
$baselineFlash=[IO.File]::ReadAllBytes((Join-Path $IspBackupDirectory 'after-flash.bin'))
$originalEeprom=[IO.File]::ReadAllBytes((Join-Path $IspBackupDirectory 'before-eeprom.bin'))
$ispValues=@{}
foreach ($memory in @('signature','lfuse','hfuse','efuse','lock')) {
    $ispValues[$memory]=[Convert]::ToHexString([IO.File]::ReadAllBytes((Join-Path $IspBackupDirectory ('after-'+$memory+'.bin'))))
}
Assert-MiniIdentity $baselineFlash $ispValues
if ($originalEeprom.Length-ne 1024) { throw 'Original EEPROM backup is incomplete.' }
Assert-SameBytes ([IO.File]::ReadAllBytes((Join-Path $IspBackupDirectory 'after-eeprom.bin'))) $originalEeprom 'ISP EEPROM preservation evidence'
Assert-SameBytes ([IO.File]::ReadAllBytes((Join-Path $UsbResultDirectory 'before-flash.bin'))) $baselineFlash 'USB/ISP Flash evidence binding'
Assert-SameBytes ([IO.File]::ReadAllBytes((Join-Path $UsbResultDirectory 'before-eeprom.bin'))) $originalEeprom 'USB/ISP EEPROM evidence binding'
Copy-Item -LiteralPath (Join-Path $IspBackupDirectory 'before-eeprom.bin') -Destination 'original-eeprom.bin'
Copy-Item -LiteralPath (Join-Path $IspBackupDirectory 'isp-result.json') -Destination 'verified-installation-result.json'
Copy-Item -LiteralPath (Join-Path $UsbResultDirectory 'usb-test-result.json') -Destination 'usb-result-before-isp.json'
$result=[ordered]@{edition='mini-experimental-512';mcu='ATmega328PB';boot_bytes=512;boot_start='0x7E00';
    boot_sha256=$expectedBootHash;mode=$(if($Run){'restore_and_verify'}else{'read_only_plan'});
    signature='1E9516';lfuse='FF';hfuse='DE';efuse='FD';lock='CF';
    pre_restore_identity_verified=$false;pre_restore_boot_hash_verified=$false;pre_restore_full_flash_matches_isp=$false;
    eeprom_write_performed=$false;eeprom_changed_bytes=$null;unexpected_eeprom_changes_outside_1014_1023=$null;
    original_application_restored=$false;original_eeprom_restored=$false;boot_unchanged_since_install=$false;
    configuration_unchanged=$false;complete_flash_readback=$false;complete_device_restoration_verified=$false;
    final_isp_required=$true;usb_checks_passed=((Get-UsbQualificationFailures $usb 0).Count-eq 0);
    usb_failure_preserved=($null-ne $usb.failure);
    cold_start_requested=[bool]$usb.cold_start_requested;cold_start_passed=[bool]$usb.cold_start_passed;
    qualification_failures=@();hardware_qualification_passed=$false;failure=$null}
try {
    Read-IspState 'post-usb'
    $currentFlash=[IO.File]::ReadAllBytes((Join-Path $taskDir 'post-usb-flash.bin'))
    Assert-MiniIdentity $currentFlash (Read-StateIdentity 'post-usb')
    $result.pre_restore_identity_verified=$true
    $result.pre_restore_boot_hash_verified=$true
    try { Assert-SameBytes $currentFlash $baselineFlash 'Post-USB complete Flash' }
    catch {
        throw 'Flash differs from the verified post-installation snapshot. No EEPROM write was attempted. Retain all backups; recover and verify application Flash through ISP before retrying in a new output directory.'
    }
    $result.pre_restore_full_flash_matches_isp=$true
    $counts=Get-EepromDifferenceCounts $originalEeprom ([IO.File]::ReadAllBytes((Join-Path $taskDir 'post-usb-eeprom.bin')))
    $result.eeprom_changed_bytes=$counts.total
    $result.unexpected_eeprom_changes_outside_1014_1023=$counts.outside_probe_range
    $result.qualification_failures=Get-UsbQualificationFailures $usb $counts.outside_probe_range
    if ($Run) {
        # No Chip Erase, Flash, fuse or lock write is permitted by this finisher.
        $result.eeprom_write_performed=$true
        Invoke-Isp 'restore-original-eeprom' @('-D','-A','-U','eeprom:w:original-eeprom.bin:r')
        Read-IspState 'final'
        $finalFlash=[IO.File]::ReadAllBytes((Join-Path $taskDir 'final-flash.bin'))
        Assert-MiniIdentity $finalFlash (Read-StateIdentity 'final')
        Assert-SameBytes $finalFlash $baselineFlash 'Final complete Flash'
        Assert-SameBytes ([IO.File]::ReadAllBytes((Join-Path $taskDir 'final-eeprom.bin'))) $originalEeprom 'Final original EEPROM'
        $result.original_application_restored=$true
        $result.original_eeprom_restored=$true
        $result.boot_unchanged_since_install=$true
        $result.configuration_unchanged=$true
        $result.complete_flash_readback=$true
        $result.complete_device_restoration_verified=$true
        $result.final_isp_required=$false
        $result.hardware_qualification_passed=(@($result.qualification_failures).Count-eq 0)
    }
} catch {
    $result.failure=$_.Exception.Message
    throw
} finally {
    $result | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath 'final-isp-result.json' -Encoding utf8
    $result | ConvertTo-Json -Depth 6 | Write-Output
}
if (-not $Run) {
    [Console]::WriteLine('READ-ONLY PLAN COMPLETE. Use -Run with a new private output directory to restore EEPROM and perform final verification.')
} elseif (-not $result.hardware_qualification_passed) {
    throw 'User data restoration passed, but qualification retains a USB failure or unexpected EEPROM change. Inspect the private results.'
} else {
    [Console]::WriteLine('PASS: original application/EEPROM and complete Flash/configuration verified; Mini Boot unchanged; requested USB qualification passed.')
}
