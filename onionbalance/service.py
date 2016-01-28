# -*- coding: utf-8 -*-
import datetime
import time
import base64

import Crypto.PublicKey.RSA
import stem

from onionbalance import descriptor
from onionbalance import util
from onionbalance import log
from onionbalance import config

logger = log.get_logger()

max_descriptor_age = 4 * 60 * 60


def publish_all_descriptors():
    """
    Called periodically to upload new super-descriptors if needed

    .. todo:: Publishing descriptors for different services at the same time
              will leak that they are related. Descriptors should
              be published individually at a random interval to avoid
              correlation.
    """
    logger.debug("Checking if any master descriptors should be published.")
    for service in config.services:
        service.descriptor_publish()


class Service(object):
    """
    Service represents a front-facing hidden service which should
    be load-balanced.
    """

    def __init__(self, controller, service_key=None, instances=None,
                 health_check_conf=None):
        """
        Initialise a HiddenService object.
        """
        self.controller = controller

        # Service key must be a valid PyCrypto RSA key object
        if isinstance(service_key, Crypto.PublicKey.RSA._RSAobj):
            self.service_key = service_key
        else:
            raise ValueError("Service key is not a valid RSA object.")

        # List of instances for this onion service
        self.instances = instances or []

        # Calculate the onion address for this service
        self.onion_address = util.calc_onion_address(self.service_key)

        # Timestamp when this descriptor was last attempted
        self.uploaded = None

        # Health checking configuration
        self.health_check_conf = health_check_conf
        self.active_standby_mode = health_check_conf['model'] == \
            'active-standby'
        self._preferred_active_instance = None

    def _intro_points_modified(self):
        """
        Check if the introduction point set has changed since last
        publish.
        """
        return any(instance.changed_since_published
                   for instance in self.instances)

    def _instances_health_has_changed(self):
        """
        Check if the health status of any instance has changed and reset the
        change flag.
        """
        changed = False
        for i in self.instances:
            changed = changed or i.health_changed
            i.health_changed = False

        return changed

    def _descriptor_not_uploaded_recently(self):
        """
        Check if the master descriptor hasn't been uploaded recently
        """
        if not self.uploaded:
            # Descriptor never uploaded
            return True

        descriptor_age = (datetime.datetime.utcnow() - self.uploaded)
        if (descriptor_age.total_seconds() > config.DESCRIPTOR_UPLOAD_PERIOD):
            return True
        else:
            return False

    def _descriptor_id_changing_soon(self):
        """
        If the descriptor ID will change soon, upload under both descriptor IDs
        """
        permanent_id = base64.b32decode(self.onion_address, 1)
        seconds_valid = util.get_seconds_valid(time.time(), permanent_id)

        # Check if descriptor ID will be changing within the overlap period.
        return (seconds_valid < config.DESCRIPTOR_OVERLAP_PERIOD)

    def _select_introduction_points(self):
        """
        Choose set of introduction points from all fresh descriptors
        If health checks are enabled, only healthy instances are selected.
        """
        now = datetime.datetime.utcnow()
        selected_instances = []

        # TODO: add fail-open threshold on instance health

        # Loop through each instance and determine fresh intro points
        for instance in self.instances:
            if not instance.received:
                logger.info("No descriptor received for instance %s.onion "
                            "yet.", instance.onion_address)
                continue

            if not instance.is_healthy:
                logger.debug("Skipping unhealthy instance %s.onion",
                             instance.onion_address)
                continue

            # The instance may be offline if no descriptor has been received
            # for it recently or if the received descriptor's timestamp is
            # too old
            received_age = now - instance.received
            timestamp_age = now - instance.timestamp
            received_age = received_age.total_seconds()
            timestamp_age = timestamp_age.total_seconds()

            if (received_age > config.DESCRIPTOR_UPLOAD_PERIOD or
                    timestamp_age > max_descriptor_age):
                logger.info("Our descriptor for instance %s.onion is too old. "
                            "The instance may be offline. It's introduction "
                            "points will not be included in the master "
                            "descriptor.", instance.onion_address)
                continue

            # Include this instance's introduction points
            instance.changed_since_published = False
            selected_instances.append(instance)

        if self.active_standby_mode and selected_instances:
            # When running in active-standby mode, only one instance is active
            # at a time. Failover happens only when the currently active
            # instance goes offline
            if self._preferred_active_instance is None:
                self._preferred_active_instance = selected_instances[0]

            if self._preferred_active_instance not in selected_instances:
                logger.info("Active-standby failover! Switching to"
                            " new instance %s" % instance.onion_address)
                self._preferred_active_instance = selected_instances[0]

            selected_instances = (self._preferred_active_instance, )

        available_intro_points = [i.introduction_points
                                  for i in selected_instances]

        num_intro_points = sum(len(ips) for ips in available_intro_points)
        choosen_intro_points = descriptor.choose_introduction_point_set(
            available_intro_points)

        logger.debug("Selected %d IPs of %d for service %s.onion.",
                     len(choosen_intro_points), num_intro_points,
                     self.onion_address)

        return choosen_intro_points

    def _publish_descriptor(self, deviation=0):
        """
        Create, sign and uploads a master descriptor for this service
        """
        introduction_points = self._select_introduction_points()
        for replica in range(0, config.REPLICAS):
            try:
                signed_descriptor = descriptor.generate_service_descriptor(
                    self.service_key,
                    introduction_point_list=introduction_points,
                    replica=replica,
                    deviation=deviation
                )
            except ValueError as exc:
                logger.warning("Error generating master descriptor: %s", exc)
            else:
                # Signed descriptor was generated successfully, upload it
                try:
                    descriptor.upload_descriptor(self.controller,
                                                 signed_descriptor)
                except stem.ControllerError:
                    logger.exception("Error uploading descriptor for service "
                                     "%s.onion.", self.onion_address)
                else:
                    logger.info("Published a descriptor for service "
                                "%s.onion under replica %d.",
                                self.onion_address, replica)

        # It would be better to set last_uploaded when an upload succeeds and
        # not when an upload is just attempted. Unfortunately the HS_DESC #
        # UPLOADED event does not provide information about the service and
        # so it can't be used to determine when descriptor upload succeeds
        self.uploaded = datetime.datetime.utcnow()

    def descriptor_publish(self, force_publish=False):
        """
        Publish descriptor if have new IP's or if descriptor has expired
        """

        # A descriptor should be published if any of the following conditions
        # are True
        if any([self._intro_points_modified(),  # If any IPs have changed
                self._descriptor_not_uploaded_recently(),
                self._instances_health_has_changed(),
                force_publish]):

            logger.debug("Publishing a descriptor for service %s.onion.",
                         self.onion_address)
            self._publish_descriptor()

            # If the descriptor ID will change soon, need to upload under
            # the new ID too.
            if self._descriptor_id_changing_soon():
                logger.info("Publishing a descriptor for service %s.onion "
                            "under next descriptor ID.", self.onion_address)
                self._publish_descriptor(deviation=1)

        else:
            logger.debug("Not publishing a new descriptor for service "
                         "%s.onion.", self.onion_address)

    def check_health(self):
        """Check health of every instance in this service
        """
        for i in self.instances:
            i.check_health(self.health_check_conf)
