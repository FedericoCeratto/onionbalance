#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# OnionBalance - Integration / benchmark testing
# Copyright: 2015 Federico Ceratto
# Released under GPLv3, see COPYING file

from argparse import ArgumentParser
from collections import Counter, deque, namedtuple
from subprocess import check_output
from threading import Thread
from time import time, sleep
import http.server
import os
import socket
import socket
import socketserver
import socks
import subprocess
import urllib.request
import yaml

"""
integration_test
~~~~~~~~~~~~~~~~

A simple integration test tool.

It runs:
 - a set of Tor "server" processes serving an Onion Service each
 - a set of HTTP servers as test Onion Services on different ports
 - a set of Tor "clients"
 - onionbalance

Onionbalance configures and runs an Onion Service in front of the "servers"
The script checks the service connectivity, st change.

Usage: run ./integration_test.py http_servers to run the HTTP servers
then run ./integration_test bench

"""

socketserver.TCPServer.allow_reuse_address = True

tpl = """
DataDirectory tor-data
ControlPort 0
SocksPort 0
RunAsDaemon 0
HiddenServiceDir %s
HiddenServicePort 80 127.0.0.1:%d
Log notice file log
"""

base_server_port = 11110

# TODO: replace "tmpdir" with configurable directory
# TODO: ensure onionbalance process is shut down


def stdev(values, n):
    """Calculate population stdev
    if len(values) < n, "values" is padded with 0s
    """
    values = list(values)
    while len(values) < n:
        values.append(0)

    avg = sum(values) / float(n)
    out = sum((float(v) - avg) ** 2 for v in values)
    return (out / n) ** 0.5


def equality(values, n):
    """Equality percentage:
    100%: optimal distribution
    0%: most unequal distribution
    """
    worst_case_stdev = stdev([n], n)
    if not worst_case_stdev:
        return 0
    v = stdev(values, n)
    e = (worst_case_stdev - v) / worst_case_stdev
    return int(e * 100)


def port_to_iid(port):
    return port - base_server_port


def iid_to_port(iid):
    return iid + base_server_port


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        port = self.server.server_address[1]
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(bytearray("%d" % port, 'utf8'))
        print("%d" % port)


def serve_on_port(port):
    server = socketserver.TCPServer(("localhost", port), Handler)
    server.serve_forever()


def start_http_server(port):
    Thread(target=serve_on_port, args=[port]).start()


def fetch_onionbalance_status(control_fname):
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.connect(control_fname)
    sleep(1)
    out = ''
    try:
        out = client.recv(8192)
    finally:
        client.close()
    return [s.decode() for s in out.splitlines()]


def print_onionbalance_status():
    # FIXME: enable this, implement timeout
    return
    print('--- ob status---')
    status = fetch_onionbalance_status("./tmpdir/master/control")
    for line in status:
        print(line)
    print('----------------')


def _getaddrinfo(*args):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (args[0], args[1]))]


def check_url(url, timeout, socks_port):
    """Check for HTTP[S] connectivity over Tor
    """
    # print("Checking %s using %d" % (url, socks_port))
    original_getaddrinfo = socket.getaddrinfo
    original_socket = socket.socket
    socket.getaddrinfo = _getaddrinfo
    socks.setdefaultproxy(socks.PROXY_TYPE_SOCKS5, "127.0.0.1",
                          socks_port, True)
    socket.socket = socks.socksocket

    opener = urllib.request.build_opener()
    out = None
    try:
        t = time()
        out = opener.open(url, None, timeout).read(1024)
        is_healthy = True
    except Exception:
        is_healthy = False
    finally:
        # Restore socket behavior to normal
        socket.getaddrinfo = original_getaddrinfo
        socket.socket = original_socket

    return out, is_healthy, t, time() - t


def gen_stats(healthy_checks_time, n):
    success_rate = len(healthy_checks_time) / float(n)

    def p(perc):
        if not healthy_checks_time:
            return 0
        pos = int(len(healthy_checks_time) * perc / 100.0)
        return healthy_checks_time[pos]

    if healthy_checks_time:
        avg = sum(healthy_checks_time) / float(len(healthy_checks_time))
    else:
        avg = 0
    return success_rate * 100, p(10), p(50), p(90), p(99), avg


def print_stats(healthy_checks_time, n, port_stats_counter):
    """Print uptime statistics"""
    eq = equality(port_stats_counter.values(), n)
    summary = gen_stats(healthy_checks_time, n)
    summary = (int(n),) + summary + (eq,)
    line = " [%03d]  %3d%%   %.3f %.3f %.3f %.3f %.3f %3d%%     " % summary
    for port in sorted(port_stats_counter):
        line += "   %d:%d" % (port, port_stats_counter[port])

    print(line, end="\r")


def create_ob_conf(n):
    print("Generating onionbalance config")
    cmd = "./onionbalance-config -n %d -v debug --no-interactive --output tmpdir" % n  # noqa
    check_output(cmd, shell=True)
    with open("./tmpdir/master/config.yaml") as f:
        conf = yaml.load(f)
    # health checks conf
    conf['services'][0]["health_check"] = {
        'type': 'http',
        'port': 80,
        'path': '/ob_ping',
        'timeout': 2,
    }
    print("-- ob conf --")
    print(yaml.dump(conf))
    print("-------------")
    with open("./tmpdir/master/config.yaml", "w") as f:
        yaml.dump(conf, f)


def start_ob_process(dirname):
    """Start manager process"""
    print("Starting onionbalance process")
    cmd = "./onionbalanced -v info -c tmpdir/master/config.yaml > /dev/null 2>&1"
    print("Running %r" % cmd)
    return subprocess.Popen(cmd, shell=True, env=dict(
        ONIONBALANCE_CONTROL_SOCKET_LOCATION="./tmpdir/master/control",
        ONIONBALANCE_LOG_LOCATION="./tmpdir/master/log",
    ))


def read_onion_addr_from_conf(dirname):
    conf_fname = os.path.join(dirname, 'instance_torrc')
    with open(conf_fname) as f:
        for line in f:
            if line.startswith("HiddenServiceDir"):
                return line.strip().split()[1]


def read_main_onion_addr():
    conf = yaml.load(open('tmpdir/master/config.yaml'))
    key = conf['services'][0]['key']
    assert key.endswith('.key')
    return key[:-4]


class InstanceManager():
    """Manage tor instances, both the "servers" running the Onion Services
    and the clients
    """
    def __init__(self, num_servers, num_clients, base_server_port):
        self._num_instances = num_servers
        self._num_clients = num_clients
        self.base_server_port = base_server_port
        self._running_instances = {}
        self._running_clients = {}
        self.create_tor_instances_conf()

    def create_tor_instances_conf(self):
        for iid in range(1, self._num_instances+1):
            dirname = "./tmpdir/srv%d/" % iid
            onion_addr = read_onion_addr_from_conf(dirname)
            assert onion_addr
            with open(os.path.join(dirname, 'torrc'), 'w') as f:
                f.write(tpl % (onion_addr, iid_to_port(iid)))

    def start_instance(self, iid):
        """Start instance process, store PID
        iid starts from 1
        """
        dirname = "./tmpdir/srv%d" % iid
        cmd = ['/usr/bin/tor', '-f', 'torrc']
        process = subprocess.Popen(cmd, cwd=dirname, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT)
        port = iid_to_port(iid)
        self._running_instances[port] = process
        print("Started instance on port %d with pid %d" % (port, process.pid))

    def stop_instance(self, port):
        pid = self._running_instances[port].pid
        print("Stopping instance on port %d with pid %d" % (port, pid))
        self._running_instances[port].terminate()
        sleep(.2)
        self._running_instances[port].kill()
        del self._running_instances[port]

    def start_all_instances(self):
        for iid in range(1, self._num_instances+1):
            self.start_instance(iid)

    def stop_all_instances(self):
        for port in tuple(self._running_instances):
            self.stop_instance(port)

    @property
    def running_ports(self):
        return set(self._running_instances.keys())

    def _create_tor_client_conf(self, confdir, port):
        tpl = """
DataDirectory tor-data
ControlPort 0
SocksPort %d
RunAsDaemon 0
Log notice file log
        """
        if os.path.isdir(confdir):
            return
        os.mkdir(confdir)
        conffn = os.path.join(confdir, 'torrc')
        os.mkdir(os.path.join(confdir, 'tordata'))
        with open(conffn, 'w') as f:
            f.write(tpl % port)

    def start_tor_clients(self):
        """Create configuration for Tor clients and start them
        """
        basedir = "./tmpdir"
        for cid in range(self._num_clients):
            port = cid + 9055
            confdir = os.path.join(basedir, "client%d" % cid)
            self._create_tor_client_conf(confdir, port)
            cmd = ['/usr/bin/tor', '-f', 'torrc']
            process = subprocess.Popen(cmd, cwd=confdir,
                                       stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT)
            print('Started tor client with PID %d' % process.pid)
            self._running_clients[port] = process

    def stop_tor_clients(self):
        """Stop all Tor clients
        """
        for process in self._running_clients.values():
            print("Stopping client %d" % process.pid)
            process.terminate()
            sleep(.2)
            process.kill()

    def _gen_probe_stats(self, samples, n):
        healthy_checks_time = [s.duration for s in samples
                               if s.healthy is True]
        success_rate = len(healthy_checks_time) / float(n)

        def p(perc):
            if not healthy_checks_time:
                return 0
            pos = int(len(healthy_checks_time) * perc / 100.0)
            return healthy_checks_time[pos]

        if healthy_checks_time:
            avg = sum(healthy_checks_time) / float(len(healthy_checks_time))
        else:
            avg = 0
        return success_rate * 100, p(10), p(50), p(90), p(99), avg

    def _print_stats(healthy_checks_time, n, port_stats_counter):
        """Print uptime statistics"""
        eq = equality(port_stats_counter.values(), n)
        summary = gen_stats(healthy_checks_time, n)
        summary = (int(n),) + summary + (eq,)
        line = " [%03d]  %3d%%   %.3f %.3f %.3f %.3f %.3f %3d%%     " % summary
        for port in sorted(port_stats_counter):
            line += "   %d:%d" % (port, port_stats_counter[port])

        print(line, end="\r")

    def probe_until_uptime(self, n, url, t0=None, timeout=3):
        """Keep polling an onion service until "n" consecutive success probes
        using the available tor clients in round robin
        """
        Sample = namedtuple('sample', 'port healthy check_time, duration')
        Summary = namedtuple('summary', 'most_common_port')

        if t0 is None:
            t0 = time()
        print(" count  avail  p10   p50   p90 "
              "  p99   avg    equality  instance hits")

        clients_ports = sorted(self._running_clients)
        samples = deque((), n)

        check_cnt = 0
        while True:
            check_cnt += 1
            socks_port = clients_ports[check_cnt % len(clients_ports)]
            contents, healthy, check_time, duration = check_url(url, timeout,
                                                                socks_port)
            port = int(contents) if healthy else None
            sample = Sample(port, healthy, check_time, duration)
            samples.append(sample)

            summary = self._gen_probe_stats(samples, n)
            port_stats_counter = Counter(
                [s.port for s in samples if s.healthy]
            )
            eq = equality(port_stats_counter.values(), n)
            samples_health = [s.healthy for s in samples]
            samples_diagram = "[%s]" % ''.join(
                'o' if h else '.' for h in samples_health
            )
            ports_summary = ' '.join(
                "%d:%d" % (port, cnt)
                for port, cnt in sorted(port_stats_counter.most_common())
            )

            summary = (check_cnt,) + summary + (eq, samples_diagram, ports_summary)
            tpl = " [%04d]  %3d%%   %.3f %.3f %.3f %.3f %.3f %3d%% %s %s     "
            line = tpl % summary
            print(line, end="\r")

            if len(samples_health) == n and all(samples_health):
                print()
                print("100%% uptime achieved in %d s" % (
                    time() - t0))
                print_onionbalance_status()

                ports = [s.port for s in samples]
                most_common_port = max(set(ports), key=ports.count)

                return Summary(most_common_port)

    def ensure_instances_are_up(self):
        for port, p in self._running_instances.items():
            if p.poll() is not None:
                print("server on port %d PID %s retcode %r is down" % (
                    port, p.pid, p.returncode))
                raise Exception()
        for port, p in self._running_clients.items():
            if p.poll() is not None:
                print("client on port %d PID %s retcode %r is down" % (
                    port, p.pid, p.returncode))


def run_http_servers():
    n = 4

    print("Starting HTTP servers")
    for iid in range(1, n+1):
        port = iid_to_port(iid)
        start_http_server(port)

    while True:
        sleep(10)


def run_bench():
    num_tor_clients = 10
    num_tor_servers = 4
    if not os.path.exists("./tmpdir"):
        create_ob_conf(num_tor_servers)

    onion_addr = read_main_onion_addr()
    url = "http://%s.onion:80/ping" % onion_addr
    print("Main test URL:", url)

    im = InstanceManager(num_tor_servers, num_tor_clients, base_server_port)
    im.start_tor_clients()
    im.start_all_instances()
    ob_process = start_ob_process("")
    t0 = time()

    im.ensure_instances_are_up()
    sleep(3)
    im.ensure_instances_are_up()

    try:
        # give ob some time to boot
        im.probe_until_uptime(10, url, t0=t0)
        print("Success!")
        del t0

        while True:
            stats_summary = im.probe_until_uptime(10, url)
            print_onionbalance_status()

            #TODO: reimplement port check
            #answering_ports = set(stats_summary[-1].keys())
            #if answering_ports - im.running_ports:
            #    print("Unexpected port responding")
            #    print(answering_ports - im.running_ports)

            # Shut down the most frequently hit onion service
            im.stop_instance(stats_summary.most_common_port)

            im.probe_until_uptime(10, url)
                # answering_ports = set(stats_summary[-1].keys())
                # if answering_ports - im.running_ports:
                #     print("Unexpected port responding")
                #     print(answering_ports - im.running_ports)
                # else:
                #     print("Success!")
                #     break

            im.start_instance(port_to_iid(stats_summary.most_common_port))

    except KeyboardInterrupt:
        pass

    finally:
        print("Shutting down")
        ob_process.terminate()
        sleep(.2)
        ob_process.kill()
        im.stop_all_instances()
        im.stop_tor_clients()


def test_stdev():
    assert equality((), 10) == 100
    assert equality((10,), 10) == 0
    assert equality((1, 1, 1), 3) == 100
    assert equality((7, 2, 1), 10) == 30
    assert equality((7,), 10) == 29


def main():
    ap = ArgumentParser()
    ap.add_argument('-r', action='store_true')
    ap.add_argument('action', choices=['bench', 'http_servers'])
    args = ap.parse_args()
    if args.action == 'bench':
        run_bench()
    else:
        run_http_servers()


if __name__ == '__main__':
    main()
