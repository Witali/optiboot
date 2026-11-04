#Requires -Version 7.2
# Hardware-free checks: extract only pure helpers, never execute the runner.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$tokens = $null
$parseErrors = $null
$runner = Join-Path $PSScriptRoot 'test_nano_usb.ps1'
$ast = [Management.Automation.Language.Parser]::ParseFile($runner,[ref]$tokens,[ref]$parseErrors)
if ($parseErrors.Count -ne 0) { throw 'Runner contains PowerShell syntax errors.' }
foreach ($name in @('Get-ColdStartProof','Get-NanoEditionSettings')) {
    $helper = @($ast.FindAll({param($node)
        $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name
    },$true))
    if ($helper.Count -ne 1) { throw ('Expected exactly one pure helper named '+$name+'.') }
    . ([ScriptBlock]::Create($helper[0].Extent.Text))
}
$passed = 0

foreach ($entry in @(@('basic',512,0x7E00,32256,0x7D80,'DE',$false,$false,$true),
                     @('middle',512,0x7E00,32256,0x7D80,'DE',$true,$true,$false),
                     @('full',1024,0x7C00,31744,0x7B80,'DC',$true,$true,$true))) {
    $settings = Get-NanoEditionSettings $entry[0]
    foreach ($field in @(@('BootBytes',1),@('BootStart',2),@('ApplicationBytes',3),@('ScratchAddress',4),
                         @('HighFuse',5),@('RequiresIsp',6),@('PreservesResetFlags',7),@('HasFuseReads',8))) {
        if ($settings.($field[0]) -ne $entry[$field[1]]) { throw ($entry[0]+': incorrect '+$field[0]+'.') }
        $passed++
    }
    if ($settings.ApplicationBytes+$settings.BootBytes -ne 32768 -or
        $settings.ScratchAddress+128 -ne $settings.BootStart -or $settings.BootHash -notmatch '^[0-9a-f]{64}$') {
        throw ($entry[0]+': invalid memory layout or pinned hash.')
    }
    $passed++
}

function New-Entry([byte]$Cause=5,[byte]$R1=0,[byte]$Mcusr=5,[byte]$Wdt=0) {
    return ,[byte[]]@(0x53,0x54,0x41,0x52,$Cause,$R1,$Mcusr,$Wdt)
}
function Expect-Proof([string]$Name,[byte[]]$Record,[int]$Ticks,[string]$Edition,[string]$Expected) {
    $actual = Get-ColdStartProof $Record $Ticks $Edition
    if ($actual -ne $Expected) { throw ($Name+': incorrect proof kind.') }
    $script:passed++
}
function Expect-Rejection([string]$Name,[byte[]]$Record,[int]$Ticks,[string]$Edition) {
    $rejected = $false
    try { Get-ColdStartProof $Record $Ticks $Edition | Out-Null } catch { $rejected = $true }
    if (-not $rejected) { throw ($Name+': invalid evidence was accepted.') }
    $script:passed++
}

$powerProof = 'power_on_entry_and_at_least_500ms_execution'
$uptimeProof = 'autonomous_uptime_at_least_1500ms'
Expect-Proof 'Observed Middle PORF/BORF entry and one tick' (New-Entry) 1 middle $powerProof
Expect-Proof 'Middle PORF entry and two ticks' (New-Entry -Cause 1 -Mcusr 1) 2 middle $powerProof
Expect-Proof 'Middle generic three-tick proof unchanged' (New-Entry -Cause 2 -Mcusr 2) 3 middle $uptimeProof
Expect-Proof 'Basic three-tick proof unchanged' (New-Entry -Mcusr 0) 3 basic $uptimeProof
Expect-Rejection 'Middle zero ticks' (New-Entry) 0 middle
Expect-Rejection 'Middle EXTRF-only low-tick entry' (New-Entry -Cause 2 -Mcusr 2) 1 middle
Expect-Rejection 'Middle WDRF-only low-tick entry' (New-Entry -Cause 8 -Mcusr 8) 1 middle
Expect-Rejection 'Middle BORF-only low-tick entry' (New-Entry -Cause 4 -Mcusr 4) 1 middle
Expect-Rejection 'Middle PORF plus EXTRF low-tick entry' (New-Entry -Cause 3 -Mcusr 3) 1 middle
Expect-Rejection 'Middle PORF plus WDRF low-tick entry' (New-Entry -Cause 9 -Mcusr 9) 1 middle
Expect-Rejection 'Nonzero r1' (New-Entry -R1 1) 3 middle
Expect-Rejection 'Watchdog enabled' (New-Entry -Wdt 8) 3 middle
Expect-Rejection 'Watchdog interrupt enabled' (New-Entry -Wdt 0x40) 3 middle
Expect-Rejection 'Incorrect MCUSR parity' (New-Entry -Mcusr 0) 3 middle
Expect-Rejection 'Basic low-tick power entry' (New-Entry -Mcusr 0) 1 basic
$badTag = New-Entry; $badTag[0] = 0
Expect-Rejection 'Missing STAR tag' $badTag 3 middle
Expect-Rejection 'Truncated record' ([byte[]]@(0x53,0x54)) 3 middle
Expect-Rejection 'No reset cause' (New-Entry -Cause 0 -Mcusr 0) 3 middle
Expect-Proof 'Full PORF/BORF entry and one tick' (New-Entry) 1 full $powerProof
Expect-Proof 'Full PORF entry and two ticks' (New-Entry -Cause 1 -Mcusr 1) 2 full $powerProof
Expect-Proof 'Full generic three-tick proof' (New-Entry -Cause 0x0A -Mcusr 2) 3 full $uptimeProof
Expect-Rejection 'Full zero ticks' (New-Entry) 0 full
Expect-Rejection 'Full EXTRF-only low-tick entry' (New-Entry -Cause 2 -Mcusr 2) 1 full
Expect-Rejection 'Full WDRF-only low-tick entry' (New-Entry -Cause 8 -Mcusr 8) 1 full
Expect-Rejection 'Full BORF-only low-tick entry' (New-Entry -Cause 4 -Mcusr 4) 1 full
Expect-Rejection 'Full PORF plus EXTRF low-tick entry' (New-Entry -Cause 3 -Mcusr 3) 1 full
Expect-Rejection 'Full PORF plus WDRF low-tick entry' (New-Entry -Cause 9 -Mcusr 9) 1 full
Expect-Rejection 'Full nonzero r1' (New-Entry -R1 1) 3 full
Expect-Rejection 'Full watchdog enabled' (New-Entry -Wdt 8) 3 full
Expect-Rejection 'Full watchdog interrupt enabled' (New-Entry -Wdt 0x40) 3 full
Expect-Rejection 'Full incorrect MCUSR parity' (New-Entry -Mcusr 0) 3 full
Expect-Rejection 'Full missing STAR tag' $badTag 3 full
Expect-Rejection 'Full truncated record' ([byte[]]@(0x53,0x54)) 3 full
Expect-Rejection 'Full no reset cause' (New-Entry -Cause 0 -Mcusr 0) 3 full
Write-Output ('PASS: '+$passed+' hardware-free edition-configuration and cold-start evidence checks.')
