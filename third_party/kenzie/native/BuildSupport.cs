using System;
using System.IO;
using System.IO.Compression;
using System.Security.Cryptography;
using System.Runtime.InteropServices;
using System.Diagnostics;
using System.Threading;
using System.Net;
using System.Text;
using System.Collections.Generic;

public static class BuildSupport {
    public const string CtrUrl = "https://github.com/3DSGuy/Project_CTR/releases/download/ctrtool-v1.3.0/ctrtool-v1.3.0-win_x64.zip";
    public const string CtrSha = "8031dff3be72d0adb250fae1f969f27627e12a89ebc6dd074a15a75f87ddc949";
    public static string Hash(byte[] bytes) { using(var s=SHA256.Create()) return Hex(s.ComputeHash(bytes)); }
    public static string HashFile(string path) { using(var s=SHA256.Create()) using(var f=File.OpenRead(path)) return Hex(s.ComputeHash(f)); }
    static string Hex(byte[] data) { return BitConverter.ToString(data).Replace("-","").ToLowerInvariant(); }
    public static void ValidateName(string name) {
        if (String.IsNullOrEmpty(name) || name.IndexOf('\\')>=0 || name.IndexOf(':')>=0 || name.StartsWith("/") || Path.IsPathRooted(name)) throw new InvalidDataException("Unsafe package path");
        foreach(string part in name.Split('/')) {
            if (part.Length==0 || part=="." || part==".." || part.EndsWith(".") || part.EndsWith(" ") || part.IndexOfAny(Path.GetInvalidFileNameChars())>=0) throw new InvalidDataException("Unsafe package path");
            string stem=part.Split('.')[0].ToUpperInvariant();
            if (stem=="CON" || stem=="PRN" || stem=="AUX" || stem=="NUL" || stem=="CLOCK$" || (stem.Length==4 && (stem.StartsWith("COM") || stem.StartsWith("LPT")) && stem[3]>='0' && stem[3]<='9')) throw new InvalidDataException("Reserved Windows path");
        }
    }
    public static bool IsWithin(string root,string path) {
        string r=Path.GetFullPath(root).TrimEnd(Path.DirectorySeparatorChar)+Path.DirectorySeparatorChar;
        string p=Path.GetFullPath(path);
        return p.StartsWith(r,StringComparison.OrdinalIgnoreCase) || String.Equals(p.TrimEnd(Path.DirectorySeparatorChar),r.TrimEnd(Path.DirectorySeparatorChar),StringComparison.OrdinalIgnoreCase);
    }
    public static string Safe(string root,string name) {
        ValidateName(name);
        string path=Path.GetFullPath(Path.Combine(root,name.Replace('/',Path.DirectorySeparatorChar)));
        if (!IsWithin(root,path)) throw new InvalidDataException("Path escapes root");
        NoReparse(path);
        return path;
    }
    public static void NoReparse(string path) {
        string p=Path.GetFullPath(path);
        while (!String.IsNullOrEmpty(p)) {
            if ((File.Exists(p)||Directory.Exists(p)) && (File.GetAttributes(p)&FileAttributes.ReparsePoint)!=0) throw new IOException("Reparse-point paths are not supported: "+p);
            p=Path.GetDirectoryName(p);
        }
    }
    public static byte[] ReadLimited(string path) {
        NoReparse(path);
        using(var f=new FileStream(path,FileMode.Open,FileAccess.Read,FileShare.Read)) {
            if(f.Length>NativeCodecs.MaxSize) throw new InvalidDataException("Input exceeds supported size");
            using(var m=new MemoryStream()) { CopyLimited(f,m,NativeCodecs.MaxSize,CancellationToken.None); return m.ToArray(); }
        }
    }
    public static void CopyLimited(Stream input,Stream output,long limit,CancellationToken cancel) {
        byte[] buffer=new byte[65536]; long total=0; int n;
        while((n=input.Read(buffer,0,buffer.Length))>0) { cancel.ThrowIfCancellationRequested(); total+=n; if(total>limit) throw new InvalidDataException("Input exceeds supported size"); output.Write(buffer,0,n); }
    }
    public static void WriteNew(string path,byte[] data) {
        NoReparse(path);
        using(var f=new FileStream(path,FileMode.CreateNew,FileAccess.Write,FileShare.None)) { f.Write(data,0,data.Length); f.Flush(true); }
    }
    [DllImport("kernel32.dll",CharSet=CharSet.Unicode,SetLastError=true)] static extern bool CreateDirectory(string path,IntPtr security);
    public static void CreateExclusiveDirectory(string path) {
        path=Path.GetFullPath(path); NoReparse(path);
        Directory.CreateDirectory(Path.GetDirectoryName(path));
        if(!CreateDirectory(path,IntPtr.Zero)) throw new IOException("Cannot create a new exclusive output directory: "+path+" (Windows error "+Marshal.GetLastWin32Error()+")");
    }
    public static string FetchTool(string url,string sha,string name,string folder,CancellationToken cancel) {
        cancel.ThrowIfCancellationRequested();
        CreateExclusiveDirectory(folder);
        byte[] raw;
        ServicePointManager.SecurityProtocol=SecurityProtocolType.Tls12;
        var req=WebRequest.CreateHttp(url); req.Timeout=60000; req.ReadWriteTimeout=60000;
        try {
            using(cancel.Register(delegate { req.Abort(); })) using(var response=req.GetResponse()) using(var s=response.GetResponseStream()) using(var m=new MemoryStream()) {
                CopyLimited(s,m,32L*1024*1024,cancel); raw=m.ToArray();
            }
        } catch(WebException) { cancel.ThrowIfCancellationRequested(); throw; }
        if(Hash(raw)!=sha) throw new InvalidDataException("Official tool download checksum mismatch");
        using(var m=new MemoryStream(raw,false)) using(var zip=new ZipArchive(m,ZipArchiveMode.Read)) {
            ZipArchiveEntry chosen=null; var seen=new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            foreach(var e in zip.Entries) {
                string entry=e.FullName.TrimEnd('/'); ValidateName(entry);
                if(!seen.Add(entry)) throw new InvalidDataException("Duplicate official tool ZIP entry");
                if(String.Equals(Path.GetFileName(entry),name,StringComparison.OrdinalIgnoreCase) && !e.FullName.EndsWith("/")) {
                    if(chosen!=null) throw new InvalidDataException("Multiple official tool executables"); chosen=e;
                }
            }
            if(chosen==null || chosen.Length>32L*1024*1024) throw new InvalidDataException("Unexpected official tool package");
            string result=Safe(folder,name);
            using(var s=chosen.Open()) using(var outFile=new FileStream(result,FileMode.CreateNew,FileAccess.Write,FileShare.None)) { CopyLimited(s,outFile,32L*1024*1024,cancel); outFile.Flush(true); }
            if(new FileInfo(result).Length!=chosen.Length) throw new InvalidDataException("Truncated official tool");
            return result;
        }
    }
    public static string Quote(string value) {
        var b=new StringBuilder("\""); int slashes=0;
        foreach(char c in value) { if(c=='\\') { slashes++; continue; } if(c=='\"') { b.Append('\\',slashes*2+1); b.Append(c); } else { b.Append('\\',slashes); b.Append(c); } slashes=0; }
        b.Append('\\',slashes*2); b.Append('"'); return b.ToString();
    }
    static void StopOwnedProcess(Process process) {
        try { if(!process.HasExited) process.Kill(); }
        catch(InvalidOperationException) { if(!process.HasExited) throw; }
        catch(System.ComponentModel.Win32Exception) { if(!process.HasExited) throw; }
    }
    public static void RunTool(string exe,string[] args,string cwd,string log,CancellationToken cancel) {
        cancel.ThrowIfCancellationRequested(); NoReparse(exe); NoReparse(cwd); NoReparse(log);
        var quoted=new List<string>(); foreach(string arg in args) quoted.Add(Quote(arg));
        var info=new ProcessStartInfo(Path.GetFullPath(exe),String.Join(" ",quoted.ToArray()));
        info.WorkingDirectory=cwd; info.UseShellExecute=false; info.CreateNoWindow=true; info.RedirectStandardOutput=true; info.RedirectStandardError=true;
        using(var writer=new StreamWriter(new FileStream(log,FileMode.Append,FileAccess.Write,FileShare.Read))) using(var process=new Process()) {
            writer.WriteLine("Command: "+Quote(exe)+" "+info.Arguments); writer.Flush();
            object gate=new object(); Exception logError=null; int pendingLines=0;
            var flushClock=Stopwatch.StartNew();
            process.StartInfo=info;
            DataReceivedEventHandler handler=delegate(object sender,DataReceivedEventArgs e) {
                if(e.Data!=null) lock(gate) {
                    if(logError!=null) return;
                    try {
                        writer.WriteLine(e.Data); pendingLines++;
                        if(pendingLines>=128 || flushClock.ElapsedMilliseconds>=500) {
                            writer.Flush(); pendingLines=0; flushClock.Restart();
                        }
                    } catch(Exception error) { logError=error; }
                }
            };
            process.OutputDataReceived+=handler; process.ErrorDataReceived+=handler;
            process.Start(); process.BeginOutputReadLine(); process.BeginErrorReadLine();
            while(!process.WaitForExit(200)) {
                if(cancel.IsCancellationRequested) { StopOwnedProcess(process); process.WaitForExit(); cancel.ThrowIfCancellationRequested(); }
                lock(gate) if(logError!=null) { StopOwnedProcess(process); break; }
            }
            process.WaitForExit(); cancel.ThrowIfCancellationRequested();
            lock(gate) {
                if(logError==null) {
                    try { writer.Flush(); } catch(Exception error) { logError=error; }
                }
            }
            if(logError!=null) throw new IOException("External-tool logging failed; build stopped safely",logError);
            if(process.ExitCode!=0) throw new IOException("Game tool failed (exit "+process.ExitCode+"). Details: "+log);
        }
    }
}
