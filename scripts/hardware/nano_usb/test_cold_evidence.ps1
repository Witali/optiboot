#Requires -Version 7.2
# Hardware-free checks: extract only the pure helper, never execute the runner.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$tokens = $null
$parseErrors = $null
$runner = Join-Path $PSScriptRoot 'test_nano_usb.ps1'
$ast = [Management.Automation.Language.Parser]::ParseFile($runner,[ref]$tokens,[ref]$parseErrors)
if ($parseErrors.Count -ne 0) { throw 'Runner contains PowerShell syntax errors.' }
$helper = @($ast.FindAll({param($node)
    $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Get-ColdStartProof'
},$true))
if ($helper.Count -ne 1) { throw 'Expected exactly one pure cold-start evidence helper.' }
. ([ScriptBlock]::Create($helper[0].Extent.Text))
$passed = 0

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
Write-Output ('PASS: '+$passed+' hardware-free cold-start evidence checks.')
