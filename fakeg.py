#!/usr/bin/python3
# -*- coding: utf-8 -*-

import socket
from time import sleep, time
from segment import Dwrap, HbFrame, LgiFrame, BacFrame, WxFrame
from segment import json_tpl, dict2json, json2dict
from threading import Thread
from asyncore import dispatcher, loop as asyncore_loop
from commons import init_log, addlog

local_ip = '10.98.1.218'
udp_port = 0xBAC1
udp_ifc = ("", 0xBAC2)
udp_msg = list()  # item: (bytes,('xx.xx.xx.xx', port))
frm_buf = list()  # item: ('xx.xx.xx.xx', port, Frame)
running = True

@addlog
class TcpHandler(dispatcher):
    def __init__(self, id, ip, port):
        super().__init__()
        self.create_socket()
        self.connect((ip, port))
        self.sbuf = bytearray()
        self.rbuf = bytearray()

        # status
        self.id = id
        self.authenticated = False
        self.auth_send_flag = False
        self.hb_tsmp = 0.0

    def handle_connect(self):
        self.info("Connected to Server.")

    def handle_close(self):
        self.error("Disconnect from Server.")
        global running
        running = False

        self.close()

    def _decode(self):
        while len(self.rbuf) >= 4:
            if self.rbuf[:2] != bytes([0x55, 0xaa]):
                del self.rbuf[0]
            else:
                break

        if len(self.rbuf) < 4:
            return None

        length = ((self.rbuf[2] & 0x00ff) << 8) | self.rbuf[3]
        if len(self.rbuf) >= 4 + length:
            pkt = self.rbuf[:4 + length]
            del self.rbuf[:4 + length]
            return pkt

        return None

    def handle_read(self):
        buf = self.recv(1024)
        if len(buf) is 0: return
        self.rbuf += buf
        self.debug("Received from server: " + buf.hex())
        self._fakeg_func(self._decode())

    def _encode(self):
        if len(frm_buf) is not 0:
            ip, port, frame = frm_buf.pop(0)
            pkt = Dwrap(frame.TYPE, self.id, ip, port, frame.get_all())
            self.info("Send to Server: " + str(pkt))
            return pkt.get_all()
        else:
            return b''

    def handle_write(self):
        if len(self.sbuf) is 0:
            if self.authenticated:
                self._send_hbframe()
            else:
                if not self.auth_send_flag:
                    frm_buf.append((local_ip,0, LgiFrame()))
                    self.auth_send_flag = True
            self.sbuf += self._encode()

        if len(self.sbuf) is not 0:
            ret = self.send(self.sbuf)
            self.debug("Sent to server: " + self.sbuf[:ret].hex())
            del self.sbuf[:ret]

    def _fakeg_func(self, pkt):
        if pkt is None:
            return

        d = Dwrap(pkt=pkt)
        if self.authenticated:
            if d.type == HbFrame.TYPE:
                self.info("Received HbFrame:" + str(d))
            elif d.type == BacFrame.TYPE:
                self.info("Received BacFram: " + str(d))
                udp_msg.append((d.data, udp_ifc))
            elif d.type == WxFrame.TYPE:
                self.info("Received WxFram: " + str(d))
                self._deal_wxframe(d.data)
            else:
                self.warn("Receive Unkonw frame: " + str(d))
        else:
            if d.type == LgiFrame.TYPE:
                self.info("Recvice authentic frame: " + str(d))
                self.authenticated = True
                self.hb_tsmp = time()
            else:
                self.warn("Not authenticated: " + str(d))

    def _send_hbframe(self):
        if self.authenticated:
            cur = time()
            if cur - self.hb_tsmp > 10.0:
                frm_buf.append((local_ip, 0, HbFrame()))
                self.hb_tsmp = cur

    def _deal_wxframe(self, data):
        frame = WxFrame(pkt=data)
        self.info("Deal WxFrame: " + str(frame))
        ins = json2dict(frame.json.decode())
        ack = json_tpl["ACK"]
        ack["Wx_FlcNum"] = ins["Wx_FlcNum"]
        ack["Wx_buildNum"] = ins["Wx_buildNum"]
        ack["LogId"] = ins["LogId"]
        ack["ReplyCommand"] = frame.number
        ack["OperResult"] = 1
        self.info("    -- wxACK: " + dict2json(ack))
        afrm = WxFrame(32, frame.sequence, dict2json(ack).encode(encoding="UTF-8"))
        frm_buf.append((local_ip, 0, afrm))

@addlog
class UdpHandler(dispatcher):
    def __init__(self, port):
        super().__init__()
        self.create_socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.bind((local_ip, port))
        self.smsg = list()
        # self.rmsg = set()

    def handle_read(self):
        data, addr = self.socket.recvfrom(1024)
        self.debug("Received from %s: %s" % (addr, data.hex()))
        if data[0] == 0x81:
            frame = BacFrame(data)
            frm_buf.append((*addr, frame))

    def handle_write(self):
        if len(self.smsg) is 0:
            if len(udp_msg) is 0:
                return
            else:
                self.smsg.append(udp_msg.pop(0))

        if len(self.smsg) is not 0:
            if len(self.smsg[0][0]) is not 0:
                self.debug("Send to %s: %s" %
                                 (self.smsg[0][1], self.smsg[0][0].hex()))
                ret = self.socket.sendto(*self.smsg[0])
                del self.smsg[0][0][:ret]
            else:
                self.smsg.pop(0)


@addlog
class FakeG(Thread):
    def __init__(self, id, ip, port):
        self.info("Start fakeg....")
        super().__init__(name="FakeG", daemon=True, target=asyncore_loop)
        self.tcp_handler = TcpHandler(id, ip, port)
        self.udp_handler = UdpHandler(udp_port)


if __name__ == '__main__':
    init_log('/tmp/fakeg.log', "INFO")
    try:
        FakeG(132, "10.98.1.178", 46060).start()
        while running:
            sleep(1)
    except KeyboardInterrupt:
        print('Quit.')

