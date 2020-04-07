from datetime import datetime
from time import timezone

from kafka import KafkaProducer
from marshmallow import fields
from marshmallow import Schema

from app.logging import get_logger
from app.models import SystemProfileSchema
from app.models import TagsSchema
from app.queue import metrics


logger = get_logger(__name__)


def create_event_producer(config, producer_type):
    if producer_type == "kafka":
        return KafkaEventProducer(config)
    else:
        return NullEventProducer()


class KafkaEventProducer:
    def __init__(self, config):
        logger.info("Starting KafkaEventProducer()")
        self._kafka_producer = KafkaProducer(bootstrap_servers=config.bootstrap_servers)
        self._topic = config.host_egress_topic

    def write_event(self, event, key):
        logger.debug("Topic: %s, key: %s, event: %s", self._topic, key, event)

        try:
            k = key.encode("utf-8") if key else None
            v = event.encode("utf-8")
            self._kafka_producer.send(self._topic, key=k, value=v)
            metrics.egress_message_handler_success.inc()
        except Exception:
            logger.exception("Failed to send event")
            metrics.egress_message_handler_failure.inc()


class NullEventProducer:
    def __init__(self):
        logger.info("Starting NullEventProducer()")

    def write_event(self, event, key=None):
        logger.debug("NullEventProducer - logging key: %s, event: %s", key, event)


def _build_event(event_type, host, platform_metadata, metadata):
    if event_type in ("created", "updated"):
        return (
            HostEvent(strict=True)
            .dumps(
                {
                    "type": event_type,
                    "host": host,
                    "platform_metadata": platform_metadata,
                    "metadata": metadata,
                    "timestamp": datetime.now(timezone.utc),
                }
            )
            .data
        )
    else:
        raise ValueError(f"Invalid event type ({event_type})")


@metrics.egress_event_serialization_time.time()
def build_egress_topic_event(event_type, host, *, platform_metadata={}, metadata={}):
    return _build_event(event_type, host, platform_metadata, metadata)


def build_event_topic_event(event_type, host, *, platform_metadata={}, metadata={}):
    return _build_event(event_type, host, platform_metadata, metadata)


class HostSchema(Schema):
    id = fields.UUID()
    display_name = fields.Str()
    ansible_host = fields.Str()
    account = fields.Str(required=True)
    insights_id = fields.Str()
    rhel_machine_id = fields.Str()
    subscription_manager_id = fields.Str()
    satellite_id = fields.Str()
    fqdn = fields.Str()
    bios_uuid = fields.Str()
    ip_addresses = fields.List(fields.Str())
    mac_addresses = fields.List(fields.Str())
    external_id = fields.Str()
    # FIXME:
    # created = fields.DateTime(format="iso8601")
    # updated = fields.DateTime(format="iso8601")
    # FIXME:
    created = fields.Str()
    updated = fields.Str()
    stale_timestamp = fields.Str()
    stale_warning_timestamp = fields.Str()
    culled_timestamp = fields.Str()
    reporter = fields.Str()
    tags = fields.List(fields.Nested(TagsSchema))
    system_profile = fields.Nested(SystemProfileSchema)


class HostEventMetadataSchema(Schema):
    request_id = fields.Str()


class HostEvent(Schema):
    type = fields.Str()
    host = fields.Nested(HostSchema())
    timestamp = fields.DateTime(format="iso8601")
    platform_metadata = fields.Dict()
    metadata = fields.Nested(HostEventMetadataSchema())
