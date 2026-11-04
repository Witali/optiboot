#Requires -Version 7.2
# GPL-2.0-or-later. Hardware-free Mini helpers; no serial or programmer access.
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$runner=Join-Path $PSScriptRoot 'test_nano_mini512.ps1'
$tokens=$null; $errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($runner,[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'Runner syntax failure.'}
foreach($name in @('Assert-Bytes','Assert-MiniColdProof','Assert-MiniProbe','Save-MiniProbe','Pad-ApplicationProbe','Read-Page','Write-Page','Verify-Application')) {
    $nodes=@($ast.FindAll({param($node) $node-is [Management.Automation.Language.FunctionDefinitionAst]-and $node.Name-eq $name},$true))
    if($nodes.Count-ne 1){throw ('Missing helper '+$name)}
    . ([ScriptBlock]::Create($nodes[0].Extent.Text))
}
$script:passed=0
function Check($Value,$Expected){if($Value-cne $Expected){throw 'Unexpected helper result.'}; $script:passed++}
function Reject([scriptblock]$Action){$caught=$false;try{& $Action | Out-Null}catch{$caught=$true};if(-not $caught){throw 'Invalid input accepted.'};$script:passed++}
function New-Record([byte]$R2=0,[byte]$R1=0,[byte]$Mcusr=0,[byte]$Wdt=0){return ,[byte[]]@(83,84,65,82,$R2,$R1,$Mcusr,$Wdt)}
Check (Assert-MiniColdProof (New-Record) 3) 'first_invocation_uptime_at_least_1500ms'
Check (Assert-MiniColdProof (New-Record -R2 255) 3) 'first_invocation_uptime_at_least_1500ms'
Reject {Assert-MiniColdProof (New-Record) 2}
Reject {Assert-MiniColdProof (New-Record -R1 1) 3}
Reject {Assert-MiniColdProof (New-Record -Mcusr 1) 3}
Reject {Assert-MiniColdProof (New-Record -Wdt 8) 3}
Reject {Assert-MiniColdProof (New-Record -Wdt 64) 3}
Reject {Assert-MiniColdProof ([byte[]]@(0,0)) 3}
Reject {Assert-MiniColdProof (New-Record) 65536}
$ready=[pscustomobject]@{r1=0;mcusr=0;wdt=0;elapsed_ms=100;bytes_read=100;read_calls=1;reason=255}
Assert-MiniProbe $ready; $script:passed++
$bad=[pscustomobject]@{r1=1;mcusr=0;wdt=0}; Reject {Assert-MiniProbe $bad}
$repoRoot=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../../..'))
$taskDir=Join-Path $repoRoot ('.worktree/nano-mini512-helper-check-'+[Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $taskDir | Out-Null
Save-MiniProbe $ready (Join-Path $taskDir 'probe.json')
$saved=Get-Content (Join-Path $taskDir 'probe.json') -Raw | ConvertFrom-Json
Check ($saved.PSObject.Properties.Name-contains 'reason') $false
Check $saved.reset_reason_available $false
[IO.File]::WriteAllBytes((Join-Path $taskDir 'probe.bin'),[byte[]](0..128))
Pad-ApplicationProbe 'probe.bin' 'pages.bin'
$padded=[IO.File]::ReadAllBytes((Join-Path $taskDir 'pages.bin'))
Check $padded.Length 256
Assert-Bytes ([byte[]]$padded[0..128]) ([byte[]](0..128)) 'Probe prefix'; $script:passed++
Check (@($padded[129..255] | Where-Object {$_-ne 255}).Count) 0
[IO.File]::WriteAllBytes((Join-Path $taskDir 'empty.bin'),[byte[]]::new(0))
Reject {Pad-ApplicationProbe 'empty.bin' 'empty-pages.bin'}
$script:sent=@()
function Load-Address([int]$Address){$script:lastAddress=$Address}
function Send-Expect([byte[]]$Packet,[byte[]]$Expected,[string]$Name){$script:sent+=,$Packet}
Write-Page 0x7D80 ([byte[]]::new(128))
Check $script:lastAddress 0x7D80
Check $script:sent[-1].Length 133
Reject {Write-Page 0x7E00 ([byte[]]::new(128))}
Reject {Write-Page 2 ([byte[]]::new(128))}
Reject {Write-Page 0 ([byte[]]::new(2))}
Reject {Write-Page -128 ([byte[]]::new(128))}
Read-Page 0x7D80 128 ([byte[]]::new(128))
Check $script:lastAddress 0x7D80
Check $script:sent[-1][2] 128
Read-Page 0 1 ([byte[]]@(0)); $script:passed++
Reject {Read-Page 0 0 ([byte[]]::new(0))}
Reject {Read-Page 0 129 ([byte[]]::new(129))}
Reject {Read-Page 0x7E00 128 ([byte[]]::new(128))}
Reject {Read-Page 2 128 ([byte[]]::new(128))}
$script:avrCalls=0
function Invoke-Avr([string[]]$NativeArgs){$script:avrCalls++;$script:lastAvrArgs=$NativeArgs}
[IO.File]::WriteAllBytes((Join-Path $taskDir 'application.bin'),[byte[]]::new(32256))
Verify-Application 'application.bin'
Check ($script:lastAvrArgs -join ' ') '-n -D -A -U flash:v:application.bin:r -U signature:v:before-signature.bin:r'
[IO.File]::WriteAllBytes((Join-Path $taskDir 'whole-flash.bin'),[byte[]]::new(32768))
Reject {Verify-Application 'whole-flash.bin'}
Reject {Verify-Application 'probe.bin'}
Check $script:avrCalls 1
Write-Output ('PASS: '+$script:passed+' hardware-free Mini USB helper checks.')
