import json
from threading import Thread

from kafka import KafkaConsumer
from kafka import KafkaProducer

from api import metrics
from app import db
from app.logging import get_logger
from app.logging import threadctx
from app.models import Host
from app.models import SystemProfileSchema
from lib.db import session_guard

logger = get_logger(__name__)


producer = None
cfg = None


def init_tasks(config, flask_app=None):
    global cfg
    global producer

    cfg = config

    if config.kafka_enabled:
        producer = _init_event_producer(config)
    if flask_app:
        _init_system_profile_consumer(config, flask_app)


def _init_event_producer(config):
    logger.info("Starting event KafkaProducer()")
    return KafkaProducer(bootstrap_servers=config.bootstrap_servers)


def emit_event(e, key):
    status = "produced" if producer else "not produced"
    logger.info("Event message (%s): topic %s, key %s", status, cfg.event_topic, key)
    logger.debug("Event message body: %s", e)
    if producer:
        producer.send(cfg.event_topic, key=key.encode("utf-8") if key else None, value=e.encode("utf-8"))


def flush():
    suffix = "" if producer else " (no producer)"
    logger.info("Event messages flush%s", suffix)
    if producer:
        producer.flush()


@metrics.system_profile_commit_processing_time.time()
def msg_handler(parsed):
    id_ = parsed["id"]
    threadctx.request_id = parsed["request_id"]
    if not id_:
        logger.error("ID is null, something went wrong.")
        return

    with session_guard(db.session):
        host = Host.query.get(id_)
        if host is None:
            logger.error("Host with id [%s] not found!", id_)
            return
        logger.info("Processing message id=%s request_id=%s", parsed["id"], parsed["request_id"])
        profile = SystemProfileSchema(strict=True).load(parsed["system_profile"]).data
        host._update_system_profile(profile)


def _init_system_profile_consumer(config, flask_app, handler=msg_handler, consumer=None):

    if not config.kafka_enabled:
        logger.info("System profile consumer has been disabled")
        return

    logger.info("Starting system profile queue consumer.")

    if consumer is None:
        consumer = KafkaConsumer(
            config.system_profile_topic, group_id=config.consumer_group, bootstrap_servers=config.bootstrap_servers
        )

    def _f():
        with flask_app.app_context():
            while True:
                for msg in consumer:
                    try:
                        with metrics.system_profile_deserialization_time.time():
                            data = json.loads(msg.value)
                        handler(data)
                        metrics.system_profile_commit_count.inc()
                    except Exception:
                        logger.exception("uncaught exception in handler, moving on.")
                        metrics.system_profile_failure_count.inc()

    t = Thread(target=_f, daemon=True)
    t.start()
