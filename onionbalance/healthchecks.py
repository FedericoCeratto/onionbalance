# -*- coding: utf-8 -*-
# OnionBalance - Service health checking
# Copyright: 2015 Federico Ceratto
# Released under GPLv3, see COPYING file

"""
Check service health using TCP, HTTP, HTTPS
"""

import urllib.request
import socks
import socket
from time import time

from onionbalance import log
import onionbalance

logger = log.get_logger()

USER_AGENT_HEADER = 'OnionBalance/%s' % onionbalance.__version__


def _getaddrinfo(*args):
    """Patch socket.getaddrinfo to use SOCKS5
    """
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (args[0], args[1]))]


def proxify(f):
    """Setup Tor SOCKS5 proxy globally.
    This breaks local connectivity e.g. Stem
    """
    def wrapper(*a, **kw):
        original_getaddrinfo = socket.getaddrinfo
        original_socket = socket.socket
        socket.getaddrinfo = _getaddrinfo
        socks.setdefaultproxy(socks.PROXY_TYPE_SOCKS5, "127.0.0.1", 9050, True)
        socket.socket = socks.socksocket
        try:
            out = f(*a, **kw)
        finally:
            # Restore socket behavior to normal
            socket.getaddrinfo = original_getaddrinfo
            socket.socket = original_socket

        return out

    return wrapper


@proxify
def check_tcp(onion_addr, port_number, timeout):
    """Check for Onion Service connectivity with a TCP connect
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    logger.debug("Checking TCP %s:%d", onion_addr, port_number)
    try:
        t = time()
        s.connect(("%s.onion" % onion_addr, port_number))
        delta = time() - t
        is_healthy = True
    except:
        delta = time() - t
        is_healthy = False
    finally:
        s.close()

    return is_healthy, t, delta


@proxify
def _check_url(url, timeout):
    """Check for HTTP[S] connectivity over Tor"""
    opener = urllib.request.build_opener()
    opener.addheaders = [('User-agent', USER_AGENT_HEADER)]
    logger.debug("Checking %s", url)
    try:
        t = time()
        opener.open(url, None, timeout).read(1024)
        is_healthy = True
    except Exception as e:
        logger.debug("Check exception %s", e)
        is_healthy = False

    return is_healthy, t, time() - t


def check_http(onion_addr, port_number, path, timeout):
    """Check for Onion Service connectivity over HTTP using GET
    """
    path = path.lstrip('/')
    url = "http://%s.onion:%d/%s" % (onion_addr, port_number, path)
    return _check_url(url, timeout)


def check_https(onion_addr, port_number, path, timeout):
    """Check for Onion Service connectivity over HTTPS using GET
    """
    path = path.lstrip('/')
    url = "https://%s.onion:%d/%s" % (onion_addr, port_number, path)
    return _check_url(url, timeout)


def test_facebook():
    """Test Facebook Onion Service"""
    logger.info(check_tcp("facebookcorewwwi", 80, 30))
    logger.info(check_http("facebookcorewwwi", 80, '/', 30))
    logger.info(check_https("facebookcorewwwi", 443, '/', 30))

    logger.info(check_tcp("facebookcorewwwi", 80, 0.01))
    logger.info(check_http("facebookcorewwwi", 80, '/', 0.01))

if __name__ == '__main__':
    test_facebook()
