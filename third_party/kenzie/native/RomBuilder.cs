using System;
using System.Collections.Generic;
using System.IO;
using System.Security.Cryptography;
using System.Threading;

// Private, decrypted DQXI cartridge reconstruction. Inputs are never modified.
// A completed output is promoted only after partition and filesystem readback.
public static class RomBuilder
{
    const string ToolUrl = "https://github.com/dnasdw/3dstool/releases/download/v1.2.6/3dstool.zip";
    const string ToolZipSha = "481e20f445eb2f0f506d0d88cd750385bc8377670d681d6f66f584a176027806";
    const string ToolExeSha = "967fd5ec6476df1fa6a01da0df5a1fea339aa488c10be218d38e07f4b8143b7e";
    const ulong TitleId = 0x0004000000199200UL;

    sealed class Part { public long Offset; public long Size; }

    public static void ValidateCartridge(string path)
    {
        ReadPartitions(Path.GetFullPath(path));
    }

    static uint U32(byte[] b, int p)
    {
        return (uint)(b[p] | b[p + 1] << 8 | b[p + 2] << 16 | b[p + 3] << 24);
    }

    static ulong U64(byte[] b, int p)
    {
        return U32(b, p) | ((ulong)U32(b, p + 4) << 32);
    }

    static bool Magic(byte[] b, int p, string text)
    {
        if (b.Length < p + text.Length) return false;
        for (int i = 0; i < text.Length; i++) if (b[p + i] != (byte)text[i]) return false;
        return true;
    }

    static byte[] ReadExactly(Stream s, int size)
    {
        byte[] b = new byte[size];
        int p = 0;
        while (p < size) { int n = s.Read(b, p, size - p); if (n == 0) throw new InvalidDataException("Unexpected end of cartridge."); p += n; }
        return b;
    }

    static void CheckRange(long offset, long size, long length, string label)
    {
        if (offset < 0 || size < 0 || offset > length || size > length - offset)
            throw new InvalidDataException(label + " exceeds file bounds.");
    }

    static SortedDictionary<int, Part> ReadPartitions(string path)
    {
        var result = new SortedDictionary<int, Part>();
        using (var s = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read))
        {
            byte[] h = ReadExactly(s, 512);
            if (!Magic(h, 256, "NCSD")) throw new InvalidDataException("Single-ROM output requires a decrypted .3ds/.cci cartridge, not an .app/.cxi.");
            for (int i = 0; i < 8; i++)
            {
                long offset = (long)U32(h, 0x120 + i * 8) * 512;
                long size = (long)U32(h, 0x124 + i * 8) * 512;
                if (size == 0) { if (offset != 0) throw new InvalidDataException("Empty cartridge partition has an offset."); continue; }
                if (offset < 512 || size < 512) throw new InvalidDataException("Invalid cartridge partition.");
                CheckRange(offset, size, s.Length, "Cartridge partition");
                foreach (Part other in result.Values)
                    if (offset < other.Offset + other.Size && other.Offset < offset + size)
                        throw new InvalidDataException("Cartridge partitions overlap.");
                result.Add(i, new Part { Offset = offset, Size = size });
            }
            if (!result.ContainsKey(0)) throw new InvalidDataException("Cartridge has no game partition.");
            s.Position = result[0].Offset;
            byte[] game = ReadExactly(s, 512);
            if (!Magic(game, 256, "NCCH") || U64(game, 0x118) != TitleId)
                throw new InvalidDataException("This is not the supported Japanese DQXI cartridge.");
        }
        return result;
    }

    static byte[] HashRange(string path, long offset, long size, CancellationToken cancel)
    {
        using (var s = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read))
        using (var sha = SHA256.Create())
        {
            CheckRange(offset, size, s.Length, "Hash range"); s.Position = offset;
            byte[] buffer = new byte[1024 * 1024];
            while (size > 0)
            {
                cancel.ThrowIfCancellationRequested();
                int n = s.Read(buffer, 0, (int)Math.Min(size, buffer.Length));
                if (n == 0) throw new InvalidDataException("Unexpected end of cartridge while hashing.");
                sha.TransformBlock(buffer, 0, n, buffer, 0); size -= n;
            }
            sha.TransformFinalBlock(new byte[0], 0, 0); return sha.Hash;
        }
    }

    static bool Equal(byte[] a, byte[] b)
    {
        if (a.Length != b.Length) return false;
        int different = 0; for (int i = 0; i < a.Length; i++) different |= a[i] ^ b[i];
        return different == 0;
    }

    static string Hex(byte[] hash) { return BitConverter.ToString(hash).Replace("-", "").ToLowerInvariant(); }
    static string FileHash(string path, CancellationToken cancel) { return Hex(HashRange(path, 0, new FileInfo(path).Length, cancel)); }

    static void MatchHeaderDigest(string path, byte[] header, long offset, long size, int expected, CancellationToken cancel)
    {
        byte[] digest = new byte[32]; Buffer.BlockCopy(header, expected, digest, 0, 32);
        if (!Equal(HashRange(path, offset, size, cancel), digest))
            throw new InvalidDataException("Generated NCCH integrity check failed for " +
                (expected==0x160 ? "ExHeader" : expected==0x1c0 ? "ExeFS" : "RomFS") + ".");
    }

    static void VerifyNcch(string path, bool requireDecrypted, CancellationToken cancel)
    {
        byte[] h;
        long length;
        using (var s = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read))
        { length = s.Length; h = ReadExactly(s, 512); }
        if (!Magic(h, 256, "NCCH") || U64(h, 0x118) != TitleId || (requireDecrypted && (h[0x18f] & 4) == 0))
            throw new InvalidDataException("Game partition is not a supported decrypted NCCH.");
        // This implementation deliberately supports only the established 512-byte media units.
        if (h[0x18e] != 0) throw new InvalidDataException("Unsupported NCCH media-unit size.");
        long declared = (long)U32(h, 0x104) * 512;
        if (declared != length) throw new InvalidDataException("NCCH declared size differs from partition size.");
        uint extendedSize = U32(h, 0x180);
        if (extendedSize == 0) throw new InvalidDataException("Game extended header is missing.");
        CheckRange(512, extendedSize, length, "Extended header");
        MatchHeaderDigest(path, h, 512, extendedSize, 0x160, cancel);
        foreach (int start in new int[] { 0x1a0, 0x1b0 })
        {
            long offset = (long)U32(h, start) * 512;
            long size = (long)U32(h, start + 4) * 512;
            long hashSize = (long)U32(h, start + 8) * 512;
            if (offset < 512 || size == 0 || hashSize == 0 || hashSize > size)
                throw new InvalidDataException("Invalid filesystem hash-region bounds.");
            CheckRange(offset, size, length, "NCCH filesystem");
            MatchHeaderDigest(path, h, offset, hashSize, start == 0x1a0 ? 0x1c0 : 0x1e0, cancel);
        }
    }

    public static void ValidatePlaintextGame(string path, CancellationToken cancel) {
        VerifyNcch(path, false, cancel);
    }

    // Input selection uses bounded structures, not stored SHA values. CIA-layer
    // extraction does not imply that NCCH regions have already been decrypted.
    public static byte[] ReadInputGameHeader(string path) {
        byte[] h; long length;
        using(var f=File.OpenRead(path)){length=f.Length;h=ReadExactly(f,512);}
        if(!Magic(h,256,"NCCH") || U64(h,0x118)!=TitleId || h[0x18e]!=0)
            throw new InvalidDataException("Unsupported DQXI NCCH header or media-unit size.");
        if((long)U32(h,0x104)*512!=length || U32(h,0x180)!=0x400)
            throw new InvalidDataException("Unsupported NCCH size or extended-header layout.");
        CheckRange(512,0x800,length,"Extended header and access descriptor");
        var spans=new List<KeyValuePair<long,long>>();
        spans.Add(new KeyValuePair<long,long>(0,0xa00));
        foreach(int at in new int[]{0x190,0x198,0x1a0,0x1b0}) {
            long offset=(long)U32(h,at)*512,size=(long)U32(h,at+4)*512;
            if(size==0){if(at>=0x1a0)throw new InvalidDataException("Missing NCCH filesystem.");continue;}
            CheckRange(offset,size,length,"NCCH region");
            foreach(var span in spans)if(offset<span.Key+span.Value && span.Key<offset+size)
                throw new InvalidDataException("NCCH regions overlap.");
            spans.Add(new KeyValuePair<long,long>(offset,size));
        }
        return h;
    }

    static void CheckExheaderLayout(byte[] h) {
        if(h.Length<0x800 || U64(h,0x200)!=TitleId || U32(h,16)!=0x100000)
            throw new InvalidDataException("NCCH_INPUT_EXHEADER: ExHeader is not supported plaintext. NCCH decryption is required or the source is malformed.");
    }

    static void CheckExeFsLayout(byte[] h, long length) {
        var names=new HashSet<string>(StringComparer.Ordinal);
        var spans=new List<KeyValuePair<long,long>>(); bool code=false;
        for(int i=0;i<10;i++) {
            int at=i*16;uint size=U32(h,at+12),relative=U32(h,at+8);
            int chars=0;while(chars<8 && h[at+chars]!=0)chars++;
            if(chars==0 && size==0 && relative==0)continue;
            if(chars==0 || size==0)throw new InvalidDataException("NCCH_INPUT_EXEFS: Invalid ExeFS entry; decryption did not produce a supported filesystem.");
            for(int j=0;j<8;j++)if((j<chars && !(h[at+j]=='.' || h[at+j]=='_' || h[at+j]=='-' ||
                h[at+j]>='a' && h[at+j]<='z' || h[at+j]>='A' && h[at+j]<='Z' || h[at+j]>='0' && h[at+j]<='9')) ||
                (j>=chars && h[at+j]!=0))throw new InvalidDataException("NCCH_INPUT_EXEFS: Unsupported ExeFS name; encrypted or malformed input.");
            string name=System.Text.Encoding.ASCII.GetString(h,at,chars);
            if(!names.Add(name))throw new InvalidDataException("NCCH_INPUT_EXEFS: Duplicate file name.");
            long offset=512+(long)relative;CheckRange(offset,size,length,"ExeFS file");
            foreach(var span in spans)if(offset<span.Key+span.Value && span.Key<offset+size)
                throw new InvalidDataException("NCCH_INPUT_EXEFS: Files overlap.");
            spans.Add(new KeyValuePair<long,long>(offset,size)); code|=name==".code";
        }
        if(!code)throw new InvalidDataException("NCCH_INPUT_EXEFS: Missing .code; encrypted or unsupported input.");
    }

    static void CheckRomFsLayout(byte[] h, long length) {
        if(!Magic(h,0,"IVFC") || U32(h,4)!=0x10000 || U32(h,0x54)!=0x5c)
            throw new InvalidDataException("NCCH_INPUT_ROMFS: Missing supported IVFC header; encrypted or malformed input.");
        long[] sizes=new long[3],blocks=new long[3];
        for(int i=0;i<3;i++) {
            ulong size=U64(h,0x14+i*24);uint shift=U32(h,0x1c+i*24);
            if(size==0 || size>(ulong)length || shift<5 || shift>24)
                throw new InvalidDataException("NCCH_INPUT_ROMFS: Invalid IVFC layer bounds.");
            sizes[i]=(long)size;blocks[i]=1L<<(int)shift;
        }
        long master=U32(h,8);CheckRange(0x60,master,length,"IVFC master table");
        long data=(0x60+master+blocks[1]-1)&~(blocks[1]-1);
        long level0=(data+sizes[2]+blocks[2]-1)&~(blocks[2]-1);
        long level1=(level0+sizes[0]+blocks[0]-1)&~(blocks[0]-1);
        CheckRange(data,sizes[2],length,"IVFC data");
        CheckRange(level0,sizes[0],length,"IVFC layer zero");
        CheckRange(level1,sizes[1],length,"IVFC layer one");
    }

    public static void ValidateInputGame(string path) {
        byte[] h=ReadInputGameHeader(path);
        using(var f=File.OpenRead(path)) {
            f.Position=512;CheckExheaderLayout(ReadExactly(f,0x800));
            f.Position=(long)U32(h,0x1a0)*512;CheckExeFsLayout(ReadExactly(f,512),(long)U32(h,0x1a4)*512);
            f.Position=(long)U32(h,0x1b0)*512;CheckRomFsLayout(ReadExactly(f,0x60),(long)U32(h,0x1b4)*512);
        }
    }

    // DQXI's auxiliary CIA content is a CFA manual with a RomFS, no executable.
    // Recognise its plaintext by bounded structures, without input hash gates.
    public static void ValidateInputManual(string path) {
        BuildSupport.NoReparse(path);
        using(var f=File.OpenRead(path)) {
            byte[] h=ReadExactly(f,512);
            if(!Magic(h,0x100,"NCCH") || h[0x18e]!=0 || (long)U32(h,0x104)*512!=f.Length ||
               U32(h,0x180)!=0 || U32(h,0x1a4)!=0)
                throw new InvalidDataException("Unsupported auxiliary DQXI content layout.");
            long offset=(long)U32(h,0x1b0)*512,size=(long)U32(h,0x1b4)*512;
            if(offset<512 || size<0x60)throw new InvalidDataException("Auxiliary content lacks a RomFS.");
            CheckRange(offset,size,f.Length,"Manual RomFS");f.Position=offset;
            CheckRomFsLayout(ReadExactly(f,0x60),size);
        }
    }

    public static void ValidateExtractedGameParts(string ncch, string folder) {
        byte[] h=ReadInputGameHeader(ncch);
        string exheader=Path.Combine(folder,"exheader.bin"),exefs=Path.Combine(folder,"exefs.bin"),romfs=Path.Combine(folder,"romfs.bin");
        BuildSupport.NoReparse(exheader);BuildSupport.NoReparse(exefs);BuildSupport.NoReparse(romfs);
        if(new FileInfo(exheader).Length!=0x800 || new FileInfo(exefs).Length!=(long)U32(h,0x1a4)*512 ||
            new FileInfo(romfs).Length!=(long)U32(h,0x1b4)*512)
            throw new InvalidDataException("Decrypted NCCH region sizes differ from their declared bounds.");
        CheckExheaderLayout(File.ReadAllBytes(exheader));
        using(var f=File.OpenRead(exefs))CheckExeFsLayout(ReadExactly(f,512),f.Length);
        using(var f=File.OpenRead(romfs))CheckRomFsLayout(ReadExactly(f,0x60),f.Length);
    }

    // Version-specific ARM hooks require their original instructions and mapped
    // padding. This checks patch preconditions without a fixed input-file hash.
    public static void ValidatePatchProfile(string codePath, string exheaderPath) {
        byte[] code=File.ReadAllBytes(codePath), h=File.ReadAllBytes(exheaderPath);
        if(h.Length<0x400 || U64(h,0x200)!=TitleId)
            throw new InvalidDataException("Executable profile has an unsupported title/header.");
        ulong pages=(ulong)U32(h,20)+U32(h,36)+U32(h,52);
        uint textSize=U32(h,24), textPages=U32(h,20);
        if(pages*4096!=(ulong)code.Length || U32(h,16)!=0x100000 ||
           textSize>0x624200-280 || (ulong)textPages*4096<0x625000)
            throw new InvalidDataException("Executable segments do not support the current voice/Luma patch.");
        ulong dataStart=U32(h,48), dataSize=U32(h,56), bss=U32(h,60);
        ulong globalsEnd=dataStart+dataSize+bss;
        ulong lumaEnd=dataStart+((dataSize+bss+4095)&~4095UL);
        ulong azaharEnd=dataStart+(ulong)U32(h,52)*4096+((bss+4095)&~4095UL);
        if(globalsEnd>0x839900 || 0x839900+640>Math.Min(lumaEnd,azaharEnd))
            throw new InvalidDataException("Voice state would overlap globals or exceed mapped RW memory.");
        int[] offsets={0xc5328,0xc465c,0xc4f3c,0x483d4,0x55fe58,0xebd34,0xc4274,0xc3e78,0xc4214,0x448e80,0x112e4};
        uint[] words={0xe92d4038,0xe92d4010,0xe92d4010,0xe92d4fff,0xe1d010b0,0xe1a002a7,0xe594000c,0xe12fff32,0xe5943034,0xeb00335e,0xef000028};
        for(int i=0;i<offsets.Length;i++) {
            if(offsets[i]>code.Length-4 || U32(code,offsets[i])!=words[i])
                throw new InvalidDataException("Unsupported or already modified ARM hook at 0x"+offsets[i].ToString("x")+".");
        }
        for(int i=0x624200;i<0x625000;i++)if(code[i]!=0)
            throw new InvalidDataException("Native voice executable padding is occupied.");
    }

    static bool NormalizePrivateHeader(string path, CancellationToken cancel)
    {
        // This is only called on a private copy containing validated plaintext.
        ValidateInputGame(path);
        byte[] h=ReadInputGameHeader(path),before=(byte[])h.Clone();
        Buffer.BlockCopy(HashRange(path,512,U32(h,0x180),cancel),0,h,0x160,32);
        foreach(int at in new int[]{0x1a0,0x1b0}) {
            long bytes=(long)U32(h,at+8)*512,size=(long)U32(h,at+4)*512;
            if(bytes<=0 || bytes>size)throw new InvalidDataException("Invalid generated NCCH superblock bounds.");
            Buffer.BlockCopy(HashRange(path,(long)U32(h,at)*512,bytes,cancel),0,h,at==0x1a0?0x1c0:0x1e0,32);
        }
        h[0x18f]=(byte)((h[0x18f]|4)&~0x21); h[0x18b]=0;
        using (var s = new FileStream(path, FileMode.Open, FileAccess.ReadWrite, FileShare.None))
        {
            s.Write(h,0,h.Length);s.Flush();
        }
        VerifyNcch(path, true, cancel); return !Equal(h,before);
    }

    public static void CreatePlaintextGameCopy(string ncch, string extracted, string destination, CancellationToken cancel) {
        BuildSupport.NoReparse(ncch);BuildSupport.NoReparse(destination);
        if(String.Equals(Path.GetFullPath(ncch),Path.GetFullPath(destination),StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("Prepared NCCH must be a new private file.");
        ValidateExtractedGameParts(ncch,extracted);byte[] h=ReadInputGameHeader(ncch);
        using(var input=File.OpenRead(ncch))using(var output=new FileStream(destination,FileMode.CreateNew,FileAccess.Write))
            BuildSupport.CopyLimited(input,output,input.Length,cancel);
        using(var output=new FileStream(destination,FileMode.Open,FileAccess.Write,FileShare.None)) {
            foreach(var pair in new KeyValuePair<int,string>[] {
                new KeyValuePair<int,string>(0,"exheader.bin"),new KeyValuePair<int,string>(0x1a0,"exefs.bin"),new KeyValuePair<int,string>(0x1b0,"romfs.bin")}) {
                string part=BuildSupport.Safe(extracted,pair.Value);output.Position=pair.Key==0?512:(long)U32(h,pair.Key)*512;
                using(var input=File.OpenRead(part))BuildSupport.CopyLimited(input,output,input.Length,cancel);
            }
        }
        NormalizePrivateHeader(destination,cancel);
    }

    static void VerifyEmbeddedFiles(string game, string folder, CancellationToken cancel)
    {
        byte[] h;
        using (var s = new FileStream(game, FileMode.Open, FileAccess.Read, FileShare.Read)) h = ReadExactly(s, 512);
        foreach (var row in new KeyValuePair<int, string>[] {
            new KeyValuePair<int, string>(0x1a0, "new-exefs.bin"),
            new KeyValuePair<int, string>(0x1b0, "new-romfs.bin") })
        {
            string expected = Path.Combine(folder, row.Value);
            long offset = (long)U32(h, row.Key) * 512; long size = (long)U32(h, row.Key + 4) * 512;
            long expectedSize = new FileInfo(expected).Length;
            if (size != expectedSize || !Equal(HashRange(game, offset, size, cancel), HashRange(expected, 0, expectedSize, cancel)))
                throw new InvalidDataException("NCCH does not contain the exact newly built filesystem.");
        }
        string extended = Path.Combine(folder, "exheader.bin"); long extendedLength = new FileInfo(extended).Length;
        if (!Equal(HashRange(game, 512, extendedLength, cancel), HashRange(extended, 0, extendedLength, cancel)))
            throw new InvalidDataException("Rebuilt extended header does not match its private source.");
        foreach (var row in new KeyValuePair<int, string>[] {
            new KeyValuePair<int, string>(0x198, "logo.bin"),
            new KeyValuePair<int, string>(0x190, "plain.bin") })
        {
            string expected = Path.Combine(folder, row.Value);
            long offset = (long)U32(h, row.Key) * 512; long size = (long)U32(h, row.Key + 4) * 512;
            if (size == 0) { if (File.Exists(expected) && new FileInfo(expected).Length != 0) throw new InvalidDataException("Original NCCH resource was dropped."); continue; }
            if (!File.Exists(expected) || size != new FileInfo(expected).Length || !Equal(HashRange(game, offset, size, cancel), HashRange(expected, 0, size, cancel)))
                throw new InvalidDataException("Original NCCH resource changed.");
        }
    }

    static string Root(string path)
    {
        return Path.GetFullPath(path).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar) + Path.DirectorySeparatorChar;
    }

    static void RejectLinks(string path)
    {
        if ((File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0)
            throw new InvalidDataException("Linked filesystem paths are not permitted: " + path);
    }

    static void CheckAncestors(string path)
    {
        string at = Path.GetFullPath(path);
        while (!String.IsNullOrEmpty(at))
        {
            if (Directory.Exists(at) || File.Exists(at)) RejectLinks(at);
            string parent = Path.GetDirectoryName(at);
            if (String.Equals(parent, at, StringComparison.OrdinalIgnoreCase)) break;
            at = parent;
        }
    }

    static Dictionary<string, string> Inventory(string folder, CancellationToken cancel)
    {
        string root = Root(folder); CheckAncestors(folder);
        if (!Directory.Exists(folder)) throw new DirectoryNotFoundException(folder);
        var files = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        var pending = new Stack<string>(); pending.Push(Path.GetFullPath(folder));
        while (pending.Count != 0)
        {
            cancel.ThrowIfCancellationRequested(); string dir = pending.Pop(); RejectLinks(dir);
            foreach (string child in Directory.GetDirectories(dir)) { RejectLinks(child); pending.Push(child); }
            foreach (string file in Directory.GetFiles(dir))
            {
                RejectLinks(file); string absolute = Path.GetFullPath(file);
                if (!absolute.StartsWith(root, StringComparison.OrdinalIgnoreCase)) throw new InvalidDataException("Filesystem path escaped its root.");
                string relative = absolute.Substring(root.Length);
                if (relative.IndexOf(':') >= 0 || relative.IndexOf('\0') >= 0 || files.ContainsKey(relative))
                    throw new InvalidDataException("Unsafe or duplicate filesystem path.");
                files.Add(relative, absolute);
            }
        }
        return files;
    }

    static void CopyTree(string input, string output, CancellationToken cancel)
    {
        foreach (var pair in Inventory(input, cancel))
        {
            cancel.ThrowIfCancellationRequested(); string dest = Path.Combine(output, pair.Key);
            Directory.CreateDirectory(Path.GetDirectoryName(dest)); File.Copy(pair.Value, dest, false);
            if (FileHash(pair.Value, cancel) != FileHash(dest, cancel)) throw new IOException("Private input copy verification failed.");
        }
    }

    static void VerifyTree(string expected, string actual, CancellationToken cancel)
    {
        var a = Inventory(expected, cancel); var b = Inventory(actual, cancel);
        if (a.Count != b.Count) throw new InvalidDataException("Rebuilt filesystem path set differs.");
        foreach (var pair in a)
        {
            cancel.ThrowIfCancellationRequested(); string target;
            if (!b.TryGetValue(pair.Key, out target) || FileHash(pair.Value, cancel) != FileHash(target, cancel))
                throw new InvalidDataException("Rebuilt filesystem does not match staged bytes: " + pair.Key);
            if(!String.Equals(pair.Key, Path.GetFullPath(target).Substring(Root(actual).Length), StringComparison.Ordinal))
                throw new InvalidDataException("Rebuilt filesystem path casing changed: " + pair.Key);
        }
    }

    static Dictionary<string,string> SnapshotTree(string folder, CancellationToken cancel) {
        var hashes=new Dictionary<string,string>(StringComparer.Ordinal);
        foreach(var pair in Inventory(folder,cancel))hashes.Add(pair.Key,FileHash(pair.Value,cancel));
        return hashes;
    }
    static void VerifyTreeSnapshot(Dictionary<string,string> expected, string actual, CancellationToken cancel) {
        var files=Inventory(actual,cancel);
        if(expected.Count!=files.Count)throw new InvalidDataException("Rebuilt filesystem path set differs.");
        foreach(var pair in expected) {
            string path;
            if(!files.TryGetValue(pair.Key,out path) ||
                !String.Equals(pair.Key,Path.GetFullPath(path).Substring(Root(actual).Length),StringComparison.Ordinal) ||
                pair.Value!=FileHash(path,cancel))
                throw new InvalidDataException("Rebuilt filesystem does not match staged bytes: "+pair.Key);
        }
    }

    static void VerifyExeFsNonCode(string original, string staged, CancellationToken cancel)
    {
        var a = Inventory(original, cancel); var b = Inventory(staged, cancel);
        if (!a.Remove("code.bin") || !b.Remove("code.bin")) throw new InvalidDataException("Original ExeFS code is missing.");
        if (a.Count != b.Count) throw new InvalidDataException("Original ExeFS path set differs.");
        foreach (var pair in a)
        {
            string target;
            if (!b.TryGetValue(pair.Key, out target) || FileHash(pair.Value, cancel) != FileHash(target, cancel))
                throw new InvalidDataException("A non-code executable resource differs from the cartridge: " + pair.Key);
        }
    }

    static bool Overlap(string a, string b)
    {
        return Root(a).StartsWith(Root(b), StringComparison.OrdinalIgnoreCase) || Root(b).StartsWith(Root(a), StringComparison.OrdinalIgnoreCase);
    }

    static void AliasExeFs(string folder, string input, string output, CancellationToken cancel)
    {
        string source = Path.Combine(folder, input); string target = Path.Combine(folder, output);
        if (!File.Exists(source)) return;
        if (File.Exists(target))
        {
            if (FileHash(source, cancel) != FileHash(target, cancel)) throw new InvalidDataException("Conflicting ExeFS filenames.");
            File.Delete(source); // This is solely the fresh private copy, never an input file.
        }
        else File.Move(source, target);
    }

    static string BuildNcchCore(string sourceNcch, string extracted, string mod, string folder,
        Action<string, int> progress, CancellationToken cancel, string tool, bool compactWork)
    {
        string log = Path.Combine(folder, "rebuild.log");
        string privateRomfs = Path.Combine(folder, "romfs");
        string privateExefs = Path.Combine(folder, "exefs");
        Action<string[]> run = delegate(string[] arguments) {
            BuildSupport.RunTool(tool, arguments, folder, log, cancel);
        };
        NormalizePrivateHeader(sourceNcch, cancel);
        run(new string[] { "-x", "-t", "cxi", "-f", sourceNcch, "--header", Path.Combine(folder, "ncch.bin"), "--exh", Path.Combine(folder, "exheader.bin"), "--logo", Path.Combine(folder, "logo.bin"), "--plain", Path.Combine(folder, "plain.bin"), "--exefs", Path.Combine(folder, "original-exefs.bin"), "--romfs", Path.Combine(folder, "original-romfs.bin") });
        if(compactWork) {
            if(!BuildSupport.IsWithin(folder,sourceNcch))throw new InvalidDataException("Only the private NCCH source may be released.");
            File.Delete(sourceNcch);
        }
        string originalExefs = Path.Combine(folder, "original-exefs");
        run(new string[] { "-x", "-t", "exefs", "-f", Path.Combine(folder, "original-exefs.bin"), "--header", Path.Combine(folder, "exefs-header.bin"), "--exefs-dir", originalExefs });
        run(new string[] { "-x", "-t", "romfs", "-f", Path.Combine(folder, "original-romfs.bin"), "--romfs-dir", privateRomfs });
        VerifyTree(Path.Combine(extracted, "romfs"), privateRomfs, cancel);
        if(compactWork)File.Delete(Path.Combine(folder,"original-romfs.bin"));
        progress("Copying the private game files and applying the translation...", 73);
        CopyTree(Path.Combine(extracted, "exefs"), privateExefs, cancel);
        AliasExeFs(privateExefs, "banner.bin", "banner.bnr", cancel); AliasExeFs(privateExefs, "icon.bin", "icon.icn", cancel);
        AliasExeFs(originalExefs, "banner.bin", "banner.bnr", cancel); AliasExeFs(originalExefs, "icon.bin", "icon.icn", cancel);
        VerifyExeFsNonCode(originalExefs, privateExefs, cancel);
        var sourceFiles = Inventory(privateRomfs, cancel);
        foreach (var replacement in Inventory(Path.Combine(mod, "romfs"), cancel))
        {
            cancel.ThrowIfCancellationRequested(); string dest;
            if (!sourceFiles.TryGetValue(replacement.Key, out dest))
            {
                // DQXI S voice assets are new files produced by our PC converter.
                // Inventory validates paths; additions stay in this private tree.
                dest = BuildSupport.Safe(privateRomfs, replacement.Key.Replace('\\', '/'));
                Directory.CreateDirectory(Path.GetDirectoryName(dest));
                sourceFiles.Add(replacement.Key, dest);
            }
            File.Copy(replacement.Value, dest, true);
            if (FileHash(replacement.Value, cancel) != FileHash(dest, cancel)) throw new IOException("Translation copy verification failed.");
        }
        string code = Path.Combine(privateExefs, "code.bin");
        ValidatePatchProfile(code,Path.Combine(folder,"exheader.bin"));
        byte[] patched = NativeCodecs.ApplyIps(File.ReadAllBytes(code), File.ReadAllBytes(Path.Combine(mod, "exefs", "code.ips")));
        File.WriteAllBytes(code, patched);
        byte[] extended = File.ReadAllBytes(Path.Combine(folder, "exheader.bin"));
        if (extended.Length < 0x10) throw new InvalidDataException("Truncated game extended header.");
        extended[0x0d] &= 0xfe; File.WriteAllBytes(Path.Combine(folder, "exheader.bin"), extended);
        AliasExeFs(privateExefs, "banner.bin", "banner.bnr", cancel); AliasExeFs(privateExefs, "icon.bin", "icon.icn", cancel);
        run(new string[] { "-c", "-t", "exefs", "-f", Path.Combine(folder, "new-exefs.bin"), "--header", Path.Combine(folder, "exefs-header.bin"), "--exefs-dir", privateExefs });
        progress("Rebuilding the game filesystem. This can take several minutes...", 77);
        run(new string[] { "-c", "-t", "romfs", "-f", Path.Combine(folder, "new-romfs.bin"), "--romfs-dir", privateRomfs });
        Dictionary<string,string> expectedRomfs=null;
        if(compactWork) {
            // Keep the complete expected file set and hashes, rather than a
            // second full staged tree while decoding the generated filesystem.
            expectedRomfs=SnapshotTree(privateRomfs,cancel);
            Directory.Delete(privateRomfs,true);
        }
        progress("Rebuilding the translated game partition...", 85);
        var args = new List<string> { "-c", "-t", "cxi", "-f", Path.Combine(folder, "translated.cxi"), "--header", Path.Combine(folder, "ncch.bin"), "--exh", Path.Combine(folder, "exheader.bin"), "--exefs", Path.Combine(folder, "new-exefs.bin"), "--romfs", Path.Combine(folder, "new-romfs.bin"), "--not-encrypt" };
        foreach (string name in new string[] { "logo", "plain" })
        { string path = Path.Combine(folder, name + ".bin"); if (File.Exists(path) && new FileInfo(path).Length > 0) { args.Add("--" + name); args.Add(path); } }
        run(args.ToArray()); string rebuiltGame = Path.Combine(folder, "translated.cxi"); VerifyNcch(rebuiltGame, true, cancel);
        VerifyEmbeddedFiles(rebuiltGame, folder, cancel);

        string verifyRomfs = Path.Combine(folder, "verify-romfs");
        string verifyExefs = Path.Combine(folder, "verify-exefs");
        run(new string[] { "-x", "-t", "romfs", "-f", Path.Combine(folder, "new-romfs.bin"), "--romfs-dir", verifyRomfs });
        run(new string[] { "-x", "-t", "exefs", "-f", Path.Combine(folder, "new-exefs.bin"), "--exefs-dir", verifyExefs });
        if(compactWork)VerifyTreeSnapshot(expectedRomfs,verifyRomfs,cancel);
        else VerifyTree(privateRomfs, verifyRomfs, cancel);
        VerifyTree(privateExefs, verifyExefs, cancel);
        if(compactWork) {
            Directory.Delete(verifyRomfs,true);Directory.Delete(verifyExefs,true);
            File.Delete(Path.Combine(folder,"new-romfs.bin"));
        }
        return rebuiltGame;
    }

    // CIA path: rebuild content 0 directly; no NCSD/cartridge header is needed.
    public static string BuildGameFromNcch(string originalNcch, string extracted, string mod,
        string work, Action<string, int> notify, CancellationToken cancel, string tool)
    {
        return BuildGameFromNcch(originalNcch,extracted,mod,work,notify,cancel,tool,false);
    }
    public static string BuildGameFromNcch(string originalNcch, string extracted, string mod,
        string work, Action<string, int> notify, CancellationToken cancel, string tool, bool compactWork)
    {
        originalNcch = Path.GetFullPath(originalNcch); extracted = Path.GetFullPath(extracted);
        mod = Path.GetFullPath(mod); work = Path.GetFullPath(work);
        CheckAncestors(originalNcch); CheckAncestors(extracted); CheckAncestors(mod); CheckAncestors(work);
        if (Overlap(extracted, mod) || Overlap(work, mod) || Overlap(work, extracted) ||
            originalNcch.StartsWith(Root(work), StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("NCCH rebuild paths overlap.");
        BuildSupport.CreateExclusiveDirectory(work);
        tool = Path.GetFullPath(tool); CheckAncestors(tool);
        if (FileHash(tool, cancel) != ToolExeSha) throw new InvalidDataException("ROM rebuilding tool checksum mismatch.");
        if(work.Length + 32 >= 260 || originalNcch.Length >= 260)
            throw new IOException("Choose shorter rebuild paths.");
        foreach(var file in Inventory(Path.Combine(extracted, "romfs"), cancel))
            if(Path.Combine(work, "verify-romfs", file.Key).Length >= 260)
                throw new IOException("A game file exceeds the rebuilding tool's path limit.");
        foreach(var file in Inventory(Path.Combine(mod, "romfs"), cancel))
            if(Path.Combine(work, "verify-romfs", file.Key).Length >= 260)
                throw new IOException("A generated game file exceeds the rebuilding tool's path limit.");
        using(var inputLock = new FileStream(originalNcch, FileMode.Open, FileAccess.Read, FileShare.Read))
        {
            string sourceHash = FileHash(originalNcch, cancel);
            string privateNcch = Path.Combine(work, "source.cxi");
            CreatePlaintextGameCopy(originalNcch, extracted, privateNcch, cancel);
            if(compactWork)File.Delete(Path.Combine(extracted,"romfs.bin"));
            string result = BuildNcchCore(privateNcch, extracted, mod, work, notify ?? delegate {}, cancel, tool,compactWork);
            if(FileHash(originalNcch, cancel) != sourceHash) throw new IOException("Original content changed.");
            return result;
        }
    }

    public static string Build(string rom, string extracted, string mod, Action<string, int> notify, CancellationToken cancel, string tool)
    {
        rom = Path.GetFullPath(rom); extracted = Path.GetFullPath(extracted); mod = Path.GetFullPath(mod);
        CheckAncestors(rom); CheckAncestors(extracted); CheckAncestors(mod);
        if (!Directory.Exists(extracted) || !Directory.Exists(mod)) throw new DirectoryNotFoundException("Extraction or mod folder does not exist.");
        if (Overlap(extracted, mod) || rom.StartsWith(Root(extracted), StringComparison.OrdinalIgnoreCase) || rom.StartsWith(Root(mod), StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("ROM input, extraction, and output paths must not overlap.");
        string final = Path.Combine(mod, "DQXI-English.3ds"); string partial = final + ".partial";
        if (File.Exists(final) || File.Exists(partial)) throw new IOException("ROM output already exists; choose a fresh output folder.");
        // A read-only share lock prevents input-ROM mutation for the entire reconstruction.
        using (var inputLock = new FileStream(rom, FileMode.Open, FileAccess.Read, FileShare.Read))
        {
            string inputRomHash = FileHash(rom, cancel);
            var originalParts = ReadPartitions(rom);
            string folder = Path.Combine(extracted, "r-" + Guid.NewGuid().ToString("N").Substring(0,12));
            BuildSupport.CreateExclusiveDirectory(folder); string log = Path.Combine(folder, "rebuild.log");
            // Pinned 3dstool uses legacy file APIs. Reject long paths before extraction,
            // without modifying Windows policy or relaxing filesystem verification.
            if(partial.Length>=260 || rom.Length>=260 || folder.Length+32>=260)
                throw new IOException("Choose a shorter output parent path for the ROM rebuilding tool.");
            foreach(var file in Inventory(Path.Combine(extracted,"romfs"),cancel))
                if(Path.Combine(folder,"verify-romfs",file.Key).Length>=260)
                    throw new IOException("Choose a shorter output parent path; a game file exceeds the rebuilding tool's path limit.");
            Action<string, int> progress = notify ?? delegate { };
            Action<string[]> run = delegate(string[] toolArguments)
            {
                cancel.ThrowIfCancellationRequested();
                BuildSupport.RunTool(tool, toolArguments, folder, log, cancel);
                cancel.ThrowIfCancellationRequested();
            };
            progress("Preparing the ROM rebuilding tool...", 66);
            if (String.IsNullOrEmpty(tool)) tool = BuildSupport.FetchTool(ToolUrl, ToolZipSha, "3dstool.exe", Path.Combine(folder, "tool"), cancel);
            tool = Path.GetFullPath(tool); CheckAncestors(tool);
            if (FileHash(tool, cancel) != ToolExeSha) throw new InvalidDataException("ROM rebuilding tool checksum mismatch.");
            var parts = new SortedDictionary<int, string>();
            var args = new List<string> { "-x", "-t", "cci", "-f", rom, "--header", Path.Combine(folder, "ncsd.bin") };
            foreach (int i in originalParts.Keys)
            { parts.Add(i, Path.Combine(folder, "partition" + i + ".bin")); args.Add("--partition" + i); args.Add(parts[i]); }
            progress("Preserving the original cartridge partitions...", 69); run(args.ToArray());
            // Verify all external extraction results before private flag normalization.
            foreach (var pair in originalParts)
                if (new FileInfo(parts[pair.Key]).Length != pair.Value.Size || !Equal(HashRange(rom, pair.Value.Offset, pair.Value.Size, cancel), HashRange(parts[pair.Key], 0, pair.Value.Size, cancel)))
                    throw new InvalidDataException("Original cartridge partition extraction failed verification.");
            if (NormalizePrivateHeader(parts[0], cancel)) progress("Corrected a verified plaintext flag in the private working copy.", 71);
            string rebuiltGame = BuildNcchCore(parts[0], extracted, mod, folder, progress, cancel, tool,false);
            progress("Writing the translated .3ds file...", 91); parts[0] = rebuiltGame;
            args = new List<string> { "-c", "-t", "cci", "-f", partial, "--header", Path.Combine(folder, "ncsd.bin"), "--not-pad" };
            foreach (var part in parts) { args.Add("--partition" + part.Key); args.Add(part.Value); }
            run(args.ToArray()); progress("Verifying the rebuilt cartridge and preserved partitions...", 96);
            var rebuiltParts = ReadPartitions(partial);
            if (rebuiltParts.Count != originalParts.Count) throw new InvalidDataException("Cartridge partition set changed.");
            foreach (var pair in originalParts)
            {
                cancel.ThrowIfCancellationRequested(); Part output;
                if (!rebuiltParts.TryGetValue(pair.Key, out output)) throw new InvalidDataException("Cartridge partition set changed.");
                string expected = parts[pair.Key];
                byte[] actualHash = HashRange(partial, output.Offset, output.Size, cancel);
                if (output.Size != new FileInfo(expected).Length || !Equal(actualHash, HashRange(expected, 0, output.Size, cancel))) throw new InvalidDataException("Rebuilt partition verification failed.");
                if (pair.Key != 0 && !Equal(actualHash, HashRange(rom, pair.Value.Offset, pair.Value.Size, cancel))) throw new InvalidDataException("An unrelated cartridge partition changed.");
            }
            if (FileHash(rom, cancel) != inputRomHash) throw new IOException("Original cartridge changed during reconstruction.");
            cancel.ThrowIfCancellationRequested();
            // File.Move refuses an existing destination. Partial output is never advertised as usable.
            File.Move(partial, final); progress("Verified cartridge ready for hardware testing.", 100); return final;
        }
    }
}
