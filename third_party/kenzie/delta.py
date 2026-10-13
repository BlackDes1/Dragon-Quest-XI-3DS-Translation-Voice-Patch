"""Small copy/literal delta codec. Inputs are required to reconstruct outputs."""
import hashlib
import struct
import zlib

MAGIC = b'DQDP1'
MAX_SIZE = 256 * 1024 * 1024


def sha(data):
    return hashlib.sha256(data).hexdigest()


def create(source, target):
    block = 32
    index = {}
    for i in range(0, len(source) - block + 1, block):
        index.setdefault(source[i:i+block], i)
    commands = bytearray()
    pending = bytearray()

    def flush():
        if pending:
            commands.extend(b'\1' + struct.pack('<I', len(pending)) + pending)
            pending.clear()

    pos = 0
    while pos < len(target):
        at = index.get(target[pos:pos+block]) if pos+block <= len(target) else None
        if at is None:
            pending.append(target[pos])
            pos += 1
            continue
        flush()
        length = block
        while at+length+1024 <= len(source) and pos+length+1024 <= len(target) and source[at+length:at+length+1024] == target[pos+length:pos+length+1024]:
            length += 1024
        while at+length < len(source) and pos+length < len(target) and source[at+length] == target[pos+length]:
            length += 1
        commands.extend(b'\0' + struct.pack('<QQ', at, length))
        pos += length
    flush()
    return MAGIC + bytes.fromhex(sha(source)) + bytes.fromhex(sha(target)) + struct.pack('<Q', len(target)) + zlib.compress(commands, 9)


def apply(source, patch):
    if len(patch) < 77 or patch[:5] != MAGIC:
        raise ValueError('Invalid delta header')
    if hashlib.sha256(source).digest() != patch[5:37]:
        raise ValueError('Wrong source file/version')
    size = struct.unpack_from('<Q', patch, 69)[0]
    if size > MAX_SIZE:
        raise ValueError('Target exceeds safety limit')
    decoder = zlib.decompressobj()
    data = decoder.decompress(patch[77:], MAX_SIZE+1)
    if len(data) > MAX_SIZE or not decoder.eof or decoder.unused_data:
        raise ValueError('Invalid or oversized delta stream')
    result = bytearray()
    p = 0
    while p < len(data):
        opcode = data[p]
        p += 1
        if opcode == 0:
            if p+16 > len(data):
                raise ValueError('Truncated copy command')
            at, length = struct.unpack_from('<QQ', data, p)
            p += 16
            if at+length > len(source) or len(result)+length > size:
                raise ValueError('Invalid copy bounds')
            result.extend(source[at:at+length])
        elif opcode == 1:
            if p+4 > len(data):
                raise ValueError('Truncated literal command')
            length = struct.unpack_from('<I', data, p)[0]
            p += 4
            if p+length > len(data) or len(result)+length > size:
                raise ValueError('Invalid literal bounds')
            result.extend(data[p:p+length])
            p += length
        else:
            raise ValueError('Unknown delta opcode')
    if len(result) != size or hashlib.sha256(result).digest() != patch[37:69]:
        raise ValueError('Reconstructed output verification failed')
    return bytes(result)
