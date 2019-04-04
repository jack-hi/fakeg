#!/usr/bin/python3
# -*- coding: utf-8 -*-


from copy import copy as _copy
from struct import pack, unpack
from binascii import hexlify
from socket import inet_aton, inet_ntoa
from time import localtime
from mcrptos import AES128, MD5, Icrc16
import time
import logging


Log = logging.getLogger("App0")


class Packet(object):
    def __init__(self, data = None, *args, **kwargs):

        if data is None:
            self.pdata = bytearray()
        elif isinstance(data, (bytes, bytearray)):
            self.pdata = bytearray(data)
        elif isinstance(data, Packet):
            self.pdata = _copy(data.pdata)
        else:
            raise TypeError("bytes or bytearray needed.")

    def get_packet(self):
        return self.pdata

    def get(self):
        """ get the first byte in the byte array and delete from the bytearray """
        if len(self.pdata) == 0:
            raise ValueError("packet is empty.")

        octet = self.pdata[0]
        del self.pdata[0]
        return octet

    def get_data(self, dlen):
        """ get len bytes from the bytearray and delete from the bytearray """
        if len(self.pdata) < dlen:
            raise ValueError("out of range")

        data = self.pdata[:dlen]
        del self.pdata[:dlen]
        return data

    def get_short(self):
        """ get a short int from the head of the bytearray
            the short int is big-endian in bytearray"""
        return unpack('>H', self.get_data(2))[0]

    def get_long(self):
        return unpack('>L', self.get_data(4))[0]

    def put(self, n):
        self.pdata += bytes([n])

    def put_data(self, data):
        if isinstance(data, bytes):
            pass
        elif isinstance(data, bytearray):
            pass
        elif isinstance(data, list):
            data = bytes(data)
        else:
            raise ValueError("need bytes/bytearray/list")

        self.pdata += data

    def put_short(self, s):
        self.pdata += pack('>H', s & 0xFFFF)

    def put_long(self, l):
        self.pdata += pack('>L', l & 0xFFFFFFFF)

    def __str__(self):
        hexstr = str(hexlify(self.pdata), 'ascii').upper()
        return ' '.join(hexstr[i:i+2] for i in range(0, len(hexstr), 2))


class HbFrame(Packet):
    """
    HbFrame: big-endian
    +--------+--------+--------+--------+
    |    sequence     |     year        |
    +--------+--------+--------+--------+
    | month  |  day   |  hour  | minute |
    +--------+--------+--------+--------+
    | second |           0              |
    +--------+--------+--------+--------+
    |        0        |
    +--------+--------+
    """
    TYPE = 0

    seq = 0
    def __init__(self):
        super().__init__()
        self._encode()

    def _encode(self):
        self.put_short(self.get_seq())
        self.update_seq()
        time = localtime()
        self.put_short(time.tm_year)
        self.put(time.tm_mon)
        self.put(time.tm_mday)
        self.put(time.tm_hour)
        self.put(time.tm_min)
        self.put(time.tm_sec)
        self.put_data(bytes(5))

    def update_seq(self):
        HbFrame.seq += 1

    def get_seq(self):
        if HbFrame.seq > 0xFFFF:
            HbFrame.seq = 0
        return HbFrame.seq



class LgiFrame(Packet):
    """
    frame: (big-endian)
    +--------+--------+--------+--------+
    |      year       | month  |   day  |
    +--------+--------+--------+--------+
    |  hour  | minute | second |    0   |
    +--------+--------+--------+--------+
    |                 0                 |
    +--------+--------+--------+--------+
    |                 0                 |
    +--------+--------+--------+--------+
    |                                   |
    +                                   +
    |                                   |
    +              AES/MD5              +
    |                                   |
    +                                   +
    |                                   |
    +--------+--------+--------+--------+
    ase = AES128(frame[0:16])
    ret = MD5(ase[:16])

    """
    TYPE = 1
    def __init__(self, key=None):
        super().__init__()

        if key is None:
            self.key = b'0123456789012345'
        else:
            self.key = key
        self._encode()

    def _encode(self):
        time = localtime()
        self.put_short(time.tm_year)
        self.put(time.tm_mon)
        self.put(time.tm_mday)
        self.put(time.tm_hour)
        self.put(time.tm_min)
        self.put(time.tm_sec)
        self.put_data(bytes(9))
        aes_crypto = AES128(self.key).encrypt(bytes(self.pdata))
        self.put_data(MD5().digest(aes_crypto[:16]))

    def verify(self, data):
        if not isinstance(data, (bytes, bytearray)):
            #raise TypeError("data must be a byte-like array.")
            Log.warning("Type Error, data must be a byte-like array.")
            return False
        if len(data) is not 16*2:
            #raise ValueError("data length error.")
            Log.warning("Type Error, data length error.")
            return False
        crypto = MD5().digest(AES128(self.key).encrypt(bytes(data[:16]))[:16])
        return crypto == data[16:]


class BacFrame(Packet):
    TYPE = 2
    def __init__(self, data):
        super().__init(data)


class FcFrame(Packet):
    """
     **
     * PacketSegment Structure: (big-endian)
     *	0       8       16      24     31
     *	+-------+-------+---------------+
     *	| 0x88  | flags |     length    |
     *	+-------+-------+-------+-------+
     *	|    packetID   |   segmentNum  |
     *	+---------------+---------------+
     *	|             DATA              |
     *	+-------------------------------+
     *
     *	flags:
     *	 7 6 5 4 3 2 1 0
     *	+-+-+-+-+-+-+-+-+
     *	| | | | | | |f|a|
     *	|0|0|0|0|0|0|l|c|
     *	| | | | | | |w|k|
     *	+-+-+-+-+-+-+-+-+
     *	flw: more follow flags
     *	ack: ACK flags
     *

    """
    TYPE = 6

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.identity = Segment.INDENTITY
        self.flags = 0
        self.packet_id = 0
        self.length = 0
        self.seq = 0
        self.data = None

    def update(self, flags, id, seq, data):
        self.flags = flags
        self.packet_id = id
        self.seq = seq
        if data is None:
            self.length = 8
            return
        else:
            if not isinstance(data, (list, bytes, bytearray)):
                raise ValueError(" value type error ")
            self.data = data
            self.length = 8 if data == None else 8 + len(data)
        return self

    def encode(self):
        self.put(self.identity)
        self.put(self.flags)
        self.put_short(self.length)
        self.put_short(self.packet_id)
        self.put_short(self.seq)
        if self.data is not None:
            self.put_data(self.data)

        return self

    def decode(self):
        self.get()  # identity: 0x88
        self.flags = self.get()
        self.length = self.get_short()
        self.packet_id = self.get_short()
        self.seq = self.get_short()
        self.data = self.get_all()

        return self

    def get_flags(self):
        return self.flags

    def get_packet_id(self):
        return self.packet_id

    def get_length(self):
        return self.length

    def get_seq(self):
        return self.seq

    def get_segment_data(self):
        return self.data

    def __str__(self):
        tmp = Packet.__str__(self)
        tmp += \
            f"\nidentity: 0x{self.identity:x}, " \
            f"flags: {self.flags}, " \
            f"length: {self.length}, " \
            f"packet_id: {self.packet_id}, " \
            f"segment_num: {self.seq}\n"
        return tmp


class WxFrame(Packet):
    TYPE = 7
    def __init__(self, data):
        super().__init(data)


class Dwrap(Packet):
    """
    " simple wrap
    +--------+--------+--------+--------+
    |    identity     |     length      |
    +--------+--------+--------+--------+
    |  type  |
    +--------+--------+--------+--------+
    |                 ID                |
    +--------+--------+--------+--------+
    |                 IP                |
    +--------+--------+--------+--------+
    |      port       |
    +--------+--------+--------+--------+
    |                                   |
    +           reserveed 17B           +
    |                                   |
    +--------+--------+--------+--------+
    |                                   |
    +                DATA               +
    |                                   |
    +--------+--------+--------+--------+
    |       CRC       |
    +--------+--------+

    length: len([type:])
    CRC: CRC([length:CRC])
    """
    IDENTITY = bytes([0x55, 0xaa])


    def __init__(self, type=None, id=None, dip=None, dport=None, data=None):
        super().__init__()
        self.length = 30
        self.type = 0 if type is None else type
        self.id = 0 if id is None else id
        self.dip = "0.0.0.0" if dip is None else dip
        self.dport = 0 if dport is None else dport
        self.data = None
        if data is not None:
            if not isinstance(data, (bytes, bytearray)):
                raise ValueError("value type error")
            self.data = data
        self.crc = 0
        # self._encode()

    def update(self, **kargs):
        for arg in kargs.keys():
            if arg in ("type", "id", "dip", "dport", "data"):
                self.__setattr__(arg, kargs.get(arg))
        self.get_packet().clear()
        self._encode()

    def _encode(self):
        self.put_data(Dwrap.IDENTITY)  # identity: 2
        if self.data is not None:
            self.length = 30 + len(self.data)
        self.put_short(self.length)  # length: 2
        self.put(self.type)  # type: 1
        self.put_long(self.id)  # id: 4
        self.put_data(inet_aton(self.dip))  # ip: 4
        self.put_short(self.dport)  # port: 2
        self.put_data(bytes(17))  # reserved: 17
        if self.data is not None:
            self.put_data(self.data)  # data: n
        self.crc = Icrc16.CRC16(bytes(self.pdata[2:]))
        self.put(self.crc&0xFF)
        self.put((self.crc&0xFF00) >> 8)

    def decode(self, data):
        if not isinstance(data, (bytes, bytearray)):
            Log.warning("Value Error, data must be byte-like array.")
            return None
        p = Packet(data)
        if Dwrap.IDENTITY != p.get_data(2):
            Log.warning("Value Error, identity error.")
            return None
        crc = Icrc16.CRC16(bytes(p.pdata[:-2]))
        self.length = p.get_short()
        if len(p.pdata) != self.length:
            Log.warning("Value Error, pakcet length error.")
            return None
        self.type = p.get()
        self.id = p.get_long()
        self.dip = inet_ntoa(p.get_data(4))
        self.dport = p.get_short()
        p.get_data(17)
        self.data = p.get_data(self.length-30)
        crcl = p.get()
        crch = p.get()
        self.crc = crch<<8 | crcl
        if crc != self.crc:
            Log.warning("Value Error, packet CRC error.")
            return None
        return self

    def __str__(self):
        return "Dwarp {length=%d, type=%d, id=%d, ip=%s:%d, crc=0x%02X}" % \
               (self.length, self.type, self.id, self.dip, self.dport, self.crc)


if __name__ == '__main__':

    l = LgiFrame()
    t1 = l.get_packet()
    print(t1)
    if l.verify(t1):
        print("OK")

    h3 = HbFrame()
    print(h3)

    sr = Dwrap()
    sr.update(type=1, id=101, dip='10.98.1.178', dport=7894, data=h3.get_packet())
    print(sr)

