// DQXI project code, MIT. This file is not copied from the Kenzie upstream.
using System;
using System.IO;
using System.Collections.Generic;
using System.Security.Cryptography;
using System.Threading;

public sealed class CiaContent {
    public uint Id;
    public ushort Index;
    public ulong Size;
    public string Sha256;
    public string Path;
}
public sealed class CiaSource {
    public string CiaPath;
    public string Root;
    public string GamePath;
    public ushort TitleVersion;
    public int RomFsFileCount;
    public long RomFsTotalBytes;
    public CiaContent[] Contents;
}
public static class CiaSupport {
    public const ulong TitleId = 0x0004000000199200UL;
    static string Hex(byte[] value) { return BitConverter.ToString(value).Replace("-", "").ToLowerInvariant(); }
    static uint Be32(byte[] b, int p) { return ((uint)b[p]<<24)|((uint)b[p+1]<<16)|((uint)b[p+2]<<8)|b[p+3]; }
    static ushort Be16(byte[] b, int p) { return (ushort)((b[p]<<8)|b[p+1]); }
    static ulong Be64(byte[] b, int p) { return ((ulong)Be32(b,p)<<32)|Be32(b,p+4); }
    public static string[] CheckPcInstallation(string root, string[] files, string[] directories) {
        root=System.IO.Path.GetFullPath(root); BuildSupport.NoReparse(root);
        var missing=new List<string>();
        foreach(string relative in directories) {
            string path=BuildSupport.Safe(root,relative);
            if(!Directory.Exists(path)) missing.Add(relative+"/");
        }
        foreach(string relative in files) {
            string path=BuildSupport.Safe(root,relative);
            if(!File.Exists(path) || new FileInfo(path).Length==0) missing.Add(relative);
        }
        return missing.ToArray();
    }
    static byte[] OriginalTmd(string path, CancellationToken cancel) {
        BuildSupport.NoReparse(path);
        if(!String.Equals(System.IO.Path.GetExtension(path), ".cia", StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("Choose the original .CIA file.");
        using(var file = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read)) {
            cancel.ThrowIfCancellationRequested();
            var h=new byte[32];
            if(file.Read(h,0,h.Length)!=h.Length) throw new InvalidDataException("Truncated CIA header.");
            uint headerSize=Le32(h,0), certSize=Le32(h,8), ticketSize=Le32(h,12), tmdSize=Le32(h,16);
            if(headerSize<0x2020 || headerSize>1024*1024 || tmdSize<4 || tmdSize>4*1024*1024)
                throw new InvalidDataException("Unsupported CIA header or TMD bounds.");
            long at=Align64(Align64(Align64(headerSize)+certSize)+ticketSize);
            if(at>file.Length-tmdSize) throw new InvalidDataException("CIA TMD lies outside the file.");
            file.Position=at;var tmd=new byte[tmdSize];int done=0;
            while(done<tmd.Length){int n=file.Read(tmd,done,tmd.Length-done);if(n==0)throw new InvalidDataException("Truncated CIA TMD.");done+=n;}
            return tmd;
        }
    }
    public static string ValidateOriginal(string path, CancellationToken cancel) {
        ParseTmd(OriginalTmd(path,cancel),path+".content");
        return "0004000000199200";
    }
    static long Align64(long value) { return (value+63)&~63L; }
    // TMD defines which content indices/IDs exist, their plaintext sizes and hashes.
    public static CiaSource ReadTmd(string tmdPath, string contentPrefix) {
        BuildSupport.NoReparse(tmdPath);
        byte[] b = File.ReadAllBytes(tmdPath);
        return ParseTmd(b,contentPrefix);
    }
    static CiaSource ParseTmd(byte[] b, string contentPrefix) {
        if(b.Length < 4 || b.Length > 4*1024*1024) throw new InvalidDataException("Invalid TMD length.");
        uint signature = Be32(b,0); int body;
        switch(signature) {
            case 0x00010000: case 0x00010003: body=0x240; break;
            case 0x00010001: case 0x00010004: body=0x140; break;
            case 0x00010002: case 0x00010005: body=0x80; break;
            default: throw new InvalidDataException("Unsupported TMD signature type.");
        }
        if(b.Length < body+0x9c4 || Be64(b,body+0x4c) != TitleId) throw new InvalidDataException("The CIA TMD is not DQXI Japan, title 0004000000199200.");
        int count = Be16(b,body+0x9e);
        if(count == 0 || count > 256 || b.Length != body+0x9c4+count*0x30)
            throw new InvalidDataException("Unsupported or truncated CIA content table.");
        var rows = new List<CiaContent>(); var seen = new HashSet<ushort>(); bool game=false;
        for(int i=0;i<count;i++) {
            int at=body+0x9c4+i*0x30; ushort index=Be16(b,at+4);
            if(!seen.Add(index)) throw new InvalidDataException("Duplicate CIA content index.");
            var digest=new byte[32]; Buffer.BlockCopy(b,at+16,digest,0,32);
            var row = new CiaContent { Id=Be32(b,at), Index=index, Size=Be64(b,at+8), Sha256=Hex(digest) };
            row.Path=contentPrefix+"."+index.ToString("x4")+"."+row.Id.ToString("x8");
            BuildSupport.NoReparse(row.Path); rows.Add(row); game |= index==0;
        }
        if(!game) throw new InvalidDataException("CIA has no content zero.");
        return new CiaSource { TitleVersion=Be16(b,body+0x9c), Contents=rows.ToArray() };
    }
    public static void VerifyContentFiles(CiaSource source) {
        foreach(var row in source.Contents) {
            BuildSupport.NoReparse(row.Path);
            if(!File.Exists(row.Path) || (ulong)new FileInfo(row.Path).Length != row.Size || BuildSupport.HashFile(row.Path) != row.Sha256)
                throw new InvalidDataException("CIA content readback differs from TMD: " + row.Index);
        }
    }
    public static void VerifyContentSizes(CiaSource source) {
        foreach(var row in source.Contents) {
            BuildSupport.NoReparse(row.Path);
            if(!File.Exists(row.Path) || (ulong)new FileInfo(row.Path).Length!=row.Size)
                throw new InvalidDataException("CIA content size differs from TMD: "+row.Index);
        }
    }
    static void ExtractRomfsDirectory(string tool, string romfsBin, string destination, string root, string log, CancellationToken cancel, out int fileCount, out long totalBytes) {
        fileCount=0; totalBytes=0;
        if(String.IsNullOrEmpty(tool)) throw new InvalidDataException("3dstool is required to extract the original ROMFS directory.");
        BuildSupport.RunTool(tool,new string[]{"-x","-t","romfs","-f",romfsBin,"--romfs-dir",destination},root,log,cancel);
        CountRomfsDirectory(destination,cancel,out fileCount,out totalBytes);
        File.AppendAllText(log,"ROMFS extraction completed: "+fileCount+" files, "+totalBytes+" bytes.\n");
    }
    static void CountRomfsDirectory(string destination, CancellationToken cancel, out int fileCount, out long totalBytes) {
        fileCount=0;totalBytes=0;
        BuildSupport.NoReparse(destination);
        if(!Directory.Exists(destination)) throw new InvalidDataException("3dstool did not create the ROMFS directory.");
        var pending=new Stack<string>(); pending.Push(destination);
        while(pending.Count>0) {
            cancel.ThrowIfCancellationRequested(); string current=pending.Pop();
            foreach(FileSystemInfo entry in new DirectoryInfo(current).EnumerateFileSystemInfos()) {
                // Every parent directory was checked before it entered the
                // stack. Check each child once and enumerate each folder once.
                FileAttributes attributes=entry.Attributes;
                if((attributes&FileAttributes.ReparsePoint)!=0) throw new IOException("Linked ROMFS entry is not permitted: "+entry.FullName);
                if((attributes&FileAttributes.Directory)!=0) {
                    pending.Push(entry.FullName);
                } else {
                    long length=((FileInfo)entry).Length;
                    checked { fileCount++; totalBytes+=length; }
                }
            }
        }
        if(fileCount==0 || totalBytes==0) throw new InvalidDataException("3dstool produced an empty ROMFS directory.");
    }
    public static CiaSource ReuseExtracted(string cia, string root, CancellationToken cancel) {
        cia=System.IO.Path.GetFullPath(cia);root=System.IO.Path.GetFullPath(root);
        BuildSupport.NoReparse(root);
        string tmd=System.IO.Path.Combine(root,"source.tmd");
        BuildSupport.NoReparse(tmd);
        byte[] originalTmd=OriginalTmd(cia,cancel),cachedTmd=File.ReadAllBytes(tmd);
        if(originalTmd.Length!=cachedTmd.Length)throw new InvalidDataException("Prepared extraction belongs to a different CIA.");
        for(int i=0;i<originalTmd.Length;i++)if(originalTmd[i]!=cachedTmd[i])throw new InvalidDataException("Prepared extraction TMD differs from the selected CIA.");
        CiaSource source=ReadTmd(tmd,System.IO.Path.Combine(root,"content"));source.CiaPath=cia;source.Root=root;
        foreach(var row in source.Contents) {
            string decoded=System.IO.Path.Combine(root,"decrypted-content."+row.Index.ToString("x4")+"."+row.Id.ToString("x8")+".cxi");
            BuildSupport.NoReparse(decoded);
            if(File.Exists(decoded))row.Path=decoded;
            if(!File.Exists(row.Path))throw new FileNotFoundException("Prepared NCCH images were released by an earlier build.",row.Path);
            if(row.Index==0)source.GamePath=row.Path;
        }
        VerifyContentSizes(source);
        RomBuilder.ValidateInputGame(source.GamePath);
        RomBuilder.ValidateExtractedGameParts(source.GamePath,root);
        RomBuilder.ValidatePatchProfile(System.IO.Path.Combine(root,"exefs","code.bin"),System.IO.Path.Combine(root,"exheader.bin"));
        CountRomfsDirectory(System.IO.Path.Combine(root,"romfs"),cancel,out source.RomFsFileCount,out source.RomFsTotalBytes);
        return source;
    }
    public static CiaSource ExtractOriginal(string cia, string root, string ctrtool, CancellationToken cancel) {
        return ExtractOriginal(cia,root,ctrtool,null,cancel);
    }
    public static CiaSource ExtractOriginal(string cia, string root, string ctrtool, string threeDstool, CancellationToken cancel) {
        return ExtractOriginal(cia,root,ctrtool,threeDstool,null,cancel);
    }
    public static void WriteTitleSeedDatabase(string extKeys, string destination) {
        BuildSupport.NoReparse(extKeys);BuildSupport.NoReparse(destination);
        if(new FileInfo(extKeys).Length>1024*1024)throw new InvalidDataException("Unexpected decryption companion size.");
        byte[] seed=null;
        foreach(string line in File.ReadAllLines(extKeys)) {
            string[] fields=line.Split(new char[]{' ','\t'},StringSplitOptions.RemoveEmptyEntries);
            if(fields.Length!=2 || !String.Equals(fields[0],"0004000000199200",StringComparison.OrdinalIgnoreCase))continue;
            if(seed!=null || fields[1].Length!=32)throw new InvalidDataException("Invalid DQXI decryption companion entry.");
            seed=new byte[16];
            for(int i=0;i<16;i++) {
                byte value;
                if(!Byte.TryParse(fields[1].Substring(i*2,2),System.Globalization.NumberStyles.HexNumber,System.Globalization.CultureInfo.InvariantCulture,out value))
                    throw new InvalidDataException("Invalid DQXI decryption companion entry.");
                seed[i]=value;
            }
        }
        if(seed==null)throw new InvalidDataException("The official decryption companion lacks the DQXI title entry.");
        using(var f=new FileStream(destination,FileMode.CreateNew,FileAccess.Write))using(var w=new BinaryWriter(f)) {
            w.Write((uint)1);w.Write(new byte[12]);w.Write(TitleId);w.Write(seed);w.Write(new byte[8]);
        }
    }
    public static CiaSource ExtractOriginal(string cia, string root, string ctrtool, string threeDstool, string romConverto, CancellationToken cancel) {
        return ExtractOriginal(cia,root,ctrtool,threeDstool,romConverto,cancel,false);
    }
    public static CiaSource ExtractOriginal(string cia, string root, string ctrtool, string threeDstool, string romConverto, CancellationToken cancel, bool compactWork) {
        cia=System.IO.Path.GetFullPath(cia); root=System.IO.Path.GetFullPath(root);
        BuildSupport.NoReparse(root);
        if(BuildSupport.IsWithin(root,cia)) throw new InvalidDataException("CIA input lies inside extraction output.");
        // Keep the user's input read-only throughout extraction.
        using(var inputLock=new FileStream(cia,FileMode.Open,FileAccess.Read,FileShare.Read)) {
            ValidateOriginal(cia,cancel);
            BuildSupport.CreateExclusiveDirectory(root);
            string prefix=System.IO.Path.Combine(root,"content"); string tmd=System.IO.Path.Combine(root,"source.tmd");
            string log=System.IO.Path.Combine(root,"extract.log");
            // CTRTool applies CIA-layer decryption where supported by its stock build.
            BuildSupport.RunTool(ctrtool,new string[]{"-q","--contents="+prefix,"--tmd="+tmd,cia},root,log,cancel);
            var result=ReadTmd(tmd,prefix); result.CiaPath=cia; result.Root=root;
            VerifyContentSizes(result);
            // CTRTool unwraps the outer CIA AES layer. Resolve the inner NCCH
            // separately, including the manual, before interpreting its bytes.
            string seedDb=System.IO.Path.Combine(root,"seeddb.bin");
            try {
                foreach(var row in result.Contents) {
                    bool contentPlain=true;
                    try{if(row.Index==0)RomBuilder.ValidateInputGame(row.Path);else RomBuilder.ValidateInputManual(row.Path);}
                    catch(InvalidDataException){contentPlain=false;}
                    if(contentPlain || String.IsNullOrEmpty(romConverto))continue;
                    if(!File.Exists(seedDb))WriteTitleSeedDatabase(System.IO.Path.Combine(System.IO.Path.GetDirectoryName(threeDstool),"ext_key.txt"),seedDb);
                    string decoded=System.IO.Path.Combine(root,"decrypted-content."+row.Index.ToString("x4")+"."+row.Id.ToString("x8")+".cxi");
                    BuildSupport.NoReparse(decoded);
                    if(File.Exists(decoded))throw new IOException("Decryption destination already exists.");
                    File.AppendAllText(log,"NCCH stage: rom-converto, content index "+row.Index+".\n");
                    BuildSupport.RunTool(romConverto,new string[]{"ctr","decrypt",row.Path,decoded},root,log,cancel);
                    if((ulong)new FileInfo(decoded).Length!=row.Size)throw new InvalidDataException("Decrypted content size differs from original TMD.");
                    if(row.Index==0)RomBuilder.ValidateInputGame(decoded);else RomBuilder.ValidateInputManual(decoded);
                    string encryptedCopy=row.Path;row.Path=decoded;
                    // Both paths are generated inside this exclusive extraction root.
                    // Retain only the successfully validated decrypted content.
                    if(compactWork)File.Delete(encryptedCopy);
                }
            } finally { if(File.Exists(seedDb))File.Delete(seedDb); }
            foreach(var row in result.Contents) if(row.Index==0) result.GamePath=row.Path;
            RomBuilder.ReadInputGameHeader(result.GamePath);
            bool plain=true;try{RomBuilder.ValidateInputGame(result.GamePath);}catch(InvalidDataException){plain=false;}
            if(plain) {
                BuildSupport.RunTool(ctrtool,new string[]{"-q","-p","--exheader="+System.IO.Path.Combine(root,"exheader.bin"),"--exefs="+System.IO.Path.Combine(root,"exefs.bin"),"--romfs="+System.IO.Path.Combine(root,"romfs.bin"),result.GamePath},root,log,cancel);
            } else {
                if(String.IsNullOrEmpty(threeDstool))throw new InvalidDataException("NCCH regions need decryption. The updated installer supplies 3dstool automatically.");
                File.AppendAllText(log,"NCCH stage: automatic region decryption with 3dstool.\n");
                BuildSupport.RunTool(threeDstool,new string[]{"-x","-t","cxi","-f",result.GamePath,"--header",System.IO.Path.Combine(root,"ncch-header.bin"),"--exh",System.IO.Path.Combine(root,"exheader.bin"),"--exefs",System.IO.Path.Combine(root,"exefs.bin"),"--romfs",System.IO.Path.Combine(root,"romfs.bin")},root,log,cancel);
            }
            RomBuilder.ValidateExtractedGameParts(result.GamePath,root);
            BuildSupport.RunTool(ctrtool,new string[]{"-q","-p","-t","exefs","--decompresscode","--exefsdir="+System.IO.Path.Combine(root,"exefs"),System.IO.Path.Combine(root,"exefs.bin")},root,log,cancel);
            // Keep the IVFC region extraction separate from directory extraction.
            // 3dstool's ROMFS parser extracts the complete tree and its file set is
            // checked again against the embedded ROMFS during the container rebuild.
            ExtractRomfsDirectory(threeDstool,System.IO.Path.Combine(root,"romfs.bin"),System.IO.Path.Combine(root,"romfs"),root,log,cancel,out result.RomFsFileCount,out result.RomFsTotalBytes);
            if(new FileInfo(System.IO.Path.Combine(root,"exefs","code.bin")).Length==0)
                throw new InvalidDataException("Original decompressed executable is empty.");
            RomBuilder.ValidatePatchProfile(System.IO.Path.Combine(root,"exefs","code.bin"),System.IO.Path.Combine(root,"exheader.bin"));
            ValidateOriginal(cia,cancel); return result;
        }
    }
    static uint Le32(byte[] b,int at) { return (uint)(b[at]|b[at+1]<<8|b[at+2]<<16|b[at+3]<<24); }
    static byte[] GeneratedRegionDigest(string file, long offset, long size) {
        using(var input=new FileStream(file,FileMode.Open,FileAccess.Read,FileShare.Read))
        using(var sha=SHA256.Create()) {
            if(offset<512 || size<=0 || offset>input.Length || size>input.Length-offset)
                throw new InvalidDataException("NCCH region exceeds content bounds.");
            input.Position=offset;var buffer=new byte[1024*1024];long remaining=size;
            while(remaining>0) {int n=input.Read(buffer,0,(int)Math.Min(remaining,buffer.Length));if(n==0)throw new EndOfStreamException();sha.TransformBlock(buffer,0,n,buffer,0);remaining-=n;}
            sha.TransformFinalBlock(new byte[0],0,0);return sha.Hash;
        }
    }
    // Validate plaintext structures, then regenerate integrity metadata on a new
    // private output. Stale input flags/digests are not input rejection gates.
    public static string NormalizeAuxiliaryContent(string original, string destination) {
        RomBuilder.ValidateInputManual(original);BuildSupport.NoReparse(destination);
        if(String.Equals(System.IO.Path.GetFullPath(original),System.IO.Path.GetFullPath(destination),StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("Auxiliary output must be a new private file.");
        byte[] header=new byte[512];
        using(var f=File.OpenRead(original)){if(f.Read(header,0,512)!=512)throw new EndOfStreamException();}
        long size=(long)Le32(header,0x1b4)*512,hashSize=(long)Le32(header,0x1b8)*512;
        if(hashSize<=0 || hashSize>size)throw new InvalidDataException("Invalid generated auxiliary NCCH superblock bounds.");
        File.Copy(original,destination,false);
        Buffer.BlockCopy(GeneratedRegionDigest(destination,(long)Le32(header,0x1b0)*512,hashSize),0,header,0x1e0,32);
        header[0x18f]=(byte)((header[0x18f]|4)&~0x21);header[0x18b]=0;
        using(var output=new FileStream(destination,FileMode.Open,FileAccess.Write,FileShare.None)) {
            output.Write(header,0,header.Length);output.Flush(true);
        }
        return destination;
    }
    static string EncodingMagic(byte[] b) { return System.Text.Encoding.ASCII.GetString(b,256,4); }
    // Preserve title version and all content IDs; rebuild the game and repair verified plaintext flags in private auxiliary copies.
    public static string PackCia(CiaSource original, string rebuiltGame, string output,
        string makerom, string ctrtool, string work, CancellationToken cancel) {
        return PackCia(original,rebuiltGame,output,makerom,ctrtool,work,cancel,false);
    }
    public static string PackCia(CiaSource original, string rebuiltGame, string output,
        string makerom, string ctrtool, string work, CancellationToken cancel, bool compactWork) {
        VerifyContentSizes(original); RomBuilder.ValidatePlaintextGame(rebuiltGame,cancel);
        if(File.Exists(output) || File.Exists(output+".partial")) throw new IOException("CIA output already exists.");
        string partial=output+".partial"; var args=new List<string>{"-f","cia","-target","t","-ignoresign","-ver",original.TitleVersion.ToString(),"-o",partial};
        var expected=new Dictionary<ushort,string>();
        foreach(var row in original.Contents) {
            string path=row.Index==0?rebuiltGame:NormalizeAuxiliaryContent(row.Path,System.IO.Path.Combine(work,"auxiliary-"+row.Index+".ncch"));
            args.Add("-i"); args.Add(path+":"+row.Index+":"+row.Id);
            expected.Add(row.Index,BuildSupport.HashFile(path));
        }
        BuildSupport.RunTool(makerom,args.ToArray(),work,System.IO.Path.Combine(work,"cia.log"),cancel);
        if(compactWork) {
            if(!BuildSupport.IsWithin(work,rebuiltGame))throw new InvalidDataException("Only an owned rebuild intermediate may be released.");
            File.Delete(rebuiltGame);
        }
        string verify=System.IO.Path.Combine(work,"verify-cia"); BuildSupport.CreateExclusiveDirectory(verify);
        string prefix=System.IO.Path.Combine(verify,"content"); string tmd=System.IO.Path.Combine(verify,"output.tmd");
        BuildSupport.RunTool(ctrtool,new string[]{"-q","-p","--contents="+prefix,"--tmd="+tmd,partial},work,System.IO.Path.Combine(work,"cia-verify.log"),cancel);
        var readback=ReadTmd(tmd,prefix); VerifyContentFiles(readback);
        if(readback.TitleVersion!=original.TitleVersion || readback.Contents.Length!=original.Contents.Length)
            throw new InvalidDataException("CIA title version or content set changed.");
        foreach(var row in readback.Contents) {
            string hash; if(!expected.TryGetValue(row.Index,out hash) || hash!=BuildSupport.HashFile(row.Path))
                throw new InvalidDataException("Rebuilt CIA content differs: "+row.Index);
            CiaContent source=null; foreach(var old in original.Contents) if(old.Index==row.Index) source=old;
            if(source==null || source.Id!=row.Id) throw new InvalidDataException("CIA content ID changed.");
        }
        cancel.ThrowIfCancellationRequested();
        if(compactWork)Directory.Delete(verify,true);
        File.Move(partial,output); return output;
    }
}
