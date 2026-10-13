"""Convert an uncompressed mono PCM16 WAV into a non-looping BCSTM.

Usage: python wav_to_bcstm_pcm16.py input.wav output.bcstm
Diagnostic PCM16 encoder; this does not inject voices into DQXI.
"""
import argparse
import struct
import wave
from pathlib import Path


def convert(source, destination):
    if source.resolve() == destination.resolve():
        raise ValueError('Input and output must be different files')
    with wave.open(str(source), 'rb') as w:
        if w.getnchannels() != 1 or w.getsampwidth() != 2 or w.getcomptype() != 'NONE':
            raise ValueError('Input must be mono, uncompressed PCM16 WAV')
        rate, samples = w.getframerate(), w.getnframes()
        pcm = w.readframes(samples)
    if not samples or len(pcm) != samples * 2:
        raise ValueError('Empty or truncated WAV')
    block_samples = 4096
    blocks = (samples + block_samples - 1) // block_samples
    last_samples = samples - (blocks - 1) * block_samples
    last_bytes = last_samples * 2
    last_padded = (last_bytes + 31) // 32 * 32
    info = bytearray(192)
    info[:4] = b'INFO'
    struct.pack_into('<I', info, 4, len(info))
    struct.pack_into('<HHI', info, 8, 0x4100, 0, 24)
    struct.pack_into('<HHI', info, 16, 0, 0, 0xffffffff)
    struct.pack_into('<HHI', info, 24, 0x0101, 0, 100)
    info[32:36] = bytes([1, 0, 1, 0])
    struct.pack_into('<11I', info, 36, rate, 0, samples, blocks, 8192,
                     block_samples, last_bytes, last_samples, last_padded, 0, block_samples)
    struct.pack_into('<HHI', info, 80, 0x1f00, 0, 24)
    struct.pack_into('<I', info, 108, 1)
    struct.pack_into('<HHI', info, 112, 0x4102, 0, 12)
    struct.pack_into('<HHI', info, 120, 0, 0, 0xffffffff)
    data = bytearray(b'DATA' + b'\0' * 28)
    data.extend(pcm)
    data.extend(b'\0' * (last_padded - last_bytes))
    struct.pack_into('<I', data, 4, len(data))
    header = bytearray(64)
    header[:4] = b'CSTM'
    struct.pack_into('<HHIIHH', header, 4, 0xfeff, 64, 0x02030100,
                     64 + len(info) + len(data), 2, 0)
    struct.pack_into('<HHII', header, 20, 0x4000, 0, 64, len(info))
    struct.pack_into('<HHII', header, 32, 0x4002, 0, 256, len(data))
    with destination.open('xb') as f:
        f.write(header + info + data)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    convert(args.input, args.output)
    print('Created:', args.output)
