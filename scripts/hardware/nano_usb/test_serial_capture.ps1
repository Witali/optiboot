#Requires -Version 7.2
# GPL-2.0-or-later. Extract helpers only; never execute the hardware runner.
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$tokens=$null; $errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot 'test_nano_usb.ps1'),[ref]$tokens,[ref]$errors)
if($errors.Count-ne 0){throw 'Runner syntax failure.'}
foreach($name in @('Read-AvailableText','Capture-Output','Crc16','Assert-DiagnosticFrames')) {
    $definitions=@($ast.FindAll({param($node)
        $node-is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name-eq $name
    },$true))
    if($definitions.Count-ne 1){throw ('Missing helper '+$name+'.')}
    . ([ScriptBlock]::Create($definitions[0].Extent.Text))
}
if(-not ('SyntheticSerialCapturePort' -as [type])) {
    Add-Type @"
using System;
using System.Collections.Generic;
public sealed class SyntheticSerialCapturePort {
    public byte[] Data;
    public int Position;
    public int MaximumRead = int.MaxValue;
    public int ReturnedCountOverride = int.MinValue;
    public List<int> Requests = new List<int>();
    public SyntheticSerialCapturePort(byte[] data) { Data=data; }
    public int BytesToRead { get { return Data.Length-Position; } }
    public int Read(byte[] buffer, int offset, int count) {
        Requests.Add(count);
        if(ReturnedCountOverride!=int.MinValue) return ReturnedCountOverride;
        int actual=Math.Min(count,Math.Min(MaximumRead,BytesToRead));
        Array.Copy(Data,Position,buffer,offset,actual);
        Position+=actual;
        return actual;
    }
}
"@
}
$script:passed=0
function Check($Actual,$Expected,[string]$Name) {
    if($Actual-cne $Expected){throw ($Name+': unexpected result.')}
    $script:passed++
}
function Reject([scriptblock]$Action,[string]$Name) {
    $caught=$false
    try { & $Action | Out-Null } catch { $caught=$true }
    if(-not $caught){throw ($Name+': invalid input accepted.')}
    $script:passed++
}

$fake=[SyntheticSerialCapturePort]::new([byte[]]::new(0)); $calls=0
$text=Read-AvailableText $fake ([ref]$calls)
Check ($null-ne $text) $true 'No-data returns an empty string'
Check $text.Length 0 'No-data text length'
Check $calls 0 'No-data avoids a read'
Check $fake.Requests.Count 0 'No-data never calls the port'

$fake=[SyntheticSerialCapturePort]::new([Text.Encoding]::ASCII.GetBytes('ABCDEF')); $calls=0
$fake.MaximumRead=2
Check (Read-AvailableText $fake ([ref]$calls)) 'AB' 'Partial read excludes unused buffer bytes'
Check (Read-AvailableText $fake ([ref]$calls)) 'CD' 'Partial reads continue without duplication'
Check (Read-AvailableText $fake ([ref]$calls)) 'EF' 'Partial reads preserve the tail'
Check $calls 3 'Partial-read accounting'
Check ($fake.Requests -join ',') '6,4,2' 'Requests follow actual remaining bytes'

$fake=[SyntheticSerialCapturePort]::new([byte[]]@(65,66,67)); $calls=0
$fake.ReturnedCountOverride=0
Check (Read-AvailableText $fake ([ref]$calls)) '' 'Zero-byte read emits no padding'
Check $calls 1 'Zero-byte read is counted'

$data=[byte[]]::new(9000); [Array]::Fill[byte]($data,88)
$fake=[SyntheticSerialCapturePort]::new($data); $calls=0
$parts=@(Read-AvailableText $fake ([ref]$calls); Read-AvailableText $fake ([ref]$calls); Read-AvailableText $fake ([ref]$calls))
Check (($parts | ForEach-Object {$_.Length}) -join ',') '4096,4096,808' 'Bounded chunk sizes'
Check ($fake.Requests -join ',') '4096,4096,808' 'Port requests never exceed 4096 bytes'
Check (($parts -join '').Length) 9000 'All chunk bytes retained'
Check $calls 3 'Chunk read accounting'

foreach($invalidCount in @(-1,4)) {
    $fake=[SyntheticSerialCapturePort]::new([byte[]]@(65,66,67))
    $fake.ReturnedCountOverride=$invalidCount
    Reject {Read-AvailableText $fake} ('Invalid returned count '+$invalidCount)
}
$fake=[SyntheticSerialCapturePort]::new([byte[]]@(65,0,66))
Check ([Convert]::ToHexString([Text.Encoding]::ASCII.GetBytes((Read-AvailableText $fake)))) '410042' 'Real NUL bytes remain observable'

$script:serialPort=[SyntheticSerialCapturePort]::new([Text.Encoding]::ASCII.GetBytes('ABC'))
$script:serialPort.MaximumRead=1
Check (Capture-Output 90) 'ABC' 'Capture joins partial reads once'
Check $script:lastCaptureMetrics.bytes_read 3 'Capture counts actual bytes'
Check $script:lastCaptureMetrics.read_calls 3 'Capture counts actual read calls'
Check ($script:lastCaptureMetrics.elapsed_ms-ge 90) $true 'Capture records elapsed time'
Check $script:lastCaptureMetrics.maximum_read_bytes 4096 'Capture records chunk bound'

$bootBytes=1024; $bootStart=0x7C00; $expectedHighFuse='DC'
$frame="BOOT_ACCESS_DIAGNOSTICS_V1`n" + (@(
    'signature=1E9516','lfuse=FF','hfuse=DC','efuse=FD','lock_raw=CF','lock_implemented=0F',
    'repeated_reads=STABLE','boot_size_hex=0400','boot_start_hex=7C00','reset_target=BOOT',
    'app_lpm_boot=BLOCKED_BY_LOCK_BITS','boot_spm_boot=BLOCKED_BY_LOCK_BITS',
    'boot_lpm_app=ALLOWED_BY_LOCK_BITS','boot_spm_app=ALLOWED_BY_LOCK_BITS','app_read_boot_crc16=B76F'
) -join "`n") + "`nEND_BOOT_ACCESS_DIAGNOSTICS`n"
Assert-DiagnosticFrames ($frame*3); $script:passed++
Reject {Assert-DiagnosticFrames ($frame*2)} 'Two frames remain insufficient'
Reject {Assert-DiagnosticFrames (($frame*3)+[char]0)} 'NUL corruption remains rejected'
Reject {Assert-DiagnosticFrames ($frame.Replace('lfuse=FF',"lfuse=FF`nBOOT_ACCESS_DIAGNOSTICS_V1")*3)} 'Nested frames remain rejected'
Reject {Assert-DiagnosticFrames ($frame.Replace('lfuse=FF',"lfuse=FF`nlfuse=FF")*3)} 'Duplicate fields remain rejected'
Reject {Assert-DiagnosticFrames ($frame.Replace('hfuse=DC','hfuse=DE')*3)} 'Incorrect actual fuse remains rejected'
Write-Output ('PASS: '+$script:passed+' hardware-free serial-read, capture-accounting and strict-frame checks.')
