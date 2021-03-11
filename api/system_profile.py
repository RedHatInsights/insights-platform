import flask
from kafka import KafkaConsumer

from api import api_operation
from api import build_collection_response
from api import custom_escape
from api import flask_json_response
from api import metrics
from api.host import get_bulk_query_source
from api.host_query_xjoin import build_sap_sids_filter
from api.host_query_xjoin import build_sap_system_filters
from api.host_query_xjoin import build_tag_query_dict_tuple
from api.host_query_xjoin import owner_id_filter
from app import Permission
from app.auth import get_current_identity
from app.config import BulkQuerySource
from app.config import Config
from app.environment import RuntimeEnvironment
from app.instrumentation import log_get_sap_sids_failed
from app.instrumentation import log_get_sap_sids_succeeded
from app.instrumentation import log_get_sap_system_failed
from app.instrumentation import log_get_sap_system_succeeded
from app.logging import get_logger
from app.xjoin import check_pagination
from app.xjoin import graphql_query
from app.xjoin import pagination_params
from app.xjoin import staleness_filter
from lib.middleware import rbac
from lib.system_profile_validate import validate_sp_for_branch

logger = get_logger(__name__)

# The list of users that are allowed to run the SP validator endpoint.
# We may add the SP team if they find this endpoint useful.
ADMIN_USERS = [
    "aprice@redhat.com",
    "tefaz@redhat.com",
    "rfelton@redhat.com",
    "aarif@redhat.com",
    "gmccullo@redhat.com",
    "rpfannsc@redhat.com",
    "jusun@redhat.com",
    "tuser@redhat.com",
]

SAP_SYSTEM_QUERY = """
    query hostSystemProfile (
        $hostFilter: HostFilter
    ) {
        hostSystemProfile (
            hostFilter: $hostFilter
        ) {
            sap_system {
                meta{
                    total
                    count
                }
                data {
                    value
                    count
                }
            }
        }
    }
"""

SAP_SIDS_QUERY = """
    query hostSystemProfile (
        $hostFilter: HostFilter
        $filter: SapSidFilter
    ) {
        hostSystemProfile (
            hostFilter: $hostFilter
        ) {
            sap_sids (
                filter: $filter
            ) {
                meta {
                    total
                    count
                }
                data {
                    value
                    count
                }
            }
        }
    }
"""


def xjoin_enabled():
    return get_bulk_query_source() == BulkQuerySource.xjoin


@api_operation
@rbac(Permission.READ)
@metrics.api_request_time.time()
def get_sap_system(tags=None, page=None, per_page=None, staleness=None, registered_with=None, filter=None):
    if not xjoin_enabled():
        flask.abort(503)

    limit, offset = pagination_params(page, per_page)

    variables = {
        "hostFilter": {
            # we're not indexing null timestamps in ES
            "OR": list(staleness_filter(staleness))
        }
    }
    hostfilter_and_variables = ()

    if tags:
        hostfilter_and_variables = build_tag_query_dict_tuple(tags)

    if registered_with:
        variables["hostFilter"]["NOT"] = {"insights_id": {"eq": None}}

    if filter:
        if filter.get("system_profile"):
            if filter["system_profile"].get("sap_system"):
                hostfilter_and_variables += build_sap_system_filters(filter["system_profile"].get("sap_system"))
            if filter["system_profile"].get("sap_sids"):
                hostfilter_and_variables += build_sap_sids_filter(filter["system_profile"]["sap_sids"])

    current_identity = get_current_identity()
    if (
        current_identity.identity_type == "System"
        and current_identity.auth_type != "classic-proxy"
        and current_identity.system["cert_type"] == "system"
    ):
        hostfilter_and_variables += owner_id_filter()

    if hostfilter_and_variables != ():
        variables["hostFilter"]["AND"] = hostfilter_and_variables

    response = graphql_query(SAP_SYSTEM_QUERY, variables, log_get_sap_system_failed)

    data = response["hostSystemProfile"]

    check_pagination(offset, data["sap_system"]["meta"]["total"])

    log_get_sap_system_succeeded(logger, data)
    return flask_json_response(
        build_collection_response(data["sap_system"]["data"], page, per_page, data["sap_system"]["meta"]["total"])
    )


@api_operation
@rbac(Permission.READ)
@metrics.api_request_time.time()
def get_sap_sids(search=None, tags=None, page=None, per_page=None, staleness=None, registered_with=None, filter=None):
    if not xjoin_enabled():
        flask.abort(503)

    limit, offset = pagination_params(page, per_page)

    variables = {
        "hostFilter": {
            # we're not indexing null timestamps in ES
            "OR": list(staleness_filter(staleness))
        }
    }

    hostfilter_and_variables = ()

    if tags:
        hostfilter_and_variables = build_tag_query_dict_tuple(tags)

    if registered_with:
        variables["hostFilter"]["NOT"] = {"insights_id": {"eq": None}}

    if search:
        variables["filter"] = {
            # Escaped so that the string literals are not interpreted as regex
            "search": {"regex": f".*{custom_escape(search)}.*"}
        }

    if filter:
        if filter.get("system_profile"):
            if filter["system_profile"].get("sap_system"):
                hostfilter_and_variables += build_sap_system_filters(filter["system_profile"].get("sap_system"))
            if filter["system_profile"].get("sap_sids"):
                hostfilter_and_variables += build_sap_sids_filter(filter["system_profile"]["sap_sids"])

    current_identity = get_current_identity()
    if (
        current_identity.identity_type == "System"
        and current_identity.auth_type != "classic-proxy"
        and current_identity.system["cert_type"] == "system"
    ):
        hostfilter_and_variables += owner_id_filter()

    if hostfilter_and_variables != ():
        variables["hostFilter"]["AND"] = hostfilter_and_variables

    response = graphql_query(SAP_SIDS_QUERY, variables, log_get_sap_sids_failed)

    data = response["hostSystemProfile"]

    check_pagination(offset, data["sap_sids"]["meta"]["total"])

    log_get_sap_sids_succeeded(logger, data)
    return flask_json_response(
        build_collection_response(data["sap_sids"]["data"], page, per_page, data["sap_sids"]["meta"]["total"])
    )


@api_operation
@rbac(Permission.READ)
@metrics.schema_validation_time.time()
def validate_schema(repo_fork="RedHatInsights", repo_branch="master", days=1, max_messages=10000):
    # Use the identity header to make sure the user is someone from our team.
    if get_current_identity().user.get("username") not in ADMIN_USERS:
        flask.abort(401, "This endpoint is restricted to HBI Admins.")

    config = Config(RuntimeEnvironment.SERVICE)
    consumer = KafkaConsumer(
        bootstrap_servers=config.bootstrap_servers,
        api_version=(0, 10, 1),
        value_deserializer=lambda m: m.decode(),
        **config.validator_kafka_consumer,
    )
    try:
        response = validate_sp_for_branch(
            consumer,
            {config.host_ingress_topic, config.additional_validation_topic},
            repo_fork,
            repo_branch,
            days,
            max_messages,
        )
        consumer.close()
        return flask_json_response(response)
    except (ValueError, AttributeError) as e:
        consumer.close()
        flask.abort(400, str(e))
