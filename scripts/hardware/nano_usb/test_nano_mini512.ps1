#Requires -Version 7.2
# GPL-2.0-or-later. Experimental Mini USB qualification on ATmega328PB.
# Default mode builds probes and verifies application Flash without writing.
# Mini cannot read Boot/EEPROM or restore EEPROM: final ISP work is mandatory.
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Port,
    [Parameter(Mandatory)][string]$IspBackupDirectory,
    [string]$AvrdudePath = 'avrdude',
    [string]$AvrdudeConfig = '',
    [string]$OutputDirectory = '',
    [switch]$UseWslToolchain,
    [switch]$ColdStart,
    [switch]$Run
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$sourceDir = $PSScriptRoot
$repoRoot = [IO.Path]::GetFullPath((Join-Path $sourceDir '../../..'))
$Baud = 115200
$bootBytes = 512
$bootStart = 0x7E00
$applicationBytes = 32256
$expectedHighFuse = 'DE'
$expectedBootHash = 'ff0b46f3276f4a8c75a0b765d263eac5ae93f5fe6bd1dddafa572ca49aff959d'
$IspBackupDirectory = [IO.Path]::GetFullPath($IspBackupDirectory)
if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $OutputDirectory = Join-Path $repoRoot ('.worktree/nano-mini512-usb-' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfff'))
}
$taskDir = [IO.Path]::GetFullPath($OutputDirectory)
$rootPrefix = $repoRoot.TrimEnd('\','/') + [IO.Path]::DirectorySeparatorChar
$privatePrefix = [IO.Path]::GetFullPath((Join-Path $repoRoot '.worktree')).TrimEnd('\','/') + [IO.Path]::DirectorySeparatorChar
if ($taskDir.StartsWith($rootPrefix,[StringComparison]::OrdinalIgnoreCase) -and
    -not $taskDir.StartsWith($privatePrefix,[StringComparison]::OrdinalIgnoreCase)) {
    throw 'Device backups inside this checkout must be under the ignored .worktree directory.'
}
if (Test-Path -LiteralPath $taskDir) { throw 'OutputDirectory must not exist; existing backups are never overwritten.' }
New-Item -ItemType Directory -Path $taskDir | Out-Null
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

function Assert-MiniIspEvidence {
    $isp = Get-Content -LiteralPath (Join-Path $IspBackupDirectory 'isp-result.json') -Raw | ConvertFrom-Json
    if ($isp.isp_programming-ne 'PASS' -or $isp.complete_flash_readback-ne 'PASS' -or
        $isp.eeprom_readback-ne 'PASS' -or $isp.edition-ne 'mini-experimental-512' -or
        $isp.boot_sha256-ne $expectedBootHash -or $isp.boot_bytes-ne 512 -or $isp.boot_start-ne '0x7E00') {
        throw 'A verified current-board ISP installation of the pinned experimental image is required.'
    }
    foreach($entry in @(@('signature','1E9516'),@('lfuse','FF'),@('hfuse','DE'),@('efuse','FD'),@('lock','CF'))) {
        $path=Join-Path $IspBackupDirectory ('after-'+$entry[0]+'.bin')
        if([Convert]::ToHexString([IO.File]::ReadAllBytes($path))-ne $entry[1]) {
            throw ('Unexpected verified ISP '+$entry[0]+'.')
        }
        Copy-Item -LiteralPath $path -Destination ('before-'+$entry[0]+'.bin')
    }
    $flash=[IO.File]::ReadAllBytes((Join-Path $IspBackupDirectory 'after-flash.bin'))
    $eeprom=[IO.File]::ReadAllBytes((Join-Path $IspBackupDirectory 'after-eeprom.bin'))
    if($flash.Length-ne 32768-or $eeprom.Length-ne 1024){throw 'Incomplete current-board ISP memory snapshots.'}
    $boot=[byte[]]::new(512); [Array]::Copy($flash,0x7E00,$boot,0,512)
    if([Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($boot)).ToLowerInvariant()-ne $expectedBootHash){
        throw 'Verified ISP snapshot does not contain the pinned experimental Boot image.'
    }
    Copy-Item -LiteralPath (Join-Path $IspBackupDirectory 'after-flash.bin') -Destination 'before-flash.bin'
    Copy-Item -LiteralPath (Join-Path $IspBackupDirectory 'after-eeprom.bin') -Destination 'before-eeprom.bin'
    Copy-Item -LiteralPath (Join-Path $IspBackupDirectory 'isp-result.json') -Destination 'verified-isp-result.json'
    [IO.File]::WriteAllText((Join-Path $taskDir 'isp-backup-directory.txt'),$IspBackupDirectory)
    $original=[byte[]]::new(32256); [Array]::Copy($flash,0,$original,0,32256)
    [IO.File]::WriteAllBytes((Join-Path $taskDir 'restore-application.bin'),$original)
    [IO.File]::WriteAllBytes((Join-Path $taskDir 'verified-boot.bin'),$boot)
}
function Verify-Application([string]$Image) {
    # The input has exactly the application extent. No whole-Flash read is sent.
    if((Get-Item -LiteralPath (Join-Path $taskDir $Image)).Length-ne 32256){
        throw 'Mini verification input must cover exactly the application region.'
    }
    Invoke-Avr @('-n','-D','-A','-U',('flash:v:'+$Image+':r'),'-U','signature:v:before-signature.bin:r')
}
function Write-Page([int]$Address,[byte[]]$Payload) {
    if($Payload.Length-ne 128-or ($Address-band 127)-ne 0-or $Address-lt 0-or $Address-ge 0x7E00){
        throw 'Only full aligned application pages may be written.'
    }
    Load-Address $Address
    Send-Expect ([byte[]](@(0x64,0,128,0x46)+$Payload+@(0x20))) ([byte[]]@(0x14,0x10)) 'PROG_PAGE'
}
function Read-Page([int]$Address,[int]$Count,[byte[]]$Expected) {
    if($Count-lt 1-or $Count-gt 128-or ($Address-band 127)-ne 0-or $Address-lt 0-or $Address-ge 0x7E00){
        throw 'Mini reads require an aligned application page and length 1..128.'
    }
    Load-Address $Address
    Send-Expect ([byte[]]@(0x74,0,$Count,0x46,0x20)) ([byte[]](@(0x14)+$Expected+@(0x10))) 'READ_PAGE'
}
function Reject-MiniPacket([byte[]]$Packet,[string]$Name,[int]$WaitMs=1800) {
    $script:serialPort.DiscardInBuffer()
    $script:serialPort.Write($Packet,0,$Packet.Length)
    $capture=Capture-Output $WaitMs
    if(-not $capture.Contains('BOOT_ACCESS_DIAGNOSTICS_V1')-or $capture.Contains([char]0x10)){
        throw ($Name+': watchdog recovery to the diagnostic application was not observed.')
    }
    Add-Check $Name
    Enter-Boot
}
function Read-MiniProbe([int]$TimeoutMs=1800,[switch]$AfterArmed) {
    $text=[Text.StringBuilder]::new(); $timer=[Diagnostics.Stopwatch]::StartNew(); $readCalls=0
    while($timer.ElapsedMilliseconds-lt $TimeoutMs){
        [void]$text.Append((Read-AvailableText $script:serialPort ([ref]$readCalls)))
        $received=$text.ToString()
        if($AfterArmed){
            $armed=$received.IndexOf('WDT_ARMED')
            if($armed-lt 0){Start-Sleep -Milliseconds 5;continue}
            $received=$received.Substring($armed)
        }
        $match=[regex]::Match($received,'APP_READY reason=[0-9A-F]{2} r1=([0-9A-F]{2}) mcusr=([0-9A-F]{2}) wdt=([0-9A-F]{2}) entry=([0-9A-F]{16}) ticks=([0-9A-F]{4})')
        if($match.Success){
            # The reused probe prints r2, but Mini defines no reset-cause ABI.
            # Never interpret or export that byte as a reset reason.
            return [pscustomobject]@{r1=[Convert]::ToInt32($match.Groups[1].Value,16);
                mcusr=[Convert]::ToInt32($match.Groups[2].Value,16);wdt=[Convert]::ToInt32($match.Groups[3].Value,16);
                entry=[Convert]::FromHexString($match.Groups[4].Value);ticks=[Convert]::ToInt32($match.Groups[5].Value,16);
                elapsed_ms=$timer.ElapsedMilliseconds;bytes_read=$text.Length;read_calls=$readCalls;reset_reason_available=$false}
        }
        Start-Sleep -Milliseconds 5
    }
    throw 'The Mini watchdog probe did not report a complete startup.'
}
function Assert-MiniProbe($Ready) {
    if($Ready.r1-ne 0-or $Ready.mcusr-ne 0-or ($Ready.wdt-band 0x48)-ne 0){
        throw ('Unexpected Mini handoff: r1={0:X2}, MCUSR={1:X2}, WDTCSR={2:X2}.' -f $Ready.r1,$Ready.mcusr,$Ready.wdt)
    }
}
function Save-MiniProbe($Ready,[string]$Name) {
    [ordered]@{r1=$Ready.r1;mcusr=$Ready.mcusr;wdt=$Ready.wdt;elapsed_ms=$Ready.elapsed_ms;
        bytes_read=$Ready.bytes_read;read_calls=$Ready.read_calls;reset_reason_available=$false} |
        ConvertTo-Json | Set-Content -LiteralPath $Name -Encoding utf8
}
function Assert-MiniColdProof([byte[]]$Record,[int]$Ticks) {
    if($Record.Length-ne 8-or [Text.Encoding]::ASCII.GetString($Record,0,4)-ne 'STAR'-or
        $Ticks-lt 3-or $Ticks-gt 65535-or $Record[5]-ne 0-or $Record[6]-ne 0-or ($Record[7]-band 0x48)-ne 0){
        throw 'At least three saved autonomous ticks and valid Mini handoff state are required.'
    }
    return 'first_invocation_uptime_at_least_1500ms'
}
function Pad-ApplicationProbe([string]$Source,[string]$Destination) {
    $data=[IO.File]::ReadAllBytes((Join-Path $taskDir $Source))
    if($data.Length-le 0-or $data.Length-gt 0x7D80){throw 'Unexpected standalone application probe size.'}
    $pages=[byte[]]::new([int]([Math]::Ceiling($data.Length/128.0)*128))
    [Array]::Fill[byte]($pages,255); [Array]::Copy($data,0,$pages,0,$data.Length)
    [IO.File]::WriteAllBytes((Join-Path $taskDir $Destination),$pages)
}

Assert-MiniIspEvidence
foreach($probe in @('diagnostics','watchdog_probe')) {
    $source=Tool-Path (Join-Path $sourceDir ($probe+'.c'))
    $elf=Tool-Path (Join-Path $taskDir ($probe+'.elf'))
    $bin=Tool-Path (Join-Path $taskDir ($probe+'.bin'))
    $flags=@('-mmcu=atmega328p','-DF_CPU=16000000UL','-Os','-std=gnu11')
    if($probe-eq 'diagnostics'){$flags+='-DDIAGNOSTICS_STANDALONE'}
    Invoke-BuildTool 'avr-gcc' ($flags+@($source,'-o',$elf))
    Invoke-BuildTool 'avr-objcopy' @('-O','binary','-R','.eeprom',$elf,$bin)
    $disassembly=Invoke-BuildTool 'avr-objdump' @('-d',$elf)
    $disassembly | Set-Content -LiteralPath ($probe+'.disassembly.txt') -Encoding utf8
    if([regex]::IsMatch(($disassembly -join "`n"),'(?m)^\s*[0-9a-f]+:.*\bspm\b')){
        throw 'The diagnostic/watchdog application contains an SPM instruction.'
    }
}
$beforeApplication=[IO.File]::ReadAllBytes((Join-Path $taskDir 'restore-application.bin'))
$boot=[IO.File]::ReadAllBytes((Join-Path $taskDir 'verified-boot.bin'))
$diagnostic=[IO.File]::ReadAllBytes((Join-Path $taskDir 'diagnostics.bin'))
$testApp=[byte[]]::new($applicationBytes)
for($i=0;$i-lt $testApp.Length;$i++){$testApp[$i]=(($i*73)-bxor($i-shr 8)-bxor 0xA5)-band 0xFF}
if($diagnostic.Length-le 0-or $diagnostic.Length-gt 0x7D80){throw 'Unexpected diagnostic application size.'}
[Array]::Copy($diagnostic,0,$testApp,0,$diagnostic.Length)
[IO.File]::WriteAllBytes((Join-Path $taskDir 'test-application.bin'),$testApp)
Pad-ApplicationProbe 'diagnostics.bin' 'diagnostics-pages.bin'
Pad-ApplicationProbe 'watchdog_probe.bin' 'watchdog-probe-pages.bin'
Verify-Application 'restore-application.bin'
[ordered]@{edition='mini-experimental-512';mcu='ATmega328PB';signature='1E9516';boot_bytes=512;
    boot_start='0x7E00';boot_sha256=$expectedBootHash;application_bytes=32256;baud=115200;
    reset_reason_available=$false;final_isp_required=$true;private_output=$taskDir;
    eeprom_protocol_supported=$false;boot_reads_supported=$false}|ConvertTo-Json|Write-Output
if(-not $Run){return}
Add-Check 'Initial application-only AVRDUDE verification matches the fresh ISP snapshot and signature'
$failure=$null; $applicationRestored=$false; $eepromProbeMayHaveWritten=$false
$initialRuntimeConfigurationVerified=$false; $runtimeConfigurationVerified=$false; $coldPassed=$false; $coldProof=$null
$watchdogCompleted=0; $dtrCompleted=0; $watchdogMaxMs=0
try {
    Invoke-Avr @('-D','-A','-U','flash:w:test-application.bin:r')
    Add-Check 'AVRDUDE writes and automatically verifies all 32256 application bytes'
    Open-Serial
    $capture=Capture-Output 7200 'runtime-diagnostics'
    [IO.File]::WriteAllText((Join-Path $taskDir 'runtime-diagnostics.txt'),$capture)
    Assert-DiagnosticFrames $capture
    $initialRuntimeConfigurationVerified=$true
    Add-Check 'Three direct application signature, fuse, lock and protected-Boot reports match ISP'
    Enter-Boot
    for($parameter=0;$parameter-lt 256;$parameter++){
        Send-Expect ([byte[]]@(0x41,$parameter,0x20)) ([byte[]]@(0x14,3,0x10)) 'Fixed GET_PARAMETER reply'
    }
    Send-Expect ([byte[]]@(0x75,0x20)) ([byte[]]@(0x14,0x1E,0x95,0x16,0x10)) 'READ_SIGN'
    # Signature access uses 0x7Fxx; parameters must reload their 0x7Exx address.
    Send-Expect ([byte[]]@(0x41,0x81,0x20)) ([byte[]]@(0x14,3,0x10)) 'Parameter after READ_SIGN high-byte relocation'
    Send-Expect ([byte[]](@(0x42)+(0..19)+@(0x20))) ([byte[]]@(0x14,0x10)) 'SET_DEVICE payload'
    Send-Expect ([byte[]](@(0x45,0x20,1,2,3,4,0x20))) ([byte[]]@(0x14,0x10)) 'SET_DEVICE_EXT payload'
    Add-Check 'All 256 parameter IDs, READ_SIGN and setup payloads preserve synchronization'
    foreach($address in @(0,0x4000,0x7D80)){
        $page=[byte[]]$testApp[$address..($address+127)]
        Write-Page $address $page
        for($length=1;$length-le 128;$length++){
            Read-Page $address $length ([byte[]]$page[0..($length-1)])
        }
    }
    Add-Check 'Full-page writes and every valid read length pass on first, upper-half and final application pages'
    foreach($length in @(0,1,2,3,127,129,130,256)){
        Load-Address 0x7D80
        Reject-MiniPacket ([byte[]]@(0x64,(($length-shr 8)-band 255),($length-band 255),0x46,0x20)) ('Flash write length '+$length+' rejected')
    }
    foreach($length in @(0,129,256,257)){
        Load-Address 0x7D80
        Reject-MiniPacket ([byte[]]@(0x74,(($length-shr 8)-band 255),($length-band 255),0x46,0x20)) ('Flash read length '+$length+' rejected')
    }
    foreach($address in @(2,0x7D82)){
        foreach($command in @(0x64,0x74)){
            Load-Address $address
            $packet=[byte[]]@( $command,0,128,0x46 )
            if($command-eq 0x64){$packet=[byte[]]($packet+[byte[]]$testApp[0..127])}
            Reject-MiniPacket ([byte[]]($packet+@(0x20))) ('Unaligned '+$command.ToString('X2')+' address '+$address.ToString('X4')+' rejected')
        }
    }
    foreach($address in @(0x7E00,0x7E80,0x7F00,0x7F80)){
        Load-Address $address
        Reject-MiniPacket ([byte[]]@(0x74,0,128,0x46,0x20)) ('Boot read '+$address.ToString('X4')+' rejected')
        Load-Address $address
        $offset=$address-0x7E00
        Reject-MiniPacket ([byte[]](@(0x64,0,128,0x46)+[byte[]]$boot[$offset..($offset+127)]+@(0x20))) ('Identical Boot write '+$address.ToString('X4')+' rejected')
    }
    foreach($address in @(0x8000,0xFF80)){
        Load-Address $address
        Reject-MiniPacket ([byte[]]@(0x74,0,128,0x46,0x20)) ('Out-of-Flash read '+$address.ToString('X4')+' rejected')
        Load-Address $address
        Reject-MiniPacket ([byte[]](@(0x64,0,128,0x46)+[byte[]]$testApp[0..127]+@(0x20))) ('Out-of-Flash write '+$address.ToString('X4')+' rejected')
    }
    foreach($type in @(0x45,0x58)){
        Load-Address 0
        Reject-MiniPacket ([byte[]]@(0x74,0,1,$type,0x20)) ('Unsupported memory read '+$type.ToString('X2')+' rejected')
        Load-Address 0
        Reject-MiniPacket ([byte[]](@(0x64,0,128,$type)+[byte[]]$testApp[0..127]+@(0x20))) ('Unsupported memory write '+$type.ToString('X2')+' rejected')
    }
    Reject-MiniPacket ([byte[]]@(0x55,0,0x80,0x20)) 'Overflowing word address rejected'
    Reject-MiniPacket ([byte[]]@(0x56,0x30,0,0,0,0x20)) 'UNIVERSAL signature packet is unsupported and recovers without an ISP operation'
    Reject-MiniPacket ([byte[]]@(0x30,0)) 'Invalid SYNC EOP recovers through watchdog'
    Load-Address 0x7D80
    Reject-MiniPacket ([byte[]](@(0x64,0,128,0x46)+[byte[]]$testApp[0x7D80..0x7DFF]+@(0))) 'Invalid Flash EOP is rejected before page erase'
    foreach($count in @(0,1,64,127)){
        Load-Address 0x7D80
        $packet=[byte[]]@(0x64,0,128,0x46)
        if($count-gt 0){$packet=[byte[]]($packet+[byte[]]$testApp[0x7D80..(0x7D80+$count-1)])}
        Reject-MiniPacket $packet ('Incomplete Flash payload '+$count+' leaves the page intact')
    }
    Send-Expect ([byte[]]@(0x52,0x20)) ([byte[]]@(0x14,0x10)) 'Legacy Chip Erase acknowledgement'
    Close-Serial
    Verify-Application 'test-application.bin'
    Add-Check 'Complete application remains exact after all raw protocol, rejection and no-op Chip Erase cases'
    $eepromProbeMayHaveWritten=$true
    Invoke-Avr @('-D','-A','-U','flash:w:watchdog-probe-pages.bin:r')
    Open-Serial
    $script:serialPort.Write('I')
    $ready=Read-MiniProbe; Assert-MiniProbe $ready
    Save-MiniProbe $ready 'application-handoff-observation.json'
    Add-Check 'Mini application handoff clears r1 and MCUSR and disables watchdog; r2 is not interpreted'
    $script:serialPort.DiscardInBuffer(); $script:serialPort.Write('P')
    if(-not (Capture-Output 100).Contains('PONG')){throw 'Application UART echo failed.'}
    Add-Check 'Application UART transmit and receive at 115200 baud'
    for($cycle=0;$cycle-lt 50;$cycle++){
        $script:serialPort.DiscardInBuffer(); $script:serialPort.Write('W')
        $ready=Read-MiniProbe -AfterArmed; Assert-MiniProbe $ready
        if($ready.elapsed_ms-ge 750){throw 'Mini watchdog restart unexpectedly waited in the UART loader.'}
        if($cycle-eq 0){Save-MiniProbe $ready 'first-watchdog-observation.json'}
        $watchdogMaxMs=[Math]::Max($watchdogMaxMs,$ready.elapsed_ms); $watchdogCompleted++
    }
    Add-Check '50 application watchdog resets restart without a reset loop'
    for($cycle=0;$cycle-lt 20;$cycle++){
        Enter-Boot
        Send-Expect ([byte[]]@(0x75,0x20)) ([byte[]]@(0x14,0x1E,0x95,0x16,0x10)) 'READ_SIGN during DTR stress'
        Send-Expect ([byte[]]@(0x51,0x20)) ([byte[]]@(0x14,0x10)) 'LEAVE_PROGMODE during DTR stress'
        $ready=Read-MiniProbe; Assert-MiniProbe $ready; $dtrCompleted++
    }
    Add-Check '20 DTR reset, sync, signature and leave cycles'
    Enter-Boot
    try{$script:serialPort.BreakState=$true; Start-Sleep -Milliseconds 20}
    finally{$script:serialPort.BreakState=$false}
    $ready=Read-MiniProbe 2500; Assert-MiniProbe $ready
    Add-Check 'BREAK input recovers through watchdog'
    Close-Serial
    for($session=0;$session-lt 3;$session++){
        Invoke-Avr @('-n','-D','-A','-U','signature:v:before-signature.bin:r')
    }
    Add-Check 'Three real AVRDUDE signature sessions reconnect'
    if($ColdStart){
        Open-Serial; Enter-Boot
        Send-Expect ([byte[]]@(0x51,0x20)) ([byte[]]@(0x14,0x10)) 'Start the armed cold probe'
        $ready=Read-MiniProbe; Assert-MiniProbe $ready
        $script:serialPort.DiscardInBuffer(); $script:serialPort.Write('C')
        $ready=Read-MiniProbe; Assert-MiniProbe $ready
        Assert-Bytes $ready.entry ([byte[]]::new(8)) 'Cleared first-entry record'
        if($ready.ticks-ne 0){throw 'Cold-start uptime counter did not clear.'}
        [Console]::WriteLine('READY_FOR_POWER_CYCLE: unplug all Nano power, then reconnect only USB in the same port.')
        Wait-PortState $false; Close-Serial; Wait-PortState $true
        Start-Sleep -Milliseconds 6000
        Open-Serial; $script:serialPort.Write('I')
        $ready=Read-MiniProbe; Assert-MiniProbe $ready
        try{$coldProof=Assert-MiniColdProof $ready.entry $ready.ticks}
        finally{
            [ordered]@{tag=[Text.Encoding]::ASCII.GetString($ready.entry,0,4);initial_r1=$ready.entry[5];
                initial_mcusr=$ready.entry[6];initial_wdt=$ready.entry[7];autonomous_uptime_ticks=$ready.ticks;
                nominal_tick_ms=500;host_wait_after_reconnect_ms=6000;reset_reason_available=$false;proof_kind=$coldProof} |
                ConvertTo-Json | Set-Content -LiteralPath 'cold-start-observation.json' -Encoding utf8
        }
        $coldPassed=$true
        Add-Check 'Physical power cycle records at least three autonomous first-invocation uptime ticks'
        Close-Serial
    }
    Invoke-Avr @('-D','-A','-U','flash:w:diagnostics-pages.bin:r')
    Open-Serial
    $capture=Capture-Output 7200 'final-runtime-diagnostics'
    [IO.File]::WriteAllText((Join-Path $taskDir 'final-runtime-diagnostics.txt'),$capture)
    Assert-DiagnosticFrames $capture
    $runtimeConfigurationVerified=$true
    Add-Check 'Final direct application diagnostics confirm signature, fuses, locks and Boot geometry'
    Close-Serial
} catch {
    $failure=$_.Exception.Message
    [Console]::WriteLine('TEST FAILURE: '+$failure)
} finally {
    Close-Serial
    [Console]::WriteLine('Restoring application Flash only; EEPROM restoration and Boot verification require ISP.')
    try {
        Invoke-Avr @('-D','-A','-U','flash:w:restore-application.bin:r')
        Verify-Application 'restore-application.bin'
        $applicationRestored=$true
        Add-Check 'Original application Flash restored and independently verified over Mini UART'
    } finally {
        [ordered]@{edition='mini-experimental-512';mcu='ATmega328PB';signature='1E9516';boot_bytes=512;
            boot_start='0x7E00';boot_sha256=$expectedBootHash;application_bytes=32256;baud=115200;
            boot_hash_source='verified_pre_test_isp_snapshot';boot_readback_performed_over_uart=$false;
            checks=$script:checks;failure=$failure;application_restored_and_verified=$applicationRestored;
            complete_device_restoration_verified=$false;eeprom_restoration_verified=$false;
            eeprom_probe_may_have_written=$eepromProbeMayHaveWritten;
            expected_probe_eeprom_range=$(if($eepromProbeMayHaveWritten){@(1014,1023)}else{@()});
            boot_unchanged_verified=$false;final_isp_required=$true;reset_reason_available=$false;
            cold_start_requested=[bool]$ColdStart;cold_start_passed=$coldPassed;cold_start_proof=$coldProof;
            initial_runtime_configuration_verified=$initialRuntimeConfigurationVerified;
            runtime_configuration_verified=$runtimeConfigurationVerified;
            watchdog_cycles=$watchdogCompleted;dtr_cycles=$dtrCompleted;max_watchdog_restart_host_ms=$watchdogMaxMs;
            lfuse='FF';hfuse='DE';efuse='FD';lock='CF'} | ConvertTo-Json -Depth 6 |
            Set-Content -LiteralPath 'usb-test-result.json' -Encoding utf8
    }
}
if(-not $applicationRestored){throw 'Application restoration was not verified; retain every ISP backup.'}
if($null-ne $failure){throw $failure}
[Console]::WriteLine('USB CHECKS PASSED; APPLICATION RESTORED. RECONNECT ISP TO RESTORE EEPROM AND VERIFY BOOT/COMPLETE DEVICE.')
