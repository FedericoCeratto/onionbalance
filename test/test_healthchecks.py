# -*- coding: utf-8 -*-
# OnionBalance - Unit/functional testing
# Copyright: 2016 Federico Ceratto
# Released under GPLv3, see COPYING file

"""
Test health checking
"""

from pytest import fixture, raises
import datetime
import pytest
import urllib.request

from onionbalance import healthchecks
from onionbalance.instance import Instance


@fixture
def instance():
    return Instance('mock_controller', 'mock_onion_addr.onion')


def test_init(instance):
    assert instance.is_healthy is None
    assert instance.last_check_time is None
    assert instance.last_check_duration is None


def test_check_health_do_nothing(instance):
    instance.check_health({'type': None})
    assert instance.is_healthy


def test_check_health_wrong_type(instance):
    with raises(ValueError):
        instance.check_health({'type': 'woof', 'port': 80, 'timeout': 5})


def test_check_url(mocker):
    mocker.patch.object(healthchecks, 'time', return_value=1.1)
    mocker.patch.object(urllib.request, 'build_opener')
    healthy, t, duration = healthchecks._check_url('http://123.onion', 10)
    assert healthy
    assert t == 1.1
    assert duration == 0


@pytest.mark.parametrize("check_type", ('http', 'https'))
def test_check_health_http_ok(check_type, instance, monkeypatch):
    conf = {'type': check_type, 'port': 80, 'timeout': 5, 'path': '/'}
    monkeypatch.setattr(healthchecks, 'check_http', lambda *a: (True, 1, 2))
    monkeypatch.setattr(healthchecks, 'check_https', lambda *a: (True, 1, 2))
    instance.check_health(conf)
    assert instance.is_healthy
    assert instance.last_check_time == 1
    assert instance.last_check_duration == 2


@pytest.mark.parametrize("check_type", ('http', 'https'))
def test_check_health_http_fails(check_type, instance, monkeypatch):
    conf = {'type': check_type, 'port': 80, 'timeout': 5, 'path': '/'}
    monkeypatch.setattr(healthchecks, 'check_http', lambda *a: (False, 1, 2))
    monkeypatch.setattr(healthchecks, 'check_https', lambda *a: (False, 1, 2))
    instance.check_health(conf)
    assert not instance.is_healthy
    assert instance.last_check_time == 1
    assert instance.last_check_duration == 2


def test_active_standby_all_healthy(service_active_standby):
    now = datetime.datetime.utcnow()
    for n in range(3):
        i = Instance('mock_controller', '%d.onion' % n)
        i.is_healthy = True
        i.received = now
        i.timestamp = now
        i.introduction_points.append('mock InP %d' % n)
        service_active_standby.instances.append(i)

    ipoints = service_active_standby._select_introduction_points()
    assert service_active_standby._preferred_active_instance
    assert service_active_standby._preferred_active_instance.onion_address == \
        "0.onion"
    assert ipoints == ['mock InP 0']


def test_active_standby_two_healthy(service_active_standby):
    now = datetime.datetime.utcnow()
    for n in range(3):
        i = Instance('mock_controller', '%d.onion' % n)
        i.is_healthy = bool(n)
        i.received = now
        i.timestamp = now
        i.introduction_points.append('mock InP %d' % n)
        service_active_standby.instances.append(i)

    ipoints = service_active_standby._select_introduction_points()
    assert service_active_standby._preferred_active_instance.onion_address == \
        "1.onion"
    assert ipoints == ['mock InP 1']


def test_active_standby_failover(service_active_standby):
    now = datetime.datetime.utcnow()
    for n in range(3):
        i = Instance('mock_controller', '%d.onion' % n)
        i.is_healthy = (n != 1) # first and third are healthy
        i.received = now
        i.timestamp = now
        i.introduction_points.append('mock InP %d' % n)
        service_active_standby.instances.append(i)

    ipoints = service_active_standby._select_introduction_points()
    assert ipoints == ['mock InP 0']

    # first goes down: perform failover
    service_active_standby.instances[0].is_healthy = False
    ipoints = service_active_standby._select_introduction_points()
    assert ipoints == ['mock InP 2']

    # first goes up again, no change
    service_active_standby.instances[0].is_healthy = True
    ipoints = service_active_standby._select_introduction_points()
    assert ipoints == ['mock InP 2']

    # third goes down: perform failover
    service_active_standby.instances[2].is_healthy = False
    ipoints = service_active_standby._select_introduction_points()
    assert ipoints == ['mock InP 0']

    # first goes down: nothing left
    service_active_standby.instances[0].is_healthy = False
    ipoints = service_active_standby._select_introduction_points()
    assert ipoints == []

