using System;
using System.IO;
using System.Text;
using System.Security.Cryptography;
using System.Threading;

public static class CiaSourceTests {
    static int checks;
    static void Check(bool value,string label) { checks++;if(!value)throw new Exception(label); }
    static void Reject(Action action,string label) {
        checks++;try {action();}catch(InvalidDataException){return;}throw new Exception("Accepted "+label);
    }
    static void Be32(byte[] b,int at,uint value){for(int i=3;i>=0;i--){b[at+i]=(byte)value;value>>=8;}}
    static void Be16(byte[] b,int at,int value){b[at]=(byte)(value>>8);b[at+1]=(byte)value;}
    static void Be64(byte[] b,int at,ulong value){for(int i=7;i>=0;i--){b[at+i]=(byte)value;value>>=8;}}
    static int TmdBody(uint signature) {
        if(signature==0x00010000 || signature==0x00010003)return 0x240;
        if(signature==0x00010001 || signature==0x00010004)return 0x140;
        if(signature==0x00010002 || signature==0x00010005)return 0x80;
        throw new ArgumentException("Unsupported test TMD signature.");
    }
    static byte[] Fixture(int[] indices,byte[][] content) { return Fixture(indices,content,0x00010004); }
    static byte[] Fixture(int[] indices,byte[][] content,uint signature) {
        int body=TmdBody(signature);byte[] b=new byte[body+0x9c4+indices.Length*0x30];Be32(b,0,signature);Be64(b,body+0x4c,CiaSupport.TitleId);Be16(b,body+0x9c,37);Be16(b,body+0x9e,indices.Length);
        for(int i=0;i<indices.Length;i++){
            int at=body+0x9c4+i*0x30;Be32(b,at,(uint)(23+i));Be16(b,at+4,indices[i]);Be64(b,at+8,(ulong)content[i].Length);
            using(var sha=SHA256.Create())Buffer.BlockCopy(sha.ComputeHash(content[i]),0,b,at+16,32);
        }return b;
    }
    public static int Main(string[] args) {
        string root=Path.Combine(Path.GetTempPath(),"dqxi-source-tests-"+Guid.NewGuid().ToString("N"));Directory.CreateDirectory(root);
        try {
            var a=Encoding.ASCII.GetBytes("game fixture");var b=Encoding.ASCII.GetBytes("manual fixture");
            string tmd=Path.Combine(root,"source.tmd");string prefix=Path.Combine(root,"content");
            File.WriteAllBytes(tmd,Fixture(new int[]{0,1},new byte[][]{a,b}));
            var source=CiaSupport.ReadTmd(tmd,prefix);Check(source.TitleVersion==37,"title version");Check(source.Contents.Length==2,"all contents");Check(source.Contents[1].Id==24 && source.Contents[1].Index==1,"manual index/id");
            foreach(uint signature in new uint[]{0x00010000,0x00010001,0x00010002,0x00010003,0x00010004,0x00010005}) {
                File.WriteAllBytes(tmd,Fixture(new int[]{0,1},new byte[][]{a,b},signature));
                source=CiaSupport.ReadTmd(tmd,prefix);Check(source.TitleVersion==37 && source.Contents.Length==2,"supported TMD signature "+signature.ToString("X8"));
            }
            File.WriteAllBytes(tmd,Fixture(new int[]{0,1},new byte[][]{a,b}));
            source=CiaSupport.ReadTmd(tmd,prefix);
            foreach(var row in source.Contents)File.WriteAllBytes(row.Path,row.Index==0?a:b);
            CiaSupport.VerifyContentFiles(source);checks++;
            File.AppendAllText(source.Contents[1].Path,"x");Reject(delegate{CiaSupport.VerifyContentFiles(source);},"corrupt content");
            File.WriteAllBytes(source.Contents[1].Path,b);b[0]^=1;File.WriteAllBytes(source.Contents[1].Path,b);Reject(delegate{CiaSupport.VerifyContentFiles(source);},"same-length corruption");
            CiaSupport.VerifyContentSizes(source);checks++; // No input digest gate.
            var invalid=Fixture(new int[]{0,0},new byte[][]{a,b});File.WriteAllBytes(tmd,invalid);Reject(delegate{CiaSupport.ReadTmd(tmd,prefix);},"duplicate index");
            invalid=Fixture(new int[]{1},new byte[][]{b});File.WriteAllBytes(tmd,invalid);Reject(delegate{CiaSupport.ReadTmd(tmd,prefix);},"missing game");
            invalid=Fixture(new int[]{0},new byte[][]{a});invalid[0x140+0x4c+7]^=1;File.WriteAllBytes(tmd,invalid);Reject(delegate{CiaSupport.ReadTmd(tmd,prefix);},"wrong title");
            invalid=Fixture(new int[]{0},new byte[][]{a});Array.Resize(ref invalid,invalid.Length-1);File.WriteAllBytes(tmd,invalid);Reject(delegate{CiaSupport.ReadTmd(tmd,prefix);},"truncated TMD");
            string cia=Path.Combine(root,"wrong.cia");File.WriteAllBytes(cia,a);Reject(delegate{CiaSupport.ValidateOriginal(cia,CancellationToken.None);},"truncated CIA header");
            byte[] bounded= new byte[0x2040+Fixture(new int[]{0},new byte[][]{a}).Length];
            byte[] validTmd=Fixture(new int[]{0},new byte[][]{a});
            Buffer.BlockCopy(BitConverter.GetBytes((uint)0x2020),0,bounded,0,4);Buffer.BlockCopy(BitConverter.GetBytes((uint)validTmd.Length),0,bounded,16,4);Buffer.BlockCopy(validTmd,0,bounded,0x2040,validTmd.Length);
            File.WriteAllBytes(cia,bounded);Check(CiaSupport.ValidateOriginal(cia,CancellationToken.None)=="0004000000199200","title accepted without fixed input hash");
            bounded[64]^=1;File.WriteAllBytes(cia,bounded);Check(CiaSupport.ValidateOriginal(cia,CancellationToken.None)=="0004000000199200","byte-different CIA not hash-whitelisted");
            bounded[0x2040+0x140+0x4c+7]^=1;File.WriteAllBytes(cia,bounded);Reject(delegate{CiaSupport.ValidateOriginal(cia,CancellationToken.None);},"wrong title before extraction");
            string pc=Path.Combine(root,"PC root with spaces");Directory.CreateDirectory(pc);Directory.CreateDirectory(Path.Combine(pc,"Game"));
            Check(CiaSupport.CheckPcInstallation(pc,new string[]{"Game/test.pak"},new string[]{"Game"}).Length==1,"missing pak");
            File.WriteAllBytes(Path.Combine(pc,"Game/test.pak"),new byte[0]);Check(CiaSupport.CheckPcInstallation(pc,new string[]{"Game/test.pak"},new string[]{"Game"}).Length==1,"empty pak");
            File.WriteAllBytes(Path.Combine(pc,"Game/test.pak"),a);Check(CiaSupport.CheckPcInstallation(pc,new string[]{"Game/test.pak"},new string[]{"Game"}).Length==0,"complete pc fixture");
            Reject(delegate{CiaSupport.CheckPcInstallation(pc,new string[]{"../escape"},new string[0]);},"PC traversal");
            string extKeys=Path.Combine(root,"ext_key.txt"),seedDb=Path.Combine(root,"seeddb.bin");
            File.WriteAllText(extKeys,"// Synthetic test seed, not game data\n0004000000199200 00112233445566778899aabbccddeeff\n");
            CiaSupport.WriteTitleSeedDatabase(extKeys,seedDb);
            byte[] db=File.ReadAllBytes(seedDb);
            Check(db.Length==48 && BitConverter.ToUInt32(db,0)==1 && BitConverter.ToUInt64(db,16)==CiaSupport.TitleId && db[24]==0 && db[39]==0xff,"local title seed database format");
            File.Delete(seedDb);File.WriteAllText(extKeys,"0004000000199200 BAD\n");
            Reject(delegate{CiaSupport.WriteTitleSeedDatabase(extKeys,seedDb);},"malformed seed entry");
            File.WriteAllText(extKeys,"0004000000000000 00112233445566778899aabbccddeeff\n");
            Reject(delegate{CiaSupport.WriteTitleSeedDatabase(extKeys,seedDb);},"missing title seed entry");
            if(args.Length!=0) {
                string work=Path.GetFullPath(args[0]);RomBuilder.ValidatePlaintextGame(Path.Combine(work,"game.cxi"),CancellationToken.None);checks++;
                string inputGame=Path.Combine(work,"game.cxi");RomBuilder.ValidateInputGame(inputGame);checks++;
                byte[] game=File.ReadAllBytes(inputGame);string regionFolder=Path.Combine(root,"regions");Directory.CreateDirectory(regionFolder);
                byte[] exheaderPart=new byte[0x800];Buffer.BlockCopy(game,512,exheaderPart,0,exheaderPart.Length);File.WriteAllBytes(Path.Combine(regionFolder,"exheader.bin"),exheaderPart);
                foreach(var region in new Tuple<int,string>[] {Tuple.Create(0x1a0,"exefs.bin"),Tuple.Create(0x1b0,"romfs.bin")}) {
                    int offset=(int)BitConverter.ToUInt32(game,region.Item1)*512,size=(int)BitConverter.ToUInt32(game,region.Item1+4)*512;
                    byte[] part=new byte[size];Buffer.BlockCopy(game,offset,part,0,size);File.WriteAllBytes(Path.Combine(regionFolder,region.Item2),part);
                }
                RomBuilder.ValidateExtractedGameParts(inputGame,regionFolder);checks++;
                game[0x160]^=1;game[0x1c0]^=1;game[0x1e0]^=1;game[0x18f]&=0xfb;
                string stale=Path.Combine(root,"stale-input.cxi");File.WriteAllBytes(stale,game);
                RomBuilder.ValidateInputGame(stale);checks++;
                Reject(delegate{RomBuilder.ValidatePlaintextGame(stale,CancellationToken.None);},"invalid generated-region digests");
                string prepared=Path.Combine(root,"prepared.cxi");RomBuilder.CreatePlaintextGameCopy(stale,regionFolder,prepared,CancellationToken.None);
                RomBuilder.ValidatePlaintextGame(prepared,CancellationToken.None);checks++;
                Check(BuildSupport.HashFile(stale)==BuildSupport.Hash(game),"input with stale metadata untouched");
                byte[] clean=File.ReadAllBytes(inputGame),preparedBytes=File.ReadAllBytes(prepared);
                clean[0x18f]=(byte)((clean[0x18f]|4)&~0x21);clean[0x18b]=0;
                Check(BuildSupport.Hash(clean)==BuildSupport.Hash(preparedBytes),"prepared plaintext game matches private reference");
                Reject(delegate{RomBuilder.CreatePlaintextGameCopy(stale,regionFolder,stale,CancellationToken.None);},"in-place source mutation");
                game[512+0x200]^=1;File.WriteAllBytes(stale,game);
                Reject(delegate{RomBuilder.ValidateInputGame(stale);},"encrypted or wrong-title ExHeader");game[512+0x200]^=1;
                int exefsAt=(int)BitConverter.ToUInt32(game,0x1a0)*512;
                game[exefsAt]=0xff;File.WriteAllBytes(stale,game);
                Reject(delegate{RomBuilder.ValidateInputGame(stale);},"unreadable ExeFS");game[exefsAt]=clean[exefsAt];
                int romfsAt=(int)BitConverter.ToUInt32(game,0x1b0)*512;game[romfsAt]^=1;File.WriteAllBytes(stale,game);
                Reject(delegate{RomBuilder.ValidateInputGame(stale);},"encrypted or missing IVFC");
                string stripped=Path.Combine(root,"stripped-manual.cfa");
                byte[] aux=File.ReadAllBytes(Path.Combine(work,"manual.cfa"));aux[0x18f]&=0xfb;File.WriteAllBytes(stripped,aux);
                string normalized=CiaSupport.NormalizeAuxiliaryContent(stripped,Path.Combine(root,"normalized-manual.cfa"));
                byte[] normalizedBytes=File.ReadAllBytes(normalized);Check((normalizedBytes[0x18f]&4)!=0,"plaintext auxiliary flag repaired");
                Check((File.ReadAllBytes(stripped)[0x18f]&4)==0,"auxiliary source untouched");
                aux[0x18f]=(byte)((aux[0x18f]|4)&~0x21);aux[0x18b]=0;
                Check(BuildSupport.Hash(aux)==BuildSupport.Hash(normalizedBytes),"only auxiliary crypto flags changed");
                RomBuilder.ValidateInputManual(normalized);checks++;
                aux[0x1e0]^=1;File.WriteAllBytes(stripped,aux);
                RomBuilder.ValidateInputManual(stripped);checks++;
                string repaired=CiaSupport.NormalizeAuxiliaryContent(stripped,Path.Combine(root,"repaired-manual.cfa"));
                Check(BuildSupport.Hash(File.ReadAllBytes(repaired))==BuildSupport.Hash(normalizedBytes),"stale auxiliary digest regenerated in private output");
                source=CiaSupport.ReadTmd(Path.Combine(work,"fixture.tmd"),Path.Combine(work,"readback"));CiaSupport.VerifyContentFiles(source);checks++;
                Check(source.TitleVersion==37 && source.Contents.Length==2 && source.Contents[0].Id==23 && source.Contents[1].Id==27,"real MakeROM/CTRTool metadata");
            }
            if(args.Length==3) {
                RomBuilder.ValidatePatchProfile(args[1],args[2]);checks++;
                byte[] code=File.ReadAllBytes(args[1]);string modified=Path.Combine(root,"modified-code.bin");
                code[0xc5328]^=1;File.WriteAllBytes(modified,code);
                Reject(delegate{RomBuilder.ValidatePatchProfile(modified,args[2]);},"wrong hook instruction");
                code[0xc5328]^=1;code[0x624200]=1;File.WriteAllBytes(modified,code);
                Reject(delegate{RomBuilder.ValidatePatchProfile(modified,args[2]);},"occupied voice code cave");
                code[0x624200]=0;code[0x100]^=1;File.WriteAllBytes(modified,code);
                RomBuilder.ValidatePatchProfile(modified,args[2]);checks++;
                byte[] header=File.ReadAllBytes(args[2]);header[0x200]^=1;string wrongHeader=Path.Combine(root,"wrong-exheader.bin");File.WriteAllBytes(wrongHeader,header);
                Reject(delegate{RomBuilder.ValidatePatchProfile(args[1],wrongHeader);},"wrong extended-header title");
            }
            Console.WriteLine("CIA/PC source checks PASS: "+checks);return 0;
        }catch(Exception e){Console.Error.WriteLine(e);return 1;}
        finally{Directory.Delete(root,true);}
    }
}
