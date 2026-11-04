#Requires -Version 7.2
# GPL-2.0-or-later. Synthetic ISP state machine only; no device access.
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$sourcePath=Join-Path $PSScriptRoot 'finish_nano_mini512_isp.ps1'
$tokens=$null; $errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($sourcePath,[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'Finisher syntax failure.'}
foreach($name in @('Assert-SameBytes','Assert-MiniIdentity','Get-EepromDifferenceCounts','Get-UsbQualificationFailures','Read-StateIdentity')){
    $nodes=@($ast.FindAll({param($node) $node-is [Management.Automation.Language.FunctionDefinitionAst]-and $node.Name-eq $name},$true))
    if($nodes.Count-ne 1){throw ('Missing helper '+$name)}
    . ([ScriptBlock]::Create($nodes[0].Extent.Text))
}
$assignment=@($ast.EndBlock.Statements | Where-Object {
    $_-is [Management.Automation.Language.AssignmentStatementAst]-and $_.Left.Extent.Text-eq '$result'
})
$tryStatement=@($ast.EndBlock.Statements | Where-Object {$_-is [Management.Automation.Language.TryStatementAst]})
if($assignment.Count-ne 1-or $tryStatement.Count-ne 1){throw 'Unexpected finisher structure.'}
$resultInitializer=[ScriptBlock]::Create($assignment[0].Extent.Text)
$source=[IO.File]::ReadAllText($sourcePath)
$execution=[ScriptBlock]::Create($source.Substring($tryStatement[0].Extent.StartOffset))
$repoRoot=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../../..'))
$privateRoot=Join-Path $repoRoot ('.worktree/mini512-isp-check-'+[Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $privateRoot | Out-Null
$script:passed=0
function Check($Actual,$Expected,[string]$Name){
    if($Actual-cne $Expected){throw ($Name+': unexpected state.')};$script:passed++
}
function Read-IspState([string]$Prefix){
    $script:readCalls++
    $flash=[byte[]]$script:virtualFlash.Clone()
    $values=$script:virtualIdentity.Clone()
    if($Prefix-eq 'final'-and $script:finalIdentityFault){$values.hfuse='DC'}
    if($Prefix-eq 'final'-and $script:finalFlashFault){$flash[0]=$flash[0]-bxor 1}
    [IO.File]::WriteAllBytes((Join-Path $taskDir ($Prefix+'-flash.bin')),$flash)
    [IO.File]::WriteAllBytes((Join-Path $taskDir ($Prefix+'-eeprom.bin')),$script:virtualEeprom)
    foreach($name in @('signature','lfuse','hfuse','efuse','lock')){
        [IO.File]::WriteAllBytes((Join-Path $taskDir ($Prefix+'-'+$name+'.bin')),[Convert]::FromHexString($values[$name]))
    }
}
function Invoke-Isp([string]$Label,[string[]]$Arguments){
    if($Label-ne 'restore-original-eeprom'-or ($Arguments-join ' ')-ne '-D -A -U eeprom:w:original-eeprom.bin:r'){
        throw 'Synthetic finisher attempted an unexpected write operation.'
    }
    $script:writeCalls++
    $script:virtualEeprom=[byte[]]$originalEeprom.Clone()
}
function Test-Case([string]$Name,[bool]$Write,[scriptblock]$Change,[bool]$Throws,[int]$ExpectedWrites,[bool]$Restored,[bool]$Qualified){
    $taskDir=Join-Path $privateRoot $Name
    New-Item -ItemType Directory -Path $taskDir | Out-Null
    $baselineFlash=[byte[]]::new(32768)
    for($index=0x7E00;$index-lt 32768;$index++){$baselineFlash[$index]=0xA5}
    $boot=[byte[]]$baselineFlash[0x7E00..0x7FFF]
    $expectedBootHash=[Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($boot)).ToLowerInvariant()
    $originalEeprom=[byte[]]::new(1024)
    for($index=0;$index-lt 1024;$index++){$originalEeprom[$index]=($index*17)-band 255}
    $script:virtualFlash=[byte[]]$baselineFlash.Clone()
    $script:virtualEeprom=[byte[]]$originalEeprom.Clone()
    $script:virtualEeprom[1014]=$script:virtualEeprom[1014]-bxor 1
    $script:virtualIdentity=@{signature='1E9516';lfuse='FF';hfuse='DE';efuse='FD';lock='CF'}
    $script:writeCalls=0;$script:readCalls=0;$script:finalIdentityFault=$false;$script:finalFlashFault=$false
    $usb=[pscustomobject]@{failure=$null;application_restored_and_verified=$true;runtime_configuration_verified=$true;
        watchdog_cycles=50;dtr_cycles=20;checks=@([pscustomobject]@{result='PASS'});
        cold_start_requested=$true;cold_start_passed=$true}
    $Run=$Write
    & $Change
    . $resultInitializer
    $caught=$false
    $previous=Get-Location
    try{
        Set-Location -LiteralPath $taskDir
        try{. $execution | Out-Null}catch{$caught=$true}
    }finally{Set-Location -LiteralPath $previous}
    Check $caught $Throws ($Name+' exception')
    Check $script:writeCalls $ExpectedWrites ($Name+' EEPROM write count')
    Check $result.complete_device_restoration_verified $Restored ($Name+' restoration flag')
    Check $result.hardware_qualification_passed $Qualified ($Name+' qualification flag')
    Check $result.final_isp_required (-not $Restored) ($Name+' remaining ISP work')
    Check $result.usb_failure_preserved ($null-ne $usb.failure) ($Name+' retained USB failure')
    Check (Test-Path -LiteralPath (Join-Path $taskDir 'final-isp-result.json')) $true ($Name+' saved result')
    if($Restored){Assert-SameBytes $script:virtualEeprom $originalEeprom ($Name+' original EEPROM');$script:passed++}
}
Test-Case 'read-only' $false {} $false 0 $false $false
Test-Case 'valid-restore' $true {} $false 1 $true $true
Test-Case 'usb-failure' $true {$usb.failure='Synthetic USB failure'} $true 1 $true $false
Test-Case 'unexpected-eeprom' $true {$script:virtualEeprom[0]=$script:virtualEeprom[0]-bxor 1} $true 1 $true $false
Test-Case 'application-differs' $true {$script:virtualFlash[0]=1} $true 0 $false $false
Test-Case 'wrong-boot' $true {$script:virtualFlash[0x7E00]=0} $true 0 $false $false
Test-Case 'wrong-fuse' $true {$script:virtualIdentity.hfuse='DC'} $true 0 $false $false
Test-Case 'wrong-signature' $true {$script:virtualIdentity.signature='1E950F'} $true 0 $false $false
Test-Case 'short-flash' $true {$script:virtualFlash=[byte[]]::new(32767)} $true 0 $false $false
Test-Case 'short-eeprom' $true {$script:virtualEeprom=[byte[]]::new(1023)} $true 0 $false $false
Test-Case 'usb-app-flag-missing' $true {$usb.application_restored_and_verified=$false} $true 1 $true $false
Test-Case 'reset-stress-incomplete' $true {$usb.watchdog_cycles=49} $true 1 $true $false
Test-Case 'cold-failure' $true {$usb.cold_start_passed=$false} $true 1 $true $false
Test-Case 'usb-check-failure' $true {$usb.checks[0].result='FAIL'} $true 1 $true $false
Test-Case 'final-fuse-fault' $true {$script:finalIdentityFault=$true} $true 1 $false $false
Test-Case 'final-flash-fault' $true {$script:finalFlashFault=$true} $true 1 $false $false
Write-Output ('PASS: '+$script:passed+' synthetic final-ISP guard, restoration and retained-failure checks.')
