using System;
using System.IO;
using System.Collections.Generic;
using System.Security.Cryptography;

// Managed C#5 codecs. No interpreter, native decoder, or permissive fallback.
public static class NativeCodecs {
 public const int MaxSize = 256 * 1024 * 1024;
 static Exception Bad(string s) { return new InvalidDataException(s); }
 static uint U32(byte[] b,int p) { if(p<0||p>b.Length-4)throw Bad("Truncated u32"); return (uint)b[p]|((uint)b[p+1]<<8)|((uint)b[p+2]<<16)|((uint)b[p+3]<<24); }
 static ulong U64(byte[] b,int p) { return U32(b,p)|((ulong)U32(b,p+4)<<32); }
 static bool Magic(byte[] b,int p,string s) { if(p<0||p>b.Length-s.Length)return false; for(int i=0;i<s.Length;i++)if(b[p+i]!=s[i])return false;return true; }
 static void HashMatch(byte[] data,byte[] expected,int p) { using(SHA256 h=SHA256.Create()){byte[] got=h.ComputeHash(data); int diff=0;for(int i=0;i<32;i++)diff|=got[i]^expected[p+i];if(diff!=0)throw Bad("SHA256 mismatch");} }
 public static byte[] Normalize(byte[] input) {
  if(input==null)throw new ArgumentNullException("input");
  if(!Magic(input,0,"PACA"))return (byte[])input.Clone();
  if(input.Length<8||input.Length>MaxSize)throw Bad("BLZ input size");
  uint footer=U32(input,input.Length-8),extra=U32(input,input.Length-4);int foot=(int)(footer>>24),compressed=(int)(footer&0xffffff);
  if(foot<8||foot>input.Length||compressed<foot||compressed>input.Length||(ulong)input.Length+extra>MaxSize)throw Bad("Invalid BLZ footer");
  byte[] output=new byte[input.Length+(int)extra];int si=input.Length-foot-1,oi=output.Length-1,read=0,end=compressed-foot;
  Func<int> next=delegate {if(si<0)throw Bad("BLZ source exhausted");read++;return input[si--];};
  Action<int> emit=delegate(int value){if(oi<0)throw Bad("BLZ output overflow");output[oi--]=(byte)value;};
  int code=next(),bits=8;
  while(read<end){if(bits==0){code=next();bits=8;}bits--;if(((code>>bits)&1)==0){emit(next());continue;}
   int a=next(),b=next(),length=(a>>4)+3,distance=(((a&15)<<8)|b)+3;
   if(distance>output.Length-1-oi)throw Bad("Invalid BLZ displacement");
   for(int j=0;j<length;j++){if(oi<0)throw Bad("BLZ output overflow");emit(output[oi+distance]);}
  }
  while(si>=0)emit(next());if(oi!=-1)throw Bad("BLZ short output");
  if(output.Length<4)throw Bad("BLZ missing expanded magic");output[0]=80;output[1]=65;output[2]=67;output[3]=75;return output;
 }
 public static byte[] ApplyDelta(byte[] source,byte[] patch) {
  if(source==null||patch==null)throw new ArgumentNullException();
  if(patch.Length<77||!Magic(patch,0,"DQDP1"))throw Bad("Delta header");HashMatch(source,patch,5);
  ulong size=U64(patch,69);if(size>MaxSize)throw Bad("Delta target limit");
  byte[] commands=InflateZlib(patch,77);byte[] result=new byte[(int)size];int p=0,write=0;
  while(p<commands.Length){int op=commands[p++];if(op==0){ulong at=U64(commands,p),n=U64(commands,p+8);p+=16;
    if(at>(ulong)source.Length||n>(ulong)source.Length-at||n>size-(ulong)write)throw Bad("Delta copy bounds");Buffer.BlockCopy(source,(int)at,result,write,(int)n);write+=(int)n;
   }else if(op==1){uint n=U32(commands,p);p+=4;if(n>(uint)(commands.Length-p)||(ulong)n>size-(ulong)write)throw Bad("Delta literal bounds");Buffer.BlockCopy(commands,p,result,write,(int)n);p+=(int)n;write+=(int)n;
   }else throw Bad("Unknown delta opcode");
  }
  if(write!=result.Length)throw Bad("Delta short output");HashMatch(result,patch,37);return result;
 }
 public static byte[] ApplyIps(byte[] source,byte[] patch) {
  if(source==null||patch==null)throw new ArgumentNullException();if(!Magic(patch,0,"PATCH"))throw Bad("IPS header");byte[] r=(byte[])source.Clone();int p=5;
  while(p<=patch.Length-3){if(Magic(patch,p,"EOF")){if(p+3!=patch.Length)throw Bad("IPS trailing/truncation footer");return r;}
   if(p>patch.Length-5)throw Bad("IPS truncated record");int at=(patch[p]<<16)|(patch[p+1]<<8)|patch[p+2],n=(patch[p+3]<<8)|patch[p+4];p+=5;
   if(n!=0){if(n>patch.Length-p||at>r.Length-n)throw Bad("IPS literal bounds");Buffer.BlockCopy(patch,p,r,at,n);p+=n;}
   else {if(p>patch.Length-3)throw Bad("IPS truncated run");n=(patch[p]<<8)|patch[p+1];byte value=patch[p+2];p+=3;if(at>r.Length-n)throw Bad("IPS run bounds");for(int j=0;j<n;j++)r[at+j]=value;}
  }throw Bad("IPS missing EOF");
 }
 sealed class Bits {
  public byte[] Data;public int Pos,Bit;public Bits(byte[] d,int p){Data=d;Pos=p;}
  public int Read(int n){int v=0;for(int i=0;i<n;i++){if(Pos>=Data.Length)throw Bad("Deflate truncated");v|=((Data[Pos]>>Bit)&1)<<i;if(++Bit==8){Bit=0;Pos++;}}return v;}
  public void Align(){if(Bit!=0){Bit=0;Pos++;}}
 }
 sealed class Tree {
  Dictionary<int,int> codes=new Dictionary<int,int>();int max;
  public Tree(int[] lengths,bool codeLengths,bool allowEmpty){int[] counts=new int[16];for(int i=0;i<lengths.Length;i++){int n=lengths[i];if(n<0||n>15)throw Bad("Huffman length");if(n>0){counts[n]++;max=Math.Max(max,n);}}
   if(max==0){if(!allowEmpty)throw Bad("Empty Huffman tree");return;}
   int left=1;for(int i=1;i<=15;i++){left=(left<<1)-counts[i];if(left<0)throw Bad("Oversubscribed Huffman tree");}
   if(left>0&&(codeLengths||max!=1))throw Bad("Incomplete Huffman tree");
   int[] next=new int[16];int code=0;for(int i=1;i<=15;i++){code=(code+counts[i-1])<<1;next[i]=code;}for(int i=0;i<lengths.Length;i++){int n=lengths[i];if(n>0)codes.Add((n<<16)|next[n]++,i);}
  }
  public int Decode(Bits b){int code=0;for(int n=1;n<=max;n++){code=(code<<1)|b.Read(1);int symbol;if(codes.TryGetValue((n<<16)|code,out symbol))return symbol;}throw Bad("Invalid Huffman code");}
 }
 static readonly int[] LB={3,4,5,6,7,8,9,10,11,13,15,17,19,23,27,31,35,43,51,59,67,83,99,115,131,163,195,227,258};
 static readonly int[] LE={0,0,0,0,0,0,0,0,1,1,1,1,2,2,2,2,3,3,3,3,4,4,4,4,5,5,5,5,0};
 static readonly int[] DB={1,2,3,4,5,7,9,13,17,25,33,49,65,97,129,193,257,385,513,769,1025,1537,2049,3073,4097,6145,8193,12289,16385,24577};
 static readonly int[] DE={0,0,0,0,1,1,2,2,3,3,4,4,5,5,6,6,7,7,8,8,9,9,10,10,11,11,12,12,13,13};
 // Strict RFC1950/1951 reader tracks exact compressed end, unlike DeflateStream.
 public static byte[] InflateZlib(byte[] data,int start) {
  if(data==null||start<0||start>data.Length-6)throw Bad("Zlib truncated");int cmf=data[start],flg=data[start+1];
  if((cmf&15)!=8||(cmf>>4)>7||((cmf<<8)|flg)%31!=0||(flg&32)!=0)throw Bad("Unsupported zlib header/dictionary");
  Bits b=new Bits(data,start+2);using(MemoryStream output=new MemoryStream()){bool final=false;
   while(!final){final=b.Read(1)!=0;int type=b.Read(2);
    if(type==0){b.Align();int n=b.Read(16),inv=b.Read(16);if((n^inv)!=65535)throw Bad("Deflate stored length");for(int i=0;i<n;i++)Put(output,b.Read(8));continue;}
    if(type==3)throw Bad("Deflate reserved block");Tree lit,dist;
    if(type==1){int[] l=new int[288],d=new int[32];for(int i=0;i<288;i++)l[i]=i<144?8:i<256?9:i<280?7:8;for(int i=0;i<32;i++)d[i]=5;lit=new Tree(l,false,false);dist=new Tree(d,false,false);}
    else {int nl=b.Read(5)+257,nd=b.Read(5)+1,nc=b.Read(4)+4;if(nl>286)throw Bad("Deflate literal count");int[] order={16,17,18,0,8,7,9,6,10,5,11,4,12,3,13,2,14,1,15},cl=new int[19];for(int i=0;i<nc;i++)cl[order[i]]=b.Read(3);Tree ct=new Tree(cl,true,false);int[] all=new int[nl+nd];int at=0;
     while(at<all.Length){int sym=ct.Decode(b),repeat,value;if(sym<16){all[at++]=sym;continue;}if(sym==16){if(at==0)throw Bad("Deflate repeat without prior");repeat=b.Read(2)+3;value=all[at-1];}else if(sym==17){repeat=b.Read(3)+3;value=0;}else if(sym==18){repeat=b.Read(7)+11;value=0;}else throw Bad("Deflate code-length symbol");if(repeat>all.Length-at)throw Bad("Deflate repeat overflow");while(repeat-->0)all[at++]=value;}
     int[] l=new int[nl],d=new int[nd];Array.Copy(all,0,l,0,nl);Array.Copy(all,nl,d,0,nd);if(l[256]==0)throw Bad("Deflate missing EOB");lit=new Tree(l,false,false);dist=new Tree(d,false,true);
    }
    for(;;){int symbol=lit.Decode(b);if(symbol<256){Put(output,symbol);continue;}if(symbol==256)break;if(symbol>285)throw Bad("Reserved length code");int k=symbol-257,n=LB[k]+b.Read(LE[k]),ds=dist.Decode(b);if(ds>29)throw Bad("Reserved distance code");int distance=DB[ds]+b.Read(DE[ds]);if(distance>output.Length||distance>(1<<(8+(cmf>>4))))throw Bad("Deflate distance bounds");for(int i=0;i<n;i++){int index=(int)output.Length-distance;Put(output,output.GetBuffer()[index]);}}
   }
   b.Align();if(b.Pos!=data.Length-4)throw Bad("Zlib trailing or truncated stream");uint expected=((uint)data[b.Pos]<<24)|((uint)data[b.Pos+1]<<16)|((uint)data[b.Pos+2]<<8)|data[b.Pos+3];byte[] result=output.ToArray();uint a=1,c=0;for(int i=0;i<result.Length;i++){a=(a+result[i])%65521;c=(c+a)%65521;}if(((c<<16)|a)!=expected)throw Bad("Zlib Adler32 mismatch");return result;
  }
 }
 static void Put(MemoryStream s,int value){if(s.Length>=MaxSize)throw Bad("Inflated stream size limit");s.WriteByte((byte)value);}
}
