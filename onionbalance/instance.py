# -*- coding: utf-8 -*-
import datetime
import time

import stem.control

from onionbalance import log
from onionbalance import config
from onionbalance import healthchecks

logger = log.get_logger()


def fetch_instance_descriptors(controller):
    """
    Try fetch fresh descriptors for all HS instances
    """
    logger.info("Initiating fetch of descriptors for all service instances.")

    # Clear Tor descriptor cache before making fetches by sending NEWNYM
    # pylint: disable=no-member
    controller.signal(stem.control.Signal.NEWNYM)
    time.sleep(5)

    for service in config.services:
        for instance in service.instances:
            instance.fetch_descriptor()


class Instance(object):
    """
    Instance represents a back-end load balancing hidden service.
    """

    def __init__(self, controller, onion_address, authentication_cookie=None):
        """
        Initialise an Instance object.
        """
        self.controller = controller

        # Onion address for the service instance.
        self.onion_address = onion_address
        self.authentication_cookie = authentication_cookie

        # Store the latest set of introduction points for this instance
        self.introduction_points = []

        # Timestamp when last received a descriptor for this instance
        self.received = None

        # Timestamp of the currently loaded descriptor
        self.timestamp = None

        # Flag this instance with it's introduction points change. A new
        # master descriptor will then be published as the introduction
        # points have changed.
        self.changed_since_published = False

        # Health status
        self.is_healthy = None
        # Has the health status changed since previous run
        # The value reset by Service._instances_health_has_changed()
        self.health_changed = False
        self.last_check_time = None
        self.last_check_duration = None

    def fetch_descriptor(self):
        """
        Try fetch a fresh descriptor for this service instance from the HSDirs
        """
        logger.debug("Trying to fetch a descriptor for instance %s.onion.",
                     self.onion_address)
        try:
            self.controller.get_hidden_service_descriptor(self.onion_address,
                                                          await_result=False)
        except stem.DescriptorUnavailable:
            # Could not find the descriptor on the HSDir
            self.received = None
            logger.warning("No descriptor received for instance %s.onion, "
                           "the instance may be offline.", self.onion_address)

    def update_descriptor(self, parsed_descriptor):
        """
        Update introduction points when a new HS descriptor is received

        Parse the descriptor content and update the set of introduction
        points for this HS instance.
        """

        self.received = datetime.datetime.utcnow()

        logger.debug("Received a descriptor for instance %s.onion.",
                     self.onion_address)

        # Reject descriptor if its timestamp is older than the current
        # descriptor. Prevent's HSDir's replaying old, expired descriptors.
        if self.timestamp and parsed_descriptor.published < self.timestamp:
            logger.error("Received descriptor for instance %s.onion with "
                         "publication timestamp older than the latest "
                         "descriptor. Ignoring the descriptor.",
                         self.onion_address)
            return
        else:
            self.timestamp = parsed_descriptor.published

        # Parse the introduction point list, decrypting if necessary
        introduction_points = parsed_descriptor.introduction_points(
            authentication_cookie=self.authentication_cookie
        )

        # If the new introduction points are different, flag this instance
        # as modified. Compare the set of introduction point identifiers
        # (fingerprint of the per IP circuit service key).
        if (set(ip.identifier for ip in introduction_points) !=
                set(ip.identifier for ip in self.introduction_points)):
            logger.info("The introduction point set has changed for instance "
                        "%s.onion.", self.onion_address)
            self.changed_since_published = True
            self.introduction_points = introduction_points

        else:
            logger.debug("Introduction points for instance %s.onion matched "
                         "the cached set.", self.onion_address)

    def check_health(self, conf):
        """Run a health check against the instance
        Update self.is_healthy and self.health_changed
        """
        if conf['type'] is None:  # no health checking
            self.is_healthy = True
            return

        # conf e.g. {'type': 'http', 'port': 80, 'path': '/', 'timeout': 15}
        port = conf['port']
        timeout = conf['timeout']
        if conf['type'] == 'tcp':
            healthy, ctime, cd = healthchecks.check_tcp(
                self.onion_address, port, timeout)
        elif conf['type'] == 'http':
            healthy, ctime, cd = healthchecks.check_http(
                self.onion_address, port, conf['path'], timeout)
        elif conf['type'] == 'https':
            healthy, ctime, cd = healthchecks.check_https(
                self.onion_address, port, conf['path'], timeout)
        else:
            raise ValueError("Unexpected check type")

        self.last_check_time = ctime
        self.last_check_duration = cd
        if healthy != self.is_healthy:
            if healthy:
                logger.info("Instance %s went online", self.onion_address)
            else:
                logger.warn("Instance %s went offline", self.onion_address)
            self.health_changed = True
            self.is_healthy = healthy
