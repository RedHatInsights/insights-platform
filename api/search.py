import logging

from api import api_operation, metrics
from app.auth import current_identity
from app.models import SearchSchema

from .host import build_paginated_host_list_response, get_host_list_by_id_list

logger = logging.getLogger(__name__)


@api_operation
@metrics.api_request_time.time()
def post(post_body, page=1, per_page=100):
    validated_input = SearchSchema(strict=True).load(post_body)
    include = validated_input.data["include_fields"]
    exclude = []

    if "facts" not in include:
        exclude.append("facts")
    if "system_profile_facts" not in include:
        exclude.append("system_profile_facts")

    query = get_host_list_by_id_list(current_identity.account_number,
                                     validated_input.data["host_id_list"],
                                     exclude)
    query_results = query.paginate(page, per_page, True)
    return build_paginated_host_list_response(
        query_results.total, page, per_page, query_results.items, exclude
    )
