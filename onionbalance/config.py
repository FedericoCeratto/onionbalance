# -*- coding: utf-8 -*-
import os

"""
Define default config options for the management server
"""

# Set default configuration options for the management server

REPLICAS = 2
MAX_INTRO_POINTS = 10
DESCRIPTOR_VALIDITY_PERIOD = 24 * 60 * 60
DESCRIPTOR_OVERLAP_PERIOD = 60 * 60
DESCRIPTOR_UPLOAD_PERIOD = 60 * 60  # Re-upload descriptor every hour
REFRESH_INTERVAL = 10 * 60
PUBLISH_CHECK_INTERVAL = 5 * 60

LOG_LOCATION = os.environ.get('ONIONBALANCE_LOG_LOCATION')
CONTROL_SOCKET_LOCATION = os.environ.get(
    'ONIONBALANCE_CONTROL_SOCKET_LOCATION', '/var/run/onionbalance/control')
LOG_LEVEL = os.environ.get('ONIONBALANCE_LOG_LEVEL', 'info')

TOR_ADDRESS = '127.0.0.1'
TOR_PORT = 9051
TOR_CONTROL_PASSWORD = None

# Store global data about onion services and their instance nodes.
services = []
