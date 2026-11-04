// GPL-2.0-or-later. Run native tools with bounded waits and USB error detection.
using System;
using System.Collections.Concurrent;
using System.Diagnostics;
using System.IO;
using System.Threading;

public static class AvrProcessRunner
{
    private static void DrainOutput(ConcurrentQueue<Tuple<bool, string>> output, int maximumLines)
    {
        Tuple<bool, string> line;
        for (int count = 0; count < maximumLines && output.TryDequeue(out line); count++)
        {
            if (line.Item1) Console.Error.WriteLine(line.Item2);
            else Console.WriteLine(line.Item2);
        }
    }

    public static int Run(string executable, string directory, string[] arguments)
    {
        using (var process = new Process())
        {
            process.StartInfo = new ProcessStartInfo(executable) {
                WorkingDirectory = directory,
                UseShellExecute = false,
                CreateNoWindow = true,
                RedirectStandardOutput = true,
                RedirectStandardError = true
            };
            foreach (string argument in arguments) process.StartInfo.ArgumentList.Add(argument);
            int transportError = 0;
            var output = new ConcurrentQueue<Tuple<bool, string>>();
            // Console/PowerShell host writers can require the calling thread.
            // Reader callbacks only queue data and flag transport failures.
            process.OutputDataReceived += (sender, e) => {
                if (e.Data != null) output.Enqueue(Tuple.Create(false, e.Data));
            };
            process.ErrorDataReceived += (sender, e) => {
                if (e.Data == null) return;
                if (e.Data.Contains("OS error:") ||
                    e.Data.Contains("cannot open USB device") ||
                    e.Data.Contains("cannot find USB device") ||
                    e.Data.Contains("wrong reading bytes") ||
                    e.Data.Contains("wrong count at writing") ||
                    e.Data.Contains("wrong response size"))
                    Interlocked.Exchange(ref transportError, 1);
                output.Enqueue(Tuple.Create(true, e.Data));
            };
            var watch = Stopwatch.StartNew();
            process.Start();
            process.BeginOutputReadLine();
            process.BeginErrorReadLine();
            while (!process.WaitForExit(100))
            {
                // Limit each batch so continuous output cannot starve checks.
                DrainOutput(output, 256);
                if (Volatile.Read(ref transportError) != 0 || watch.Elapsed.TotalSeconds > 180)
                {
                    try { process.Kill(); }
                    catch (InvalidOperationException) { if (!process.HasExited) throw; }
                    process.WaitForExit();
                    DrainOutput(output, int.MaxValue);
                    throw new IOException("AVRDUDE was stopped after a USB transport error or timeout.");
                }
            }
            process.WaitForExit();
            DrainOutput(output, int.MaxValue);
            if (Volatile.Read(ref transportError) != 0)
                throw new IOException("AVRDUDE reported a USB transport error.");
            return process.ExitCode;
        }
    }
}
