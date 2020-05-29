import sys
from functools import partial

from prometheus_client import CollectorRegistry
from prometheus_client import push_to_gateway
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import UNKNOWN_REQUEST_ID_VALUE
from app.config import Config
from app.culling import Conditions
from app.environment import RuntimeEnvironment
from app.logging import configure_logging
from app.logging import get_logger
from app.logging import threadctx
from app.models import Host
from lib.db import session_guard
from lib.host_delete import delete_hosts
from lib.host_repository import stale_timestamp_filter
from lib.metrics import delete_host_count
from lib.metrics import delete_host_processing_time
from lib.metrics import host_reaper_fail_count

# from tasks import flush
# from tasks import init_tasks

__all__ = ("main", "run")

PROMETHEUS_JOB = "inventory-reaper"
LOGGER_NAME = "host_reaper"
COLLECTED_METRICS = (delete_host_count, delete_host_processing_time, host_reaper_fail_count)
RUNTIME_ENVIRONMENT = RuntimeEnvironment.JOB


def _init_config():
    config = Config(RUNTIME_ENVIRONMENT)
    config.log_configuration()
    return config


def _init_db(config):
    engine = create_engine(config.db_uri)
    return sessionmaker(bind=engine)


def _prometheus_job(namespace):
    return f"{PROMETHEUS_JOB}-{namespace}" if namespace else PROMETHEUS_JOB


def _excepthook(logger, type, value, traceback):
    logger.exception("Host reaper failed", exc_info=value)


@host_reaper_fail_count.count_exceptions()
def run(config, logger, session):
    conditions = Conditions.from_config(config)
    query_filter = stale_timestamp_filter(*conditions.culled())

    query = session.query(Host).filter(query_filter)

    events = delete_hosts(query, None)
    for host_id, deleted in events:
        if deleted:
            logger.info("Deleted host: %s", host_id)
        else:
            logger.info("Host %s already deleted. Delete event not emitted.", host_id)


def main(config_name, logger):
    config = _init_config(config_name)

    registry = CollectorRegistry()
    for metric in COLLECTED_METRICS:
        registry.register(metric)

    Session = _init_db(config)
    session = Session()

    try:
        with session_guard(session):
            run(config, logger, session)
    finally:
        # flush()

        job = _prometheus_job(config.kubernetes_namespace)
        push_to_gateway(config.prometheus_pushgateway, job, registry)


if __name__ == "__main__":
    configure_logging(RUNTIME_ENVIRONMENT)

    logger = get_logger(LOGGER_NAME)
    sys.excepthook = partial(_excepthook, logger)

    threadctx.request_id = UNKNOWN_REQUEST_ID_VALUE
    main(logger)
