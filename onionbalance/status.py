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

LISTEN_TIMEOUT = 1  # seconds


class StatusSocket():
    def __init__(self, config):
        """Create a unix domain socket. When a reader appears, emit a brief
        status summary
        Example::
            socat - UNIX-CONNECT:/var/run/onionbalance/control
            pc47em2hovrmrkvm.onion 2015-12-20 19:51:10.969582
              homkyx37cotkk3yg.onion None 0
              5a2pi3nyanlus5kj.onion 19:20:00 3 ips

        """
        self._config = config
        self._unix_socket_fname = config.CONTROL_SOCKET_LOCATION
        logger.debug("Creating status socket %s", self._unix_socket_fname)
        try:
            os.unlink(self._unix_socket_fname)
        except OSError:
            if os.path.exists(self._unix_socket_fname):
                raise
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.bind(self._unix_socket_fname)
        self._sock.listen(5)  # enqueue up to 5 connetction requests
        self._sock.settimeout(LISTEN_TIMEOUT)

    def listen_with_timeout(self):
        """Listen for incoming status requests with at timeout
        """
        try:
            conn, addr = self._sock.accept()
            self.output_status(conn)
        except socket.timeout:
            return
        except Exception:
            logger.error("Unexpected exception:", exc_info=True)

    def _write(self, conn, msg):
        msg += "\n"
        conn.send(msg.encode())

    def output_status(self, conn):
        """Output a status summary
        """
        for s in self._config.services:
            self._write(conn, "%s.onion %s" % (s.onion_address, s.uploaded))
            for i in s.instances:
                if i.timestamp is None:
                    self._write(conn, "  %s.onion [offline]" % i.onion_address)
                else:
                    inp_cnt = len(i.introduction_points)
                    line = "  %s.onion %s %s ips" % (
                        i.onion_address, i.timestamp, inp_cnt)
                    self._write(conn, line)

    def close(self):
        """Close unix socket and remove its file
        """
        self._sock.close()
        os.remove(self._unix_socket_fname)
