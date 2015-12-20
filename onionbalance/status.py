# -*- coding: utf-8 -*-
# OnionBalance - Status
# Copyright: 2015 Federico Ceratto
# Released under GPLv3, see COPYING file

"""
Provide status over Unix socket
Default path: /var/run/onionbalance/control
"""

from onionbalance import log
import os
import socket

logger = log.get_logger()


class StatusSocket():
    def __init__(self, config):
        self._config = config
        self._unix_socket_fname = '/tmp/ux'
        try:
            os.unlink(self._unix_socket_fname)
        except OSError:
            if os.path.exists(self._unix_socket_fname):
                raise
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.bind(self._unix_socket_fname)
        self._sock.listen(5)
        self._sock.settimeout(1)

    def listen_with_timeout(self):
        try:
            conn, addr = self._sock.accept()
            self.output_status(conn)
        except socket.timeout:
            return

    def _write(self, conn, msg):
        msg += "\n"
        conn.send(msg.encode())

    def output_status(self, conn):
        for s in self._config.services:
            self._write(conn, "%s.onion %s" % (s.onion_address, s.uploaded))
            for i in s.instances:
                inp_cnt = len(i.introduction_points)
                self._write(conn, "  %s.onion %s %s" % (
                    i.onion_address, i.timestamp, inp_cnt))

    def close(self):
        self._sock.close()
        os.remove(self._unix_socket_fname)
