# -*- coding: utf-8 -*-
# OnionBalance - Unit/functional testing
# Copyright: 2016 Federico Ceratto
# Released under GPLv3, see COPYING file

"""
Test health checking
"""

import urllib.request

import pytest
from pytest import fixture, raises

from onionbalance.instance import Instance
from onionbalance import healthchecks


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
