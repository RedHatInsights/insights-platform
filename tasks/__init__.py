# Probably want to delete this whole file in the refactor
# from kafka import KafkaProducer
from app.logging import get_logger
from app.queue.event_producer import KafkaEventProducer

logger = get_logger(__name__)
producer = None


def init_tasks(config):
    global producer
    logger.info("Starting event KafkaProducer()")
    producer = KafkaEventProducer(config)


def emit_event(event, key, headers):
    producer.write_event_events_topic(event, key, headers)


def flush():
    producer.flush()
    logger.info("Event messages flushed")
