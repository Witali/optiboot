#Requires -Version 7.2
# GPL-2.0-or-later. Hardware validation for the pinned ATmega328PB Mini image.
# Requires PowerShell 7.2+. The default mode builds probes and reads backups only.
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Port,
    [string]$AvrdudePath = 'avrdude',
    [string]$AvrdudeConfig = '',
    [string]$OutputDirectory = '',
    [ValidateSet('basic','middle','full')][string]$Edition = 'basic',
    [string]$IspBackupDirectory = '',
    [switch]$UseWslToolchain,
    [string]$RestoreFromDirectory = '',
    [switch]$ColdStart,
    [switch]$ColdStartOnly,
    [switch]$DiagnosticsOnly,
    [switch]$Run
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$sourceDir = $PSScriptRoot
$repoRoot = [IO.Path]::GetFullPath((Join-Path $sourceDir '../../..'))
$Baud = 115200
function Get-NanoEditionSettings([ValidateSet('basic','middle','full')][string]$Name) {
    $bootBytes = if ($Name -eq 'full') {1024} else {512}
    $bootStart = 32768 - $bootBytes
    $hash = switch ($Name) {
        basic {'149ebc0347815b42daaa20defce83342462306e9ddd3f15c63eeb59baafd70d1'}
        middle {'156d3701c01e5a9f5008b371c08e4753b7d7200e1535b1c776755040723a99c1'}
        full {'6a16bbe0776d704e4c9ab7651961bd35b02efe68809a7492090232014d5d82ef'}
    }
    $source = switch ($Name) {
        basic {'ccfc7f9470d9823b945092fb2e2905c193c75ec8'}
        middle {'30651a823368ee0d4e692d6450530bbd8c70c39c'}
        full {'89628571b118638c653533469f54830aa8cf1d61'}
    }
    return [pscustomobject]@{Edition=$Name;BootBytes=$bootBytes;BootStart=$bootStart;
        ApplicationBytes=$bootStart;ScratchAddress=($bootStart-128);
        HighFuse=$(if($Name-eq 'full'){'DC'}else{'DE'});BootHash=$hash;SourceCommit=$source;
        RequiresIsp=($Name-ne 'basic');HasAppSpm=($Name-ne 'basic');
        PreservesResetFlags=($Name-ne 'basic');HasFuseReads=($Name-ne 'middle')}
}
$editionSettings = Get-NanoEditionSettings $Edition
$middle = $Edition -eq 'middle'
$fullEdition = $Edition -eq 'full'
$expectedBootHash = $editionSettings.BootHash
$firmwareSourceCommit = $editionSettings.SourceCommit
$bootBytes = $editionSettings.BootBytes
$bootStart = $editionSettings.BootStart
$applicationBytes = $editionSettings.ApplicationBytes
$scratchAddress = $editionSettings.ScratchAddress
$expectedHighFuse = $editionSettings.HighFuse
$restoreOnly = -not [string]::IsNullOrWhiteSpace($RestoreFromDirectory)
if ($DiagnosticsOnly -and ($restoreOnly -or $ColdStart -or $ColdStartOnly -or $Edition-eq 'basic')) {
    throw '-DiagnosticsOnly requires Middle or Full and cannot be combined with cold-start or restoration modes.'
}
if ($ColdStartOnly -and $restoreOnly) { throw '-ColdStartOnly cannot be combined with -RestoreFromDirectory.' }
if ($ColdStartOnly) { $ColdStart = $true }
if ($restoreOnly) { $taskDir = [IO.Path]::GetFullPath($RestoreFromDirectory) }
else {
    if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
        $OutputDirectory = Join-Path $repoRoot ('.worktree/nano-usb-test-' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfff'))
    }
    $taskDir = [IO.Path]::GetFullPath($OutputDirectory)
    $rootPrefix = $repoRoot.TrimEnd('\','/') + [IO.Path]::DirectorySeparatorChar
    $privatePrefix = [IO.Path]::GetFullPath((Join-Path $repoRoot '.worktree')).TrimEnd('\','/') + [IO.Path]::DirectorySeparatorChar
    if ($taskDir.StartsWith($rootPrefix,[StringComparison]::OrdinalIgnoreCase) -and
        -not $taskDir.StartsWith($privatePrefix,[StringComparison]::OrdinalIgnoreCase)) {
        throw 'Device backups inside this checkout must be under the ignored .worktree directory.'
    }
    if (Test-Path -LiteralPath $taskDir) { throw 'OutputDirectory must not exist; existing backups are never overwritten.' }
    New-Item -ItemType Directory -Path $taskDir -Force | Out-Null
}
$avrExe = (Get-Command $AvrdudePath -CommandType Application -ErrorAction Stop).Source
if ([string]::IsNullOrWhiteSpace($AvrdudeConfig)) {
    $candidate = [IO.Path]::GetFullPath((Join-Path (Split-Path $avrExe -Parent) '../etc/avrdude.conf'))
    if (Test-Path -LiteralPath $candidate) { $AvrdudeConfig = $candidate }
}
$baseArgs = @('-p','m328pb','-c','arduino','-P',$Port,'-b',$Baud.ToString())
if (-not [string]::IsNullOrWhiteSpace($AvrdudeConfig)) {
    $baseArgs = @('-C',[IO.Path]::GetFullPath($AvrdudeConfig)) + $baseArgs
}
Set-Location -LiteralPath $taskDir
if (-not ('AvrProcessRunner' -as [type])) { Add-Type -LiteralPath (Join-Path $sourceDir 'AvrProcessRunner.cs') }
$script:checks = [Collections.Generic.List[object]]::new()
$script:serialPort = $null
$script:lastCaptureMetrics = $null

function Add-Check([string]$Name) {
    $script:checks.Add([ordered]@{name=$Name; result='PASS'})
    [Console]::WriteLine('PASS ' + $Name)
}
function Assert-Bytes([byte[]]$Actual, [byte[]]$Expected, [string]$Name) {
    if ($Actual.Length -ne $Expected.Length) { throw "$Name length mismatch." }
    for ($index=0; $index -lt $Expected.Length; $index++) {
        if ($Actual[$index] -ne $Expected[$index]) { throw "$Name data mismatch." }
    }
}
function Assert-Files([string]$Actual, [string]$Expected) {
    if ((Get-FileHash -LiteralPath $Actual).Hash -ne (Get-FileHash -LiteralPath $Expected).Hash) {
        throw "File comparison failed for $Actual."
    }
}
function Invoke-Avr([string[]]$NativeArgs) {
    $code = [AvrProcessRunner]::Run($avrExe, $taskDir, [string[]]($baseArgs + $NativeArgs))
    if ($code -ne 0) { throw "AVRDUDE exited with code $code." }
}
function Identity-VerifyArgs {
    $arguments = @('-U','signature:v:before-signature.bin:r')
    if (-not $middle) {
        foreach ($memory in @('lfuse','hfuse','efuse','lock')) {
            $arguments += @('-U',($memory+':v:before-'+$memory+'.bin:r'))
        }
    }
    return $arguments
}
function Assert-IspEvidence {
    if ([string]::IsNullOrWhiteSpace($IspBackupDirectory)) {
        if ($restoreOnly -and (Test-Path -LiteralPath 'isp-backup-directory.txt')) {
            $script:IspBackupDirectory = [IO.File]::ReadAllText((Join-Path $taskDir 'isp-backup-directory.txt')).Trim()
        } else { throw 'This edition requires -IspBackupDirectory with verified post-installation ISP readouts.' }
    }
    $script:IspBackupDirectory = [IO.Path]::GetFullPath($IspBackupDirectory)
    $result = Get-Content -LiteralPath (Join-Path $IspBackupDirectory 'isp-result.json') -Raw | ConvertFrom-Json
    if ($result.isp_programming -ne 'PASS' -or $result.complete_flash_readback -ne 'PASS' -or
        $result.eeprom_readback -ne 'PASS' -or $result.boot_sha256 -ne $expectedBootHash) {
        throw 'This edition requires a verified ISP installation of the pinned image.'
    }
    foreach ($entry in @(@('signature','1E9516'),@('lfuse','FF'),@('hfuse',$expectedHighFuse),@('efuse','FD'),@('lock','CF'))) {
        $value = [Convert]::ToHexString([IO.File]::ReadAllBytes((Join-Path $IspBackupDirectory ('after-'+$entry[0]+'.bin'))))
        if ($value -ne $entry[1]) { throw ('Unexpected ISP '+$entry[0]+'.') }
    }
    $ispFlash = [IO.File]::ReadAllBytes((Join-Path $IspBackupDirectory 'after-flash.bin'))
    $ispEeprom = [IO.File]::ReadAllBytes((Join-Path $IspBackupDirectory 'after-eeprom.bin'))
    if ($ispFlash.Length -ne 32768 -or $ispEeprom.Length -ne 1024) { throw 'Unexpected ISP memory snapshot size.' }
    $ispBoot = [byte[]]::new($bootBytes); [Array]::Copy($ispFlash,$bootStart,$ispBoot,0,$bootBytes)
    if ([Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($ispBoot)).ToLowerInvariant() -ne $expectedBootHash) {
        throw 'ISP Flash snapshot does not contain the pinned edition bootloader.'
    }
    if (-not $restoreOnly) {
        [IO.File]::WriteAllText((Join-Path $taskDir 'isp-backup-directory.txt'),$IspBackupDirectory)
        Copy-Item -LiteralPath (Join-Path $IspBackupDirectory 'isp-result.json') -Destination 'verified-isp-result.json'
        foreach ($memory in @('lfuse','hfuse','efuse','lock')) {
            Copy-Item -LiteralPath (Join-Path $IspBackupDirectory ('after-'+$memory+'.bin')) -Destination ('before-'+$memory+'.bin')
        }
    }
}
function Open-Serial {
    $script:serialPort = [IO.Ports.SerialPort]::new($Port,$Baud,[IO.Ports.Parity]::None,8,[IO.Ports.StopBits]::One)
    $script:serialPort.DtrEnable = $false
    $script:serialPort.RtsEnable = $false
    $script:serialPort.ReadTimeout = 1500
    $script:serialPort.WriteTimeout = 1500
    $script:serialPort.Open()
    $script:serialPort.DiscardInBuffer()
}
function Close-Serial {
    if ($null -ne $script:serialPort) { $script:serialPort.Dispose(); $script:serialPort=$null }
}
function Read-Raw([int]$Count) {
    $bytes = [byte[]]::new($Count)
    $offset = 0
    while ($offset -lt $Count) {
        $read = $script:serialPort.Read($bytes,$offset,$Count-$offset)
        if ($read -le 0) { throw 'Serial port closed before the reply completed.' }
        $offset += $read
    }
    return ,$bytes
}
function Send-Expect([byte[]]$Packet, [byte[]]$Expected, [string]$Name) {
    $script:serialPort.Write($Packet,0,$Packet.Length)
    $reply = Read-Raw $Expected.Length
    Assert-Bytes $reply $Expected $Name
}
function Enter-Boot {
    $script:serialPort.DtrEnable=$false
    $script:serialPort.RtsEnable=$false
    Start-Sleep -Milliseconds 250
    $script:serialPort.DtrEnable=$true
    $script:serialPort.DtrEnable=$false
    Start-Sleep -Milliseconds 100
    $script:serialPort.DiscardInBuffer()
    Send-Expect ([byte[]]@(0x30,0x20)) ([byte[]]@(0x14,0x10)) 'GET_SYNC after external reset'
}
function Load-Address([int]$ByteAddress) {
    if (($ByteAddress -band 1) -ne 0) { throw 'Word addressing requires an even start address.' }
    Send-Expect ([byte[]]@(0x55,(($ByteAddress -shr 1)-band 0xFF),(($ByteAddress -shr 9)-band 0xFF),0x20)) ([byte[]]@(0x14,0x10)) 'LOAD_ADDRESS'
}
function Read-Memory([int]$Address,[int]$Count,[byte]$Type,[byte[]]$Expected,[switch]$LegacyZero) {
    Load-Address $Address
    $high=($Count-shr 8)-band 0xFF; $low=$Count-band 0xFF
    if ($LegacyZero) { $high=0; $low=0 }
    Send-Expect ([byte[]]@(0x74,$high,$low,$Type,0x20)) ([byte[]](@(0x14)+$Expected+@(0x10))) 'READ_PAGE'
}
function Write-Memory([int]$Address,[byte]$Type,[byte[]]$Payload) {
    Load-Address $Address
    $packet=[byte[]](@(0x64,(($Payload.Length-shr 8)-band 0xFF),($Payload.Length-band 0xFF),$Type)+$Payload+@(0x20))
    Send-Expect $packet ([byte[]]@(0x14,0x10)) 'PROG_PAGE'
}
function Read-AvailableText($Connection,$ReadCalls = $null) {
    # ReadCalls is an optional PowerShell [ref] counter; only returned bytes decode.
    $available = [int]$Connection.BytesToRead
    if ($available-le 0) { return [string]::Empty }
    $requested = [Math]::Min($available,4096)
    $buffer = [byte[]]::new($requested)
    if ($null-ne $ReadCalls) { $ReadCalls.Value = [int]$ReadCalls.Value + 1 }
    $actual = [int]$Connection.Read($buffer,0,$requested)
    if ($actual-lt 0 -or $actual-gt $requested) { throw 'Serial reader returned an invalid byte count.' }
    return [Text.Encoding]::ASCII.GetString($buffer,0,$actual)
}
function Drain-StartupInput($Connection,[ValidateRange(1,1000)][int]$Milliseconds = 250) {
    $timer=[Diagnostics.Stopwatch]::StartNew()
    $readCalls=0
    $discardedBytes=0
    while($timer.ElapsedMilliseconds-lt $Milliseconds) {
        $chunk=Read-AvailableText $Connection ([ref]$readCalls)
        $discardedBytes+=$chunk.Length
        Start-Sleep -Milliseconds 20
    }
    return [ordered]@{requested_ms=$Milliseconds;elapsed_ms=$timer.Elapsed.TotalMilliseconds;
        discarded_bytes=$discardedBytes;read_calls=$readCalls;maximum_read_bytes=4096}
}
function Capture-Output([int]$Milliseconds,[string]$EvidenceName = '') {
    if($EvidenceName-in @('runtime-diagnostics','final-runtime-diagnostics')) {
        # Explicit startup-only exclusion; validation sees every measured byte.
        $startup=Drain-StartupInput $script:serialPort 250
        $startup | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $taskDir ($EvidenceName+'.startup.json')) -Encoding utf8
    }
    $text=[Text.StringBuilder]::new()
    $timer=[Diagnostics.Stopwatch]::StartNew()
    $readCalls=0
    try {
        while ($timer.ElapsedMilliseconds -lt $Milliseconds) {
            [void]$text.Append((Read-AvailableText $script:serialPort ([ref]$readCalls)))
            Start-Sleep -Milliseconds 20
        }
    } finally {
        $script:lastCaptureMetrics=[ordered]@{requested_ms=$Milliseconds;elapsed_ms=$timer.Elapsed.TotalMilliseconds;
            bytes_read=$text.Length;read_calls=$readCalls;maximum_read_bytes=4096;encoding='ASCII';
            observed_bytes_per_second=($text.Length*1000.0/[Math]::Max(1.0,$timer.Elapsed.TotalMilliseconds))}
        if(-not [string]::IsNullOrWhiteSpace($EvidenceName)) {
            $script:lastCaptureMetrics | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $taskDir ($EvidenceName+'.capture.json')) -Encoding utf8
        }
    }
    return $text.ToString()
}
function Assert-AppStarted([string]$Text,[string]$Name) {
    if (-not $Text.Contains('BOOT_ACCESS_DIAGNOSTICS_V1') -or $Text.Contains([char]0x10)) {
        throw "$Name did not reject the packet and restart the diagnostic application as expected."
    }
}
function Reject-And-Restart([byte[]]$Packet,[string]$Name,[int]$WaitMs=900) {
    $script:serialPort.Write($Packet,0,$Packet.Length)
    $capture=Capture-Output $WaitMs
    Assert-AppStarted $capture $Name
    Add-Check $Name
    Enter-Boot
}
function Crc16([byte[]]$Data) {
    $crc=0xFFFF
    foreach ($value in $Data) {
        $crc=$crc-bxor([int]$value-shl 8)
        for($bit=0;$bit-lt 8;$bit++) {
            if(($crc-band 0x8000)-ne 0){$crc=(($crc-shl 1)-bxor 0x1021)-band 0xFFFF}
            else{$crc=($crc-shl 1)-band 0xFFFF}
        }
    }
    return $crc.ToString('X4')
}
function Probe-Ready([int]$TimeoutMs=1500,[switch]$AfterArmed) {
    $text=[Text.StringBuilder]::new();$timer=[Diagnostics.Stopwatch]::StartNew()
    $readCalls=0
    while($timer.ElapsedMilliseconds-lt $TimeoutMs){
        [void]$text.Append((Read-AvailableText $script:serialPort ([ref]$readCalls)))
        $received=$text.ToString()
        if($AfterArmed){
            $armed=$received.IndexOf('WDT_ARMED')
            if($armed-lt 0){Start-Sleep -Milliseconds 5;continue}
            $received=$received.Substring($armed)
        }
        $match=[regex]::Match($received,'APP_READY reason=([0-9A-F]{2}) r1=([0-9A-F]{2}) mcusr=([0-9A-F]{2}) wdt=([0-9A-F]{2}) entry=([0-9A-F]{16}) ticks=([0-9A-F]{4})')
        if($match.Success){
            return [pscustomobject]@{reason=[Convert]::ToInt32($match.Groups[1].Value,16);
                r1=[Convert]::ToInt32($match.Groups[2].Value,16);mcusr=[Convert]::ToInt32($match.Groups[3].Value,16);
                wdt=[Convert]::ToInt32($match.Groups[4].Value,16);entry=[Convert]::FromHexString($match.Groups[5].Value);
                ticks=[Convert]::ToInt32($match.Groups[6].Value,16);elapsed_ms=$timer.ElapsedMilliseconds;
                bytes_read=$text.Length;read_calls=$readCalls}
        }
        Start-Sleep -Milliseconds 5
    }
    throw 'The watchdog probe did not report a complete application startup.'
}
function Assert-Probe($Ready,[int]$ReasonMask) {
    $expectedMcusr = if ($editionSettings.PreservesResetFlags) { $Ready.reason -band $(if ($Ready.reason-band 2) {0xF7} else {0xFF}) } else {0}
    if(($Ready.reason-band $ReasonMask)-eq 0-or $Ready.r1-ne 0-or $Ready.mcusr-ne $expectedMcusr-or ($Ready.wdt-band 0x48)-ne 0){
        throw ('Unexpected boot state: reason={0:X2}, r1={1:X2}, MCUSR={2:X2}, WDTCSR={3:X2}.' -f $Ready.reason,$Ready.r1,$Ready.mcusr,$Ready.wdt)
    }
}
function Get-ColdStartProof([byte[]]$Record,[int]$Ticks,[ValidateSet('basic','middle','full')][string]$EvidenceEdition) {
    if ($Record.Length -ne 8 -or [Text.Encoding]::ASCII.GetString($Record,0,4) -ne 'STAR') {
        throw 'Missing autonomous-start evidence tag.'
    }
    $cause = [int]$Record[4]
    $expectedMcusr = if ($EvidenceEdition -ne 'basic') { $cause -band $(if ($cause-band 2) {0xF7} else {0xFF}) } else {0}
    if ($Ticks-lt 0 -or $Ticks-gt 65535 -or ($cause-band 0x0F)-eq 0 -or
        $Record[5]-ne 0 -or $Record[6]-ne $expectedMcusr -or ($Record[7]-band 0x48)-ne 0) {
        throw 'Autonomous-start evidence has an invalid handoff state.'
    }
    if ($Ticks-ge 3) { return 'autonomous_uptime_at_least_1500ms' }
    if ($EvidenceEdition-ne 'basic' -and $Ticks-ge 1 -and
        ($cause-band 0x01)-ne 0 -and ($cause-band 0x0A)-eq 0) {
        return 'power_on_entry_and_at_least_500ms_execution'
    }
    throw 'Application execution before the host connection was not confirmed.'
}
function Assert-DiagnosticFrames([string]$Capture) {
    if($Capture.Contains([char]0)){throw 'Runtime diagnostic capture contains NUL bytes.'}
    $frames=[regex]::Matches($Capture,'BOOT_ACCESS_DIAGNOSTICS_V1\r?\n(.*?)END_BOOT_ACCESS_DIAGNOSTICS',[Text.RegularExpressions.RegexOptions]::Singleline)
    if($frames.Count-lt 3){throw 'Fewer than three runtime diagnostic frames received.'}
    $zeroCrc=Crc16 ([byte[]]::new($bootBytes))
    foreach($frame in $frames){
        if($frame.Groups[1].Value.Contains('BOOT_ACCESS_DIAGNOSTICS_V1')){throw 'Runtime diagnostic capture contains nested frames.'}
        $fields=@{}; foreach($line in ($frame.Groups[1].Value -split '\r?\n')){if($line.Contains('=')){
            $pair=$line.Split('=',2)
            if($fields.ContainsKey($pair[0])){throw 'Runtime diagnostic frame contains a duplicate field.'}
            $fields[$pair[0]]=$pair[1]
        }}
        foreach($entry in @(@('signature','1E9516'),@('lfuse','FF'),@('hfuse',$expectedHighFuse),@('efuse','FD'),@('lock_raw','CF'),
            @('lock_implemented','0F'),@('repeated_reads','STABLE'),@('boot_size_hex',$bootBytes.ToString('X4')),@('boot_start_hex',$bootStart.ToString('X4')),
            @('reset_target','BOOT'),@('app_lpm_boot','BLOCKED_BY_LOCK_BITS'),@('boot_spm_boot','BLOCKED_BY_LOCK_BITS'),
            @('boot_lpm_app','ALLOWED_BY_LOCK_BITS'),@('boot_spm_app','ALLOWED_BY_LOCK_BITS'),@('app_read_boot_crc16',$zeroCrc))){
            if($fields[$entry[0]]-ne $entry[1]){throw ('Runtime diagnostic mismatch: '+$entry[0])}
        }
    }
}
function Wait-PortState([bool]$Present) {
    $timer=[Diagnostics.Stopwatch]::StartNew()
    while($timer.ElapsedMilliseconds-lt 120000){
        if(Test-Path -LiteralPath 'cancel-cold-start.txt'){throw 'Cold-start test cancelled; restoring the original application.'}
        $found=@([IO.Ports.SerialPort]::GetPortNames())-contains $Port
        if($found-eq $Present){return}
        Start-Sleep -Milliseconds 100
    }
    throw 'Timed out waiting for the Nano USB port to disappear or return.'
}

function Tool-Path([string]$Path) {
    $full = [IO.Path]::GetFullPath($Path)
    if (-not $UseWslToolchain) { return $full }
    $converted = & wsl.exe --exec wslpath -a -u $full
    if ($LASTEXITCODE -ne 0 -or @($converted).Count -ne 1) { throw 'WSL path conversion failed.' }
    return [string]$converted
}
function Invoke-BuildTool([string]$Name,[string[]]$ToolArgs) {
    if ($UseWslToolchain) { & wsl.exe --exec $Name @ToolArgs }
    else { & $Name @ToolArgs }
    if ($LASTEXITCODE -ne 0) { throw "$Name failed." }
}
if ($editionSettings.RequiresIsp) { Assert-IspEvidence }
if (-not $restoreOnly) {
    $probeNames = if($DiagnosticsOnly){@('diagnostics')}else{@('diagnostics','watchdog_probe')}
    foreach ($probe in $probeNames) {
        $source = Tool-Path (Join-Path $sourceDir ($probe+'.c'))
        $elf = Tool-Path (Join-Path $taskDir ($probe+'.elf'))
        $bin = Tool-Path (Join-Path $taskDir ($probe+'.bin'))
        Invoke-BuildTool 'avr-gcc' @('-mmcu=atmega328p','-DF_CPU=16000000UL','-DDIAGNOSTICS_STANDALONE',
            '-Os','-std=gnu11','-ffunction-sections','-fdata-sections',$source,'-Wl,--gc-sections','-o',$elf)
        Invoke-BuildTool 'avr-objcopy' @('-O','binary','-R','.eeprom',$elf,$bin)
        Invoke-BuildTool 'avr-objdump' @('-d',$elf) | Set-Content -LiteralPath ($probe+'.disassembly.txt') -Encoding utf8
        if ([regex]::IsMatch([IO.File]::ReadAllText((Join-Path $taskDir ($probe+'.disassembly.txt'))),'(?m)^\s*[0-9a-f]+:.*\bspm\b')) {
            throw 'A diagnostic probe contains an SPM instruction.'
        }
    }
    if ($editionSettings.HasAppSpm -and -not $ColdStartOnly -and -not $DiagnosticsOnly) {
        $source = Tool-Path (Join-Path $sourceDir 'app_spm_probe.c')
        $include = Tool-Path (Join-Path $repoRoot 'optiboot/bootloaders/optiboot')
        $elf = Tool-Path (Join-Path $taskDir 'app_spm_probe.elf')
        $bin = Tool-Path (Join-Path $taskDir 'app_spm_probe.bin')
        Invoke-BuildTool 'avr-gcc' @('-mmcu=atmega328p','-DF_CPU=16000000UL',('-DOPTIBOOT_MINI_BOOT_BYTES='+$bootBytes),'-I',$include,
            '-Os','-std=gnu11','-ffunction-sections','-fdata-sections',$source,'-Wl,--gc-sections','-o',$elf)
        Invoke-BuildTool 'avr-objcopy' @('-O','binary','-R','.eeprom',$elf,$bin)
        Invoke-BuildTool 'avr-objdump' @('-d',$elf) | Set-Content -LiteralPath 'app_spm_probe.disassembly.txt' -Encoding utf8
    }
    $readArgs = @('-n','-D','-A','-U','signature:r:before-signature.bin:r',
                  '-U','flash:r:before-flash.bin:r','-U','eeprom:r:before-eeprom.bin:r')
    if (-not $middle) {
        foreach ($memory in @('lfuse','hfuse','efuse','lock')) { $readArgs += @('-U',($memory+':r:before-'+$memory+'.bin:r')) }
    }
    Invoke-Avr $readArgs
    Invoke-Avr (@('-n','-D','-A','-U','flash:v:before-flash.bin:r','-U','eeprom:v:before-eeprom.bin:r') + (Identity-VerifyArgs))
    if ($editionSettings.RequiresIsp) {
        Assert-Files 'before-flash.bin' (Join-Path $IspBackupDirectory 'after-flash.bin')
        Assert-Files 'before-eeprom.bin' (Join-Path $IspBackupDirectory 'after-eeprom.bin')
        Assert-Files 'before-signature.bin' (Join-Path $IspBackupDirectory 'after-signature.bin')
    }
    Set-Content -LiteralPath 'backup-verified.txt' -Value 'Complete current-board backups independently verified before any write.' -Encoding utf8
}
if (-not (Test-Path -LiteralPath 'backup-verified.txt')) { throw 'Verified current-board backups are required.' }
$beforeFlash=[IO.File]::ReadAllBytes((Join-Path $taskDir 'before-flash.bin'))
$beforeEeprom=[IO.File]::ReadAllBytes((Join-Path $taskDir 'before-eeprom.bin'))
$diagnostic=[IO.File]::ReadAllBytes((Join-Path $taskDir 'diagnostics.bin'))
if($beforeFlash.Length-ne 32768-or $beforeEeprom.Length-ne 1024-or $diagnostic.Length-le 0-or $diagnostic.Length-gt $bootStart){throw 'Unexpected image size.'}
foreach($entry in @(@('signature','1E9516'),@('lfuse','FF'),@('hfuse',$expectedHighFuse),@('efuse','FD'),@('lock','CF'))){
    $value=[Convert]::ToHexString([IO.File]::ReadAllBytes((Join-Path $taskDir ('before-'+$entry[0]+'.bin'))))
    if($value-ne $entry[1]){throw ('Unexpected '+$entry[0]+'.')}
}
$boot=[byte[]]::new($bootBytes); [Array]::Copy($beforeFlash,$bootStart,$boot,0,$bootBytes)
$bootHash=[Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($boot)).ToLowerInvariant()
if($bootHash-ne $expectedBootHash){throw 'Installed bootloader differs from the pinned edition build.'}
if([regex]::IsMatch([IO.File]::ReadAllText((Join-Path $taskDir 'diagnostics.disassembly.txt')),'(?m)^\s*[0-9a-f]+:.*\bspm\b')){throw 'Diagnostic contains an SPM instruction.'}
$restoreApp=[byte[]]::new($applicationBytes); [Array]::Copy($beforeFlash,0,$restoreApp,0,$restoreApp.Length)
[IO.File]::WriteAllBytes((Join-Path $taskDir 'restore-application.bin'),$restoreApp)
$testApp=[byte[]]::new($applicationBytes)
for($i=0;$i-lt $testApp.Length;$i++){$testApp[$i]=(($i*73)-bxor($i-shr 8)-bxor 0xA5)-band 0xFF}
[Array]::Copy($diagnostic,0,$testApp,0,$diagnostic.Length)
[IO.File]::WriteAllBytes((Join-Path $taskDir 'test-application.bin'),$testApp)
$testFlash=[byte[]]$beforeFlash.Clone();[Array]::Copy($testApp,0,$testFlash,0,$testApp.Length)
[IO.File]::WriteAllBytes((Join-Path $taskDir 'test-full-flash.bin'),$testFlash)
$testEeprom=[byte[]]::new(1024)
for($i=0;$i-lt 1024;$i++){$testEeprom[$i]=(($i*37)-bxor($i-shr 8)-bxor 0x5A)-band 0xFF}
[IO.File]::WriteAllBytes((Join-Path $taskDir 'test-eeprom.bin'),$testEeprom)
[ordered]@{port=$Port;baud=$Baud;edition=$Edition;signature='1E9516';boot_sha256=$bootHash;boot_bytes=$bootBytes;boot_start=('0x'+$bootStart.ToString('X4'));application_test_bytes=$(if($ColdStartOnly-or $DiagnosticsOnly){0}else{$applicationBytes});eeprom_test_bytes=$(if($ColdStartOnly-or $DiagnosticsOnly){0}else{1024});diagnostic_bytes=$diagnostic.Length;restore_in_finally=$true;private_output=$taskDir;restore_only=$restoreOnly;cold_start_only=[bool]$ColdStartOnly;diagnostics_only=[bool]$DiagnosticsOnly}|ConvertTo-Json|Write-Output
if(-not $Run){return}
if ($restoreOnly) {
    Invoke-Avr (@('-n','-D','-A') + (Identity-VerifyArgs))
    if ($editionSettings.RequiresIsp) {
        Invoke-Avr @('-n','-D','-A','-U','flash:r:pre-restore-flash.bin:r')
        $currentFlash = [IO.File]::ReadAllBytes((Join-Path $taskDir 'pre-restore-flash.bin'))
        $currentBoot = [byte[]]::new($bootBytes)
        if ($currentFlash.Length -ne 32768) { throw 'Unexpected pre-restoration Flash size.' }
        [Array]::Copy($currentFlash,$bootStart,$currentBoot,0,$bootBytes)
        if ([Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($currentBoot)).ToLowerInvariant() -ne $expectedBootHash) {
            throw 'Current bootloader differs from the pinned edition build; refusing restoration.'
        }
    }
    Invoke-Avr @('-D','-A','-U','flash:w:restore-application.bin:r','-U','eeprom:w:before-eeprom.bin:r')
    Invoke-Avr @('-n','-D','-A','-U','flash:v:before-flash.bin:r','-U','eeprom:v:before-eeprom.bin:r')
    [Console]::WriteLine('Original Flash and EEPROM restored and verified from the saved backup.')
    return
}

# Verify that this is still the saved board before allowing any write.
Invoke-Avr (@('-n','-D','-A','-U','flash:v:before-flash.bin:r','-U','eeprom:v:before-eeprom.bin:r') + (Identity-VerifyArgs))
Add-Check $(if($editionSettings.RequiresIsp){'Initial serial memory/signature verification matches the fresh ISP installation and configuration'}else{'Initial full Flash, EEPROM, signature, fuse and lock verification'})
$failure=$null
$restorePassed=$false
$coldStartPassed=$false
$watchdogMaxMs=0
$watchdogCompleted=0
$dtrCompleted=0
$coldQueryReason=$null
$coldStartProof=$null
$runtimeConfigurationVerified=$false
try {
    if(-not $DiagnosticsOnly){
    if(-not $ColdStartOnly){
    # Only application Flash is written; the protected boot section is excluded.
    Invoke-Avr @('-D','-A','-U','flash:w:test-application.bin:r','-U','eeprom:w:test-eeprom.bin:r')
    Add-Check ('AVRDUDE write and automatic verify of all '+$applicationBytes+' application bytes')
    Add-Check 'AVRDUDE write and automatic verify of all 1024 EEPROM bytes'

    Open-Serial
    $capture=Capture-Output 7200 'runtime-diagnostics'
    [IO.File]::WriteAllText((Join-Path $taskDir 'runtime-diagnostics.txt'),$capture)
    Assert-DiagnosticFrames $capture
    Add-Check 'Application starts after AVRDUDE LEAVE_PROGMODE and prints at 115200 baud'
    Add-Check 'Three stable direct application reads of signature, fuses and lock bits'
    Add-Check 'Application boot reads blocked; boot write protection decoded as enabled'

    Enter-Boot
    if ($middle) { Send-Expect ([byte[]]@(0x31,0x20)) ([byte[]]@(0x14,0x10)) 'GET_SIGN_ON compatibility ACK without a sign-on string' }
    else { Send-Expect ([byte[]]@(0x31,0x20)) ([byte[]](@(0x14)+[Text.Encoding]::ASCII.GetBytes('AVR STK')+@(0x10))) 'GET_SIGN_ON' }
    Send-Expect ([byte[]]@(0x41,0x81,0x20)) ([byte[]]@(0x14,8,0x10)) 'Version major'
    Send-Expect ([byte[]]@(0x41,0x82,0x20)) ([byte[]]@(0x14,3,0x10)) 'Version minor'
    Send-Expect ([byte[]]@(0x75,0x20)) ([byte[]]@(0x14,0x1E,0x95,0x16,0x10)) 'Signature'
    if ($editionSettings.RequiresIsp) {
        $signatureBytes = [byte[]]@(0x1E,0x95,0x16)
        for ($index=0; $index-lt 3; $index++) {
            Send-Expect ([byte[]]@(0x56,0x30,0,$index,0,0x20)) ([byte[]]@(0x14,$signatureBytes[$index],0x10)) 'UNIVERSAL signature byte'
        }
        if ($middle) {
            foreach ($packet in @([byte[]]@(0x56,0x50,0,0,0,0x20),[byte[]]@(0x56,0x58,0,0,0,0x20))) {
                Send-Expect $packet ([byte[]]@(0x14,0,0x10)) 'UNIVERSAL fuse/lock operation is unsupported'
            }
        } else {
            foreach ($entry in @(@(0x50,0,0xFF),@(0x50,8,0xFD),@(0x58,0,0xCF),@(0x58,8,0xDC))) {
                Send-Expect ([byte[]]@(0x56,$entry[0],$entry[1],0,0,0x20)) ([byte[]]@(0x14,$entry[2],0x10)) 'UNIVERSAL actual fuse/lock byte'
            }
            Add-Check 'Full UNIVERSAL returns all four actual fuse/lock bytes'
        }
    }
    Add-Check $(if($middle){'Raw STK500v1 sync, ACK-only sign-on, version, READ_SIGN and UNIVERSAL signature'}else{'Raw STK500v1 sync, sign-on, version and ATmega328PB signature'})
    if ($fullEdition) {
        Send-Expect ([byte[]]@(0x40,0x81,0x42,0x20)) ([byte[]]@(0x14,0x10)) 'SET_PARAMETER compatibility ACK'
        Send-Expect ([byte[]]@(0x41,0x81,0x20)) ([byte[]]@(0x14,8,0x10)) 'SET_PARAMETER does not change fixed version'
        Send-Expect ([byte[]]@(0x40,0x20,0x20,0x20)) ([byte[]]@(0x14,0x10)) 'SET_PARAMETER consumes both payload bytes including EOP values'
        Send-Expect ([byte[]]@(0x30,0x20)) ([byte[]]@(0x14,0x10)) 'Sync after SET_PARAMETER payload'
        Reject-And-Restart ([byte[]]@(0x40,0x81,0x42,0)) 'SET_PARAMETER invalid EOP rejected'
        Reject-And-Restart ([byte[]]@(0x40,0x81)) 'Incomplete SET_PARAMETER recovers through watchdog' 1800
        Add-Check 'Full SET_PARAMETER consumes two bytes, keeps fixed parameters and rejects malformed packets'
    }
    Read-Memory 0 256 0x46 ([byte[]]$testApp[0..255])
    Read-Memory 0 256 0x46 ([byte[]]$testApp[0..255]) -LegacyZero
    Read-Memory $scratchAddress 256 0x46 ([byte[]]$testFlash[$scratchAddress..($bootStart+127)])
    Read-Memory 0x100 256 0x45 ([byte[]]$testEeprom[0x100..0x1FF])
    Add-Check '256-byte Flash and EEPROM reads, legacy zero length and app/boot boundary'

    Send-Expect ([byte[]]@(0x74,0,1,0x58,0x20)) ([byte[]]@(0x14,0x11)) 'Unknown read memory'
    Send-Expect ([byte[]](@(0x64,0,8,0x58)+@(0,0,0,0,0,0,0,0)+@(0x20))) ([byte[]]@(0x14,0x11)) 'Unknown write memory'
    Send-Expect ([byte[]]@(0x30,0x20)) ([byte[]]@(0x14,0x10)) 'Sync after rejected memory types'
    Add-Check 'Unknown memory types return FAILED and keep protocol synchronized'

    for($length=1;$length-le 16;$length++){
        $payload=[byte[]]::new($length);for($i=0;$i-lt $length;$i++){$payload[$i]=0x70+$i}
        Write-Memory 0x3F0 0x45 $payload
        Read-Memory 0x3F0 $length 0x45 $payload
        [Array]::Copy($payload,0,$testEeprom,0x3F0,$length)
    }
    Add-Check 'EEPROM blocks of every size 1 through 16 at the upper boundary'
    Write-Memory $scratchAddress 0x46 ([byte[]]@(0xA5,0x5A))
    $partial=[byte[]]::new(128);for($i=0;$i-lt 128;$i++){$partial[$i]=0xFF};$partial[0]=0xA5;$partial[1]=0x5A
    Read-Memory $scratchAddress 128 0x46 $partial
    Write-Memory $scratchAddress 0x46 ([byte[]]$testApp[$scratchAddress..($bootStart-1)])
    Add-Check 'Two-byte Flash write erases unspecified bytes; full last application page restored'

    Load-Address $scratchAddress
    Reject-And-Restart ([byte[]](@(0x64,0,128,0x46)+[byte[]]$testApp[$scratchAddress..($bootStart-1)]+@(0))) 'Invalid Flash EOP rejected before page erase'
    Read-Memory $scratchAddress 128 0x46 ([byte[]]$testApp[$scratchAddress..($bootStart-1)])
    Load-Address 0x3F0
    Reject-And-Restart ([byte[]](@(0x64,0,16,0x45)+@(0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0)+@(0))) 'Invalid EEPROM EOP rejected before commit'
    Read-Memory 0x3F0 16 0x45 ([byte[]]$testEeprom[0x3F0..0x3FF])
    Load-Address $bootStart
    # The rejected boot payload is IDENTICAL to the installed first boot page.
    Reject-And-Restart ([byte[]](@(0x64,0,128,0x46)+[byte[]]$boot[0..127]+@(0x20))) 'Boot-section write rejected; watchdog returns to application'
    Read-Memory $bootStart 128 0x46 ([byte[]]$boot[0..127])
    Load-Address 0x7FFE
    Reject-And-Restart ([byte[]]@(0x74,0,4,0x46,0x20)) 'Flash read beyond physical end rejected'
    Load-Address 0x3FE
    Reject-And-Restart ([byte[]]@(0x74,0,4,0x45,0x20)) 'EEPROM read beyond physical end rejected'
    Reject-And-Restart ([byte[]]@(0x74,1,1,0x46,0x20)) 'Read length 257 rejected'
    Reject-And-Restart ([byte[]]@(0x55,0,0x80,0x20)) 'Overflowing word address rejected'
    Reject-And-Restart ([byte[]]@(0x30,0)) 'Invalid SYNC EOP triggers watchdog recovery'
    $script:serialPort.DiscardInBuffer()
    $idleCapture=Capture-Output 3400
    Assert-AppStarted $idleCapture 'Bootloader idle timeout'
    Add-Check 'One-second bootloader idle watchdog starts the application'

    Enter-Boot
    foreach($length in @(0,1,3,129,130,256)){
        Load-Address $scratchAddress
        $packet=[byte[]]@(0x64,(($length-shr 8)-band 0xFF),($length-band 0xFF),0x46,0x20)
        Reject-And-Restart $packet ('Invalid Flash write length '+$length+' rejected before erase')
    }
    Load-Address ($scratchAddress+2)
    Reject-And-Restart ([byte[]]@(0x64,0,2,0x46,0,0,0x20)) 'Unaligned Flash write rejected'
    Load-Address 0x3F0
    Reject-And-Restart ([byte[]]@(0x64,0,17,0x45,0x20)) 'EEPROM write length 17 rejected'
    Load-Address 0x3FE
    Reject-And-Restart ([byte[]]@(0x64,0,4,0x45,0,0,0,0,0x20)) 'EEPROM write beyond physical end rejected'
    Load-Address $scratchAddress
    Reject-And-Restart ([byte[]](@(0x64,0,128,0x46)+[byte[]]$testApp[$scratchAddress..($scratchAddress+63)])) 'Incomplete Flash packet leaves the old page intact' 1800
    Read-Memory $scratchAddress 128 0x46 ([byte[]]$testApp[$scratchAddress..($bootStart-1)])
    Load-Address 0x3F0
    Reject-And-Restart ([byte[]](@(0x64,0,16,0x45)+@(0,0,0,0,0,0,0,0))) 'Incomplete EEPROM packet leaves the old bytes intact' 1800
    Read-Memory 0x3F0 16 0x45 ([byte[]]$testEeprom[0x3F0..0x3FF])
    Send-Expect ([byte[]]@(0x56,0,0,0,0,0x20)) ([byte[]]@(0x14,0,0x10)) 'Unsupported UNIVERSAL read-only query'
    Add-Check 'Unsupported UNIVERSAL operation returns zero without programming fuses'
    Send-Expect ([byte[]]@(0x52,0x20)) ([byte[]]@(0x14,0x10)) 'Compatibility chip erase acknowledgement'
    Read-Memory 0 128 0x46 ([byte[]]$testApp[0..127])
    Add-Check 'Legacy chip erase acknowledgement preserves application Flash'
    Close-Serial

    [IO.File]::WriteAllBytes((Join-Path $taskDir 'test-eeprom-after-raw.bin'),$testEeprom)
    Invoke-Avr (@('-n','-D','-A','-U','flash:v:test-full-flash.bin:r','-U','eeprom:v:test-eeprom-after-raw.bin:r') + (Identity-VerifyArgs))
    Add-Check $(if($middle){'Full Flash, EEPROM and signature still correct after all raw protocol cases'}else{'Full Flash and EEPROM still correct after all raw protocol cases; fuses and locks unchanged'})

    if ($editionSettings.HasAppSpm) {
        $spmProbe=[IO.File]::ReadAllBytes((Join-Path $taskDir 'app_spm_probe.bin'))
        if($spmProbe.Length-le 0-or $spmProbe.Length-gt $scratchAddress){throw 'Unexpected application SPM probe size.'}
        $spmProbeImage=[byte[]]::new([int]([Math]::Ceiling($spmProbe.Length/128.0)*128))
        for($i=0;$i-lt $spmProbeImage.Length;$i++){$spmProbeImage[$i]=0xFF}
        [Array]::Copy($spmProbe,0,$spmProbeImage,0,$spmProbe.Length)
        [IO.File]::WriteAllBytes((Join-Path $taskDir 'app-spm-probe-pages.bin'),$spmProbeImage)
        $spmExpectedFlash=[byte[]]$testFlash.Clone()
        [Array]::Copy($spmProbeImage,0,$spmExpectedFlash,0,$spmProbeImage.Length)
        [IO.File]::WriteAllBytes((Join-Path $taskDir 'app-spm-expected-flash.bin'),$spmExpectedFlash)
        Invoke-Avr @('-D','-A','-U','flash:w:app-spm-probe-pages.bin:r')
        Open-Serial
        Enter-Boot
        Send-Expect ([byte[]]@(0x51,0x20)) ([byte[]]@(0x14,0x10)) 'Start application SPM probe'
        $spmCapture=Capture-Output 2500
        [IO.File]::WriteAllText((Join-Path $taskDir 'app-spm-observation.txt'),$spmCapture)
        if(-not $spmCapture.Contains('APP_SPM_RESULT erase=PASS write=PASS restore=PASS r1=00 boot_calls=RETURNED')){
            throw 'Application SPM service did not complete the scratch-page and protected-Boot call checks.'
        }
        Close-Serial
        Invoke-Avr (@('-n','-D','-A','-U','flash:v:app-spm-expected-flash.bin:r',
                       '-U','eeprom:v:test-eeprom-after-raw.bin:r') + (Identity-VerifyArgs))
        Add-Check ($Edition+' application SPM erases, writes and restores the scratch page with r1 zero')
        Add-Check 'Protected Boot-address calls return; full Flash and EEPROM remain as expected'
    }

    }

    $probe=[IO.File]::ReadAllBytes((Join-Path $taskDir 'watchdog_probe.bin'))
    if($probe.Length-le 0-or $probe.Length-gt $scratchAddress){throw 'Unexpected watchdog probe size.'}
    $probeImage=[byte[]]::new([int]([Math]::Ceiling($probe.Length/128.0)*128))
    for($i=0;$i-lt $probeImage.Length;$i++){$probeImage[$i]=0xFF}
    [Array]::Copy($probe,0,$probeImage,0,$probe.Length)
    [IO.File]::WriteAllBytes((Join-Path $taskDir 'watchdog-probe-pages.bin'),$probeImage)
    Invoke-Avr @('-D','-A','-U','flash:w:watchdog-probe-pages.bin:r')
    Open-Serial
    $script:serialPort.Write('I')
    $ready=Probe-Ready;Assert-Probe $ready 8
    $ready | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath 'application-handoff-observation.json' -Encoding utf8
    Add-Check $(if($editionSettings.PreservesResetFlags){'Boot handoff clears r1, preserves Optiboot MCUSR parity and disables the watchdog'}else{'Boot handoff clears r1 and MCUSR before the C runtime and disables the watchdog'})
    if(-not $ColdStartOnly){
    $script:serialPort.DiscardInBuffer();$script:serialPort.Write('P')
    $pong=Capture-Output 100
    if(-not $pong.Contains('PONG')){throw 'Application UART receive/echo failed.'}
    Add-Check 'Application UART transmit and receive at 115200 baud'
    for($cycle=0;$cycle-lt 50;$cycle++){
        $script:serialPort.DiscardInBuffer();$script:serialPort.Write('W')
        $ready=Probe-Ready -AfterArmed;Assert-Probe $ready 8
        if($cycle-eq 0){$ready | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath 'first-watchdog-observation.json' -Encoding utf8}
        if($ready.elapsed_ms-ge 750){throw 'Watchdog reset unexpectedly waited in the bootloader.'}
        $watchdogMaxMs=[Math]::Max($watchdogMaxMs,$ready.elapsed_ms)
        $watchdogCompleted++
    }
    Add-Check '50 application-triggered 15ms watchdog resets restart the application without a reset loop'
    for($cycle=0;$cycle-lt 20;$cycle++){
        Enter-Boot
        Send-Expect ([byte[]]@(0x75,0x20)) ([byte[]]@(0x14,0x1E,0x95,0x16,0x10)) 'Signature during reset stress'
        Send-Expect ([byte[]]@(0x51,0x20)) ([byte[]]@(0x14,0x10)) 'LEAVE_PROGMODE during reset stress'
        $ready=Probe-Ready;Assert-Probe $ready 8
        $dtrCompleted++
    }
    Add-Check '20 consecutive DTR reset, sync, signature and LEAVE_PROGMODE cycles'
    Enter-Boot
    try{$script:serialPort.BreakState=$true;Start-Sleep -Milliseconds 20}
    finally{$script:serialPort.BreakState=$false}
    $ready=Probe-Ready 2500;Assert-Probe $ready 8
    Add-Check 'UART BREAK/framing-error input recovers through the watchdog'
    Close-Serial
    for($session=0;$session-lt 3;$session++){
        Invoke-Avr (@('-n','-D','-A') + (Identity-VerifyArgs))
    }
    Add-Check 'Three consecutive real AVRDUDE sessions reconnect and verify the device'
    } else { Close-Serial }
    if($ColdStart){
        Open-Serial
        Enter-Boot
        Send-Expect ([byte[]]@(0x51,0x20)) ([byte[]]@(0x14,0x10)) 'Start the armed cold-start probe'
        $ready=Probe-Ready;Assert-Probe $ready 8
        $script:serialPort.DiscardInBuffer()
        $script:serialPort.Write('C')
        $ready=Probe-Ready;Assert-Probe $ready 8
        Assert-Bytes $ready.entry ([byte[]]::new(8)) 'Cleared autonomous-start evidence record'
        if($ready.ticks-ne 0){throw 'Autonomous-start uptime counter did not clear.'}
        # Keep this handle open until physical removal so closing the serial
        # driver cannot reset the armed application before power is removed.
        [Console]::WriteLine('READY_FOR_POWER_CYCLE: unplug every Nano power source, then reconnect only its USB cable.')
        Wait-PortState $false
        Close-Serial
        Wait-PortState $true
        Start-Sleep -Milliseconds 4000
        Open-Serial
        $script:serialPort.Write('I')
        $ready=Probe-Ready;Assert-Probe $ready 0x0F
        $coldQueryReason=$ready.reason
        $record=$ready.entry
        try {
            $coldStartProof=Get-ColdStartProof $record $ready.ticks $Edition
        } finally {
            [ordered]@{query_reset_reason=$ready.reason;first_application_entry=[Convert]::ToHexString($record);autonomous_uptime_ticks=$ready.ticks;tick_ms=500;proof_kind=$coldStartProof} |
                ConvertTo-Json | Set-Content -LiteralPath 'cold-start-observation.json' -Encoding utf8
        }
        $coldStartPassed=$true
        Add-Check $(if($editionSettings.PreservesResetFlags){'Physical power cycle confirms autonomous application startup and execution'}else{'Physical power-off/on runs the application autonomously before the host opens the port'})
        Close-Serial
    }
    }
    if($editionSettings.RequiresIsp){
        # Independently recheck actual silicon configuration from the read-only
        # application after all protocol/reset tests, also for Middle without fuse queries.
        Invoke-Avr @('-D','-A','-U','flash:w:diagnostics.bin:r')
        Open-Serial
        $capture=Capture-Output 7200 'final-runtime-diagnostics'
        [IO.File]::WriteAllText((Join-Path $taskDir 'final-runtime-diagnostics.txt'),$capture)
        Assert-DiagnosticFrames $capture
        $runtimeConfigurationVerified=$true
        Add-Check $(if($DiagnosticsOnly){'Focused diagnostics: three stable direct signature, fuse, lock and Boot-access reports'}else{'Actual signature, fuses and locks unchanged after '+$Edition+' protocol/reset tests'})
        Close-Serial
    }
} catch {
    $failure=$_.Exception.Message
    [Console]::WriteLine('TEST FAILURE: '+$failure)
} finally {
    Close-Serial
    [Console]::WriteLine('Restoring the original complete application and EEPROM.')
    try {
        Invoke-Avr @('-D','-A','-U','flash:w:restore-application.bin:r','-U','eeprom:w:before-eeprom.bin:r')
        Invoke-Avr (@('-n','-D','-A','-U','flash:r:restored-flash.bin:r','-U','eeprom:r:restored-eeprom.bin:r') + (Identity-VerifyArgs))
        Assert-Files 'restored-flash.bin' 'before-flash.bin'
        Assert-Files 'restored-eeprom.bin' 'before-eeprom.bin'
        $restorePassed=$true
        Add-Check $(if($middle){'Original complete Flash/EEPROM and signature restored and verified'}else{'Original complete Flash, EEPROM, signature, fuses and lock bits restored and verified'})
    } finally {
        [ordered]@{port=$Port;baud=$Baud;edition=$Edition;firmware_source_commit=$firmwareSourceCommit;mcu='ATmega328PB';boot_bytes=$bootBytes;boot_start=('0x'+$bootStart.ToString('X4'));application_bytes=$applicationBytes;boot_sha256=$bootHash;
            checks=$script:checks;failure=$failure;original_state_restored=$restorePassed;
            cold_start_requested=[bool]$ColdStart;cold_start_passed=$coldStartPassed;cold_start_query_reason=$coldQueryReason;
            cold_start_only=[bool]$ColdStartOnly;cold_start_proof=$coldStartProof;
            diagnostics_only=[bool]$DiagnosticsOnly;test_mode=$(if($DiagnosticsOnly){'diagnostics_only'}elseif($ColdStartOnly){'cold_start_only'}else{'full'});
            watchdog_cycles=$watchdogCompleted;dtr_cycles=$dtrCompleted;max_watchdog_restart_host_ms=$watchdogMaxMs;
            middle_runtime_configuration_verified=($middle -and $runtimeConfigurationVerified);runtime_configuration_verified=$runtimeConfigurationVerified;
            lfuse='FF';hfuse=$expectedHighFuse;efuse='FD';lock='CF'} |
            ConvertTo-Json -Depth 6 | Set-Content -LiteralPath 'usb-test-result.json' -Encoding utf8
    }
}
if(-not $restorePassed){throw 'Original state restoration was not verified.'}
if($null-ne $failure){throw $failure}
[Console]::WriteLine('ALL REQUESTED USB HARDWARE TESTS PASSED; ORIGINAL DATA RESTORED.')
