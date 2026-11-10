#Requires -Version 7.2
# GPL-2.0-or-later. Synthetic child processes only; no hardware access.
[CmdletBinding()]
param([string]$RunnerPath = (Join-Path $PSScriptRoot 'AvrProcessRunner.cs'))

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../../..'))
$privateDir = Join-Path $repoRoot ('.worktree/process-runner-check-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $privateDir | Out-Null
$RunnerPath = [IO.Path]::GetFullPath($RunnerPath)
$pwshPath = (Get-Process -Id $PID).Path

$childPath = Join-Path $privateDir 'fake-child.ps1'
@'
param([string]$Mode)
if ($Mode -eq 'transport') {
    [Console]::Error.WriteLine('OS error: synthetic transport failure')
    [Threading.Thread]::Sleep(2400)
    exit 0
}
for ($index=0; $index-lt 2048; $index++) {
    [Console]::Out.WriteLine(('OUT:{0:D4}:' -f $index) + ('x' * 128))
    [Console]::Error.WriteLine(('ERR:{0:D4}:' -f $index) + ('y' * 128))
}
exit 7
'@ | Set-Content -LiteralPath $childPath -Encoding utf8

$workerPath = Join-Path $privateDir 'pipeline-worker.ps1'
@'
param([string]$Runner,[string]$Pwsh,[string]$Child,[string]$Directory,[string]$Mode)
$ErrorActionPreference='Stop'
Add-Type -LiteralPath $Runner
if($Mode-eq 'thread-affinity') {
    Add-Type 'using System; using System.IO; using System.Text; using System.Threading; public sealed class ThreadCheckingWriter : TextWriter { private readonly TextWriter inner; private readonly int owner = Thread.CurrentThread.ManagedThreadId; public static int WrongThreadWrites; public ThreadCheckingWriter(TextWriter writer) { inner=writer; } public override Encoding Encoding { get { return inner.Encoding; } } public override void WriteLine(string value) { if(Thread.CurrentThread.ManagedThreadId!=owner) Interlocked.Increment(ref WrongThreadWrites); inner.WriteLine(value); } }'
    [Console]::SetOut([ThreadCheckingWriter]::new([Console]::Out))
    [Console]::SetError([ThreadCheckingWriter]::new([Console]::Error))
}
& {
    $watch=[Diagnostics.Stopwatch]::StartNew()
    if($Mode -eq 'transport') {
        $caught=$false
        try { [AvrProcessRunner]::Run($Pwsh,$Directory,[string[]]@('-NoProfile','-File',$Child,$Mode)) | Out-Null }
        catch {
            if($_.Exception.ToString() -notmatch 'USB transport error'){throw}
            $caught=$true
        }
        if(-not $caught -or $watch.ElapsedMilliseconds-ge 1800){throw 'Transport error was not stopped promptly.'}
    } else {
        $code=[AvrProcessRunner]::Run($Pwsh,$Directory,[string[]]@('-NoProfile','-File',$Child,$Mode))
        if($code-ne 7){throw 'Child exit code was not preserved.'}
        if($Mode-eq 'thread-affinity' -and [ThreadCheckingWriter]::WrongThreadWrites-ne 0) {
            throw 'Console output was written from an asynchronous callback instead of the calling thread.'
        }
    }
    'PIPELINE_COMPLETED'
} 2>&1 | Tee-Object -FilePath (Join-Path $Directory ($Mode+'.log'))
[IO.File]::WriteAllText((Join-Path $Directory ($Mode+'.completed')),'PASS')
'@ | Set-Content -LiteralPath $workerPath -Encoding utf8

foreach($mode in @('flood','thread-affinity','transport')) {
    $process = [Diagnostics.Process]::new()
    try {
        $process.StartInfo = [Diagnostics.ProcessStartInfo]::new($pwshPath)
        $process.StartInfo.UseShellExecute = $false
        $process.StartInfo.CreateNoWindow = $true
        $process.StartInfo.RedirectStandardOutput = $true
        $process.StartInfo.RedirectStandardError = $true
        foreach($argument in @('-NoProfile','-File',$workerPath,$RunnerPath,$pwshPath,$childPath,$privateDir,$mode)) {
            $process.StartInfo.ArgumentList.Add($argument)
        }
        [void]$process.Start()
        $stdout = $process.StandardOutput.ReadToEndAsync()
        $stderr = $process.StandardError.ReadToEndAsync()
        if(-not $process.WaitForExit(8000)) {
            $process.Kill($true)
            [void]$process.WaitForExit(1000)
            throw ($mode+': merged-output pipeline exceeded the eight-second bound.')
        }
        $output = $stdout.GetAwaiter().GetResult() + $stderr.GetAwaiter().GetResult()
        if($process.ExitCode-ne 0 -or -not (Test-Path -LiteralPath (Join-Path $privateDir ($mode+'.completed')))) {
            throw ($mode+': synthetic pipeline failed. Private output: '+$privateDir)
        }
        $log=[IO.File]::ReadAllText((Join-Path $privateDir ($mode+'.log')))
        if(-not $log.Contains('PIPELINE_COMPLETED')) {throw ($mode+': Tee-Object did not complete.')}
        if($mode-ne 'transport') {
            foreach($prefix in @('OUT','ERR')) {
                if([regex]::Matches($output,($prefix+':\d{4}:')).Count-ne 2048) {
                    throw ($mode+': child output was lost or duplicated.')
                }
            }
        }
        Write-Output ('PASS '+$mode+' through 2>&1 | Tee-Object')
    } finally { $process.Dispose() }
}
Write-Output 'PASS: synthetic merged-output, caller-thread console writes, complete stream capture, exit-code and prompt transport-stop checks.'
