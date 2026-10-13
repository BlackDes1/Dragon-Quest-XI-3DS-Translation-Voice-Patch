using System;
using System.IO;
using System.Text;
using System.Collections.Generic;
using System.Security.Cryptography;

// C#5 synthetic harness. Root must compile/run independently; no game data.
public static class CodecTests {
 static int count;
 static void Equal(byte[] a,byte[] b){count++;if(a.Length!=b.Length)throw new Exception("Length mismatch");for(int i=0;i<a.Length;i++)if(a[i]!=b[i])throw new Exception("Byte mismatch");}
 static void Reject(Action a){count++;try{a();}catch(InvalidDataException){return;}throw new Exception("Malformed fixture accepted");}
 static byte[] Hash(byte[] b){using(SHA256 h=SHA256.Create())return h.ComputeHash(b);}
 static void U64(List<byte> b,ulong n){for(int i=0;i<8;i++){b.Add((byte)n);n>>=8;}}
 static byte[] Zlib(byte[] raw,byte[] plain){List<byte> b=new List<byte>();b.Add(0x78);b.Add(0x01);b.AddRange(raw);uint a=1,c=0;foreach(byte v in plain){a=(a+v)%65521;c=(c+a)%65521;}uint sum=(c<<16)|a;for(int i=3;i>=0;i--)b.Add((byte)(sum>>(i*8)));return b.ToArray();}
 static byte[] Stored(byte[] data){if(data.Length>65535)throw new Exception();List<byte>b=new List<byte>();b.Add(1);b.Add((byte)data.Length);b.Add((byte)(data.Length>>8));int n=65535-data.Length;b.Add((byte)n);b.Add((byte)(n>>8));b.AddRange(data);return Zlib(b.ToArray(),data);}
 sealed class Writer { public List<byte> Bytes=new List<byte>();int value,bits;public void Put(int v,int n){for(int i=0;i<n;i++){value|=((v>>i)&1)<<bits;if(++bits==8){Bytes.Add((byte)value);value=bits=0;}}}public byte[] Done(){if(bits!=0){Bytes.Add((byte)value);bits=value=0;}return Bytes.ToArray();}}
 static int Reverse(int n,int bits){int r=0;while(bits-->0){r=(r<<1)|(n&1);n>>=1;}return r;}
 static void FixedSymbol(Writer w,int symbol){int n,code;if(symbol<144){n=8;code=48+symbol;}else if(symbol<256){n=9;code=400+symbol-144;}else if(symbol<280){n=7;code=symbol-256;}else{n=8;code=192+symbol-280;}w.Put(Reverse(code,n),n);}
 static byte[] Fixed(byte[] plain){Writer w=new Writer();w.Put(1,1);w.Put(1,2);foreach(byte c in plain)FixedSymbol(w,c);FixedSymbol(w,256);return Zlib(w.Done(),plain);}
 static byte[] Dynamic(){Writer w=new Writer();w.Put(1,1);w.Put(2,2);w.Put(0,5);w.Put(0,5);w.Put(14,4);int[] order={16,17,18,0,8,7,9,6,10,5,11,4,12,3,13,2,14,1};foreach(int s in order)w.Put(s==0||s==1?1:0,3);for(int i=0;i<258;i++)w.Put(i==0||i==256?1:0,1);w.Put(0,1);w.Put(0,1);w.Put(1,1);return Zlib(w.Done(),new byte[]{0,0});}
 static byte[] DynamicRepeats(int zeros,bool overflow){Writer w=new Writer();w.Put(1,1);w.Put(2,2);w.Put(0,5);w.Put(0,5);w.Put(14,4);int[] order={16,17,18,0,8,7,9,6,10,5,11,4,12,3,13,2,14,1};foreach(int s in order)w.Put(s==18?1:s==0||s==1?2:0,3);
  // Canonical code lengths: symbol18=0, symbol0=10, symbol1=11.
  w.Put(3,2);w.Put(0,1);w.Put(127,7);w.Put(0,1);w.Put(overflow?127:106,7);w.Put(3,2);w.Put(1,2);
  for(int i=0;i<zeros;i++)w.Put(0,1);w.Put(1,1);return Zlib(w.Done(),new byte[zeros]);}
 static byte[] BadDynamic(int kind){Writer w=new Writer();w.Put(1,1);w.Put(2,2);w.Put(0,5);w.Put(0,5);w.Put(0,4);
  // First four code-length symbols16/17/18/0. kind0 oversubscribes, kind1 incomplete.
  for(int i=0;i<4;i++)w.Put(kind==0?1:i==3?2:0,3);return Zlib(w.Done(),new byte[0]);}
 static byte[] DynamicAllRepeatCodes(){Writer w=new Writer();w.Put(1,1);w.Put(2,2);w.Put(0,5);w.Put(0,5);w.Put(10,4);int[] order={16,17,18,0,8,7,9,6,10,5,11,4,12,3};foreach(int s in order)w.Put(s==16||s==17||s==18?2:s==0||s==3?3:0,3);
  // Seven length3 literal codes then 249 zeros, EOB length3 and empty distance.
  // Code16=00,17=01,18=10,0=110,3=111 (transmitted MSB first).
  w.Put(7,3);w.Put(0,2);w.Put(3,2);w.Put(1,2);w.Put(127,7);w.Put(1,2);w.Put(97,7);w.Put(2,2);w.Put(0,3);w.Put(7,3);w.Put(3,3);
  w.Put(0,3);w.Put(7,3);return Zlib(w.Done(),new byte[]{0});}
 static byte[] FixedBadDistance(int symbol,bool priorLiteral){Writer w=new Writer();w.Put(1,1);w.Put(1,2);if(priorLiteral)FixedSymbol(w,97);FixedSymbol(w,257);w.Put(Reverse(symbol,5),5);FixedSymbol(w,256);return Zlib(w.Done(),new byte[0]);}
 static byte[] StoredBlocks(byte[] first,byte[] second){List<byte> raw=new List<byte>();foreach(byte[] block in new byte[][]{first,second}){raw.Add((byte)(Object.ReferenceEquals(block,second)?1:0));raw.Add((byte)block.Length);raw.Add((byte)(block.Length>>8));int inv=65535-block.Length;raw.Add((byte)inv);raw.Add((byte)(inv>>8));raw.AddRange(block);}List<byte> plain=new List<byte>(first);plain.AddRange(second);return Zlib(raw.ToArray(),plain.ToArray());}
 static byte[] Delta(byte[] source,byte[] target,byte[] commands,bool fixedTree){List<byte> b=new List<byte>(Encoding.ASCII.GetBytes("DQDP1"));b.AddRange(Hash(source));b.AddRange(Hash(target));U64(b,(ulong)target.Length);b.AddRange(fixedTree?Fixed(commands):Stored(commands));return b.ToArray();}
 static byte[] Append(byte[] a,byte v){byte[] b=new byte[a.Length+1];Buffer.BlockCopy(a,0,b,0,a.Length);b[a.Length]=v;return b;}
 public static int Run(){count=0;try{
  byte[] hello=Encoding.ASCII.GetBytes("Hello, native codecs!"),empty=new byte[0];Equal(hello,NativeCodecs.InflateZlib(Stored(hello),0));Equal(hello,NativeCodecs.InflateZlib(Fixed(hello),0));Equal(new byte[]{0,0},NativeCodecs.InflateZlib(Dynamic(),0));Equal(empty,NativeCodecs.InflateZlib(Stored(empty),0));
  Writer copy=new Writer();copy.Put(1,1);copy.Put(1,2);FixedSymbol(copy,97);FixedSymbol(copy,257);copy.Put(0,5);FixedSymbol(copy,256);Equal(Encoding.ASCII.GetBytes("aaaa"),NativeCodecs.InflateZlib(Zlib(copy.Done(),Encoding.ASCII.GetBytes("aaaa")),0));
  Reject(delegate{NativeCodecs.InflateZlib(Append(Stored(hello),0),0);});byte[] bad=Stored(hello);bad[bad.Length-1]^=1;Reject(delegate{NativeCodecs.InflateZlib(bad,0);});Reject(delegate{NativeCodecs.InflateZlib(new byte[]{0x78,1,7,0,0,0,1},0);});byte[] truncated=Stored(hello);Array.Resize(ref truncated,truncated.Length-1);Reject(delegate{NativeCodecs.InflateZlib(truncated,0);});
  byte[] source=Encoding.ASCII.GetBytes("base"),target=Encoding.ASCII.GetBytes("target"),cmd=new byte[]{1,6,0,0,0,116,97,114,103,101,116};Equal(target,NativeCodecs.ApplyDelta(source,Delta(source,target,cmd,false)));Equal(target,NativeCodecs.ApplyDelta(source,Delta(source,target,cmd,true)));
  List<byte> cc=new List<byte>();cc.Add(0);U64(cc,1);U64(cc,2);Equal(Encoding.ASCII.GetBytes("as"),NativeCodecs.ApplyDelta(source,Delta(source,Encoding.ASCII.GetBytes("as"),cc.ToArray(),false)));
  Reject(delegate{NativeCodecs.ApplyDelta(hello,Delta(source,target,cmd,false));});Reject(delegate{NativeCodecs.ApplyDelta(source,Delta(source,target,new byte[]{3},false));});Reject(delegate{NativeCodecs.ApplyDelta(source,Delta(source,target,new byte[]{1,255,255,255,255},false));});Reject(delegate{NativeCodecs.ApplyDelta(source,Delta(source,target,new byte[]{0},false));});Reject(delegate{NativeCodecs.ApplyDelta(source,Delta(source,source,cmd,false));});
  Equal(source,NativeCodecs.ApplyIps(source,Encoding.ASCII.GetBytes("PATCHEOF")));Equal(Encoding.ASCII.GetBytes("bZZe"),NativeCodecs.ApplyIps(source,new byte[]{80,65,84,67,72,0,0,1,0,0,0,2,90,69,79,70}));Reject(delegate{NativeCodecs.ApplyIps(source,Encoding.ASCII.GetBytes("PATCHEOFx"));});Reject(delegate{NativeCodecs.ApplyIps(source,new byte[]{80,65,84,67,72,0,0,4,0,1,90,69,79,70});});Reject(delegate{NativeCodecs.ApplyIps(source,new byte[]{80,65,84,67,72,0,0,1,0,2,90});});
  Equal(source,NativeCodecs.Normalize(source));Reject(delegate{NativeCodecs.Normalize(Encoding.ASCII.GetBytes("PACA"));});
  byte[] allBytes=new byte[256];for(int i=0;i<256;i++)allBytes[i]=(byte)i;Equal(allBytes,NativeCodecs.InflateZlib(Fixed(allBytes),0));Equal(Encoding.ASCII.GetBytes("onetwo"),NativeCodecs.InflateZlib(StoredBlocks(Encoding.ASCII.GetBytes("one"),Encoding.ASCII.GetBytes("two")),0));Equal(new byte[4096],NativeCodecs.InflateZlib(DynamicRepeats(4096,false),0));
  Equal(new byte[]{0},NativeCodecs.InflateZlib(DynamicAllRepeatCodes(),0));
  Reject(delegate{NativeCodecs.InflateZlib(DynamicRepeats(0,true),0);});Reject(delegate{NativeCodecs.InflateZlib(BadDynamic(0),0);});Reject(delegate{NativeCodecs.InflateZlib(BadDynamic(1),0);});Reject(delegate{NativeCodecs.InflateZlib(FixedBadDistance(30,true),0);});Reject(delegate{NativeCodecs.InflateZlib(FixedBadDistance(0,false),0);});
  byte[] badStored=Stored(hello);badStored[5]^=1;Reject(delegate{NativeCodecs.InflateZlib(badStored,0);});Reject(delegate{NativeCodecs.InflateZlib(new byte[]{0x78,0x20,0,0,0,0},0);});Reject(delegate{NativeCodecs.InflateZlib(Stored(hello),-1);});
  byte[] bigTarget=Delta(source,target,cmd,false);bigTarget[69]=1;bigTarget[70]=0;bigTarget[71]=0;bigTarget[72]=16;Reject(delegate{NativeCodecs.ApplyDelta(source,bigTarget);});List<byte> maxCopy=new List<byte>();maxCopy.Add(0);U64(maxCopy,UInt64.MaxValue);U64(maxCopy,UInt64.MaxValue);Reject(delegate{NativeCodecs.ApplyDelta(source,Delta(source,target,maxCopy.ToArray(),false));});
  Reject(delegate{NativeCodecs.ApplyIps(source,new byte[]{80,65,84,67,72,0,0,1,0,0,0,9,90,69,79,70});});Reject(delegate{NativeCodecs.ApplyIps(source,new byte[]{80,65,84,67,72,0,0,1,0,0,0});});
  // BLZ emits a,b,c then an overlapping distance3 length11 reference in reverse.
  byte[] blz=new byte[]{80,65,67,65,0,128,99,98,97,16,14,0,0,8,0,0,0,0};
  Equal(Encoding.ASCII.GetBytes("PACKbacbacbacbacba"),NativeCodecs.Normalize(blz));
  byte[] invalidBlz=(byte[])blz.Clone();invalidBlz[10]=255;
  Reject(delegate{NativeCodecs.Normalize(invalidBlz);});
  byte[] tooBigBlz=(byte[])blz.Clone();tooBigBlz[17]=16;Reject(delegate{NativeCodecs.Normalize(tooBigBlz);});byte[] badDistanceBlz=(byte[])blz.Clone();badDistanceBlz[4]=255;badDistanceBlz[5]=143;Reject(delegate{NativeCodecs.Normalize(badDistanceBlz);});
  Console.WriteLine("Synthetic checks PASS: "+count);return 0;
 }catch(Exception e){Console.Error.WriteLine(e);return 1;}}
}
