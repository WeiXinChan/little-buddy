"""Bounded real PNG validation and metadata removal. No files or image URLs."""
import struct
import zlib

MAX_PNG=2*1024*1024
SIGNATURE=b'\x89PNG\r\n\x1a\n'


def chunk(kind,data):
    return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)


def checked_png(data,expected_width,expected_height):
    if not 0<len(data)<=MAX_PNG or not data.startswith(SIGNATURE):raise ValueError('PNG')
    offset=8;header=None;compressed=bytearray();count=0;ended=False;after_idat=False
    while offset<len(data):
        count+=1
        if count>128 or offset+12>len(data):raise ValueError('PNG')
        length=struct.unpack_from('>I',data,offset)[0];kind=data[offset+4:offset+8]
        if length>MAX_PNG or offset+12+length>len(data):raise ValueError('PNG')
        part=data[offset+8:offset+8+length];crc=struct.unpack_from('>I',data,offset+8+length)[0]
        if zlib.crc32(kind+part)&0xffffffff!=crc:raise ValueError('PNG')
        offset+=12+length
        if count==1 and kind!=b'IHDR':raise ValueError('PNG')
        if kind==b'IHDR':
            if header is not None or length!=13:raise ValueError('PNG')
            width,height,depth,color,method,filtering,interlace=struct.unpack('>IIBBBBB',part)
            if (width!=expected_width or height!=expected_height or not 512<=width<=2048 or not 512<=height<=2048 or
                depth!=8 or color not in (2,6) or method!=0 or filtering!=0 or interlace!=0):raise ValueError('PNG')
            header=part;stride=width*(3 if color==2 else 4)+1;expected=stride*height
        elif kind==b'IDAT':
            if header is None or after_idat or not part or len(compressed)+length>MAX_PNG:raise ValueError('PNG')
            compressed.extend(part)
        elif kind==b'IEND':
            if length or offset!=len(data) or not compressed:raise ValueError('PNG')
            ended=True;break
        else:
            # Reject unknown critical chunks, animations and malformed chunk names.
            # Ignore ancillary metadata only after validating its CRC; never publish it.
            if (len(kind)!=4 or any(not (65<=c<=90 or 97<=c<=122) for c in kind) or
                not kind[0]&32 or kind[2]&32 or kind in (b'acTL',b'fcTL',b'fdAT')):raise ValueError('PNG')
            if compressed:after_idat=True
    if not ended or header is None:raise ValueError('PNG')
    decoder=zlib.decompressobj()
    try:decoded=decoder.decompress(compressed,expected+1)
    except zlib.error:raise ValueError('PNG') from None
    if (len(decoded)!=expected or not decoder.eof or decoder.unconsumed_tail or decoder.unused_data or
        any(decoded[row*stride]>4 for row in range(height))):raise ValueError('PNG')
    # Same pixels/IDAT, no text/EXIF/provider metadata. Review hashes bind these exact bytes.
    return SIGNATURE+chunk(b'IHDR',header)+chunk(b'IDAT',bytes(compressed))+chunk(b'IEND',b'')
