#!/usr/bin/env python
import json
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from unittest import main
from unittest.mock import ANY
from unittest.mock import patch

import dateutil.parser

from app.utils import HostWrapper
from tests.test_api_utils import ACCOUNT
from tests.test_api_utils import generate_uuid
from tests.test_api_utils import HOST_URL
from tests.test_api_utils import now
from tests.test_api_utils import PreCreatedHostsBaseTestCase
from tests.test_utils import expected_headers


class PatchHostTestCase(PreCreatedHostsBaseTestCase):
    def setUp(self):
        super().setUp()
        self.now_timestamp = datetime.now(timezone.utc)

    def test_update_fields(self):
        original_id = self.added_hosts[0].id

        patch_docs = [
            {"ansible_host": "NEW_ansible_host"},
            {"ansible_host": ""},
            {"display_name": "fred_flintstone"},
            {"display_name": "fred_flintstone", "ansible_host": "barney_rubble"},
        ]

        for patch_doc in patch_docs:
            with self.subTest(valid_patch_doc=patch_doc):
                with self.app.app_context():
                    response_data = self.patch(f"{HOST_URL}/{original_id}", patch_doc, 200)

                    response_data = self.get(f"{HOST_URL}/{original_id}", 200)

                host = response_data["results"][0]

                for key in patch_doc:
                    self.assertEqual(host[key], patch_doc[key])

    def test_patch_with_branch_id_parameter(self):
        patch_doc = {"display_name": "branch_id_test"}

        url_host_id_list = self._build_host_id_list_for_url(self.added_hosts)

        test_url = f"{HOST_URL}/{url_host_id_list}?branch_id=123"

        with self.app.app_context():
            self.patch(test_url, patch_doc, 200)

    def test_update_fields_on_multiple_hosts(self):
        patch_doc = {"display_name": "fred_flintstone", "ansible_host": "barney_rubble"}

        url_host_id_list = self._build_host_id_list_for_url(self.added_hosts)

        test_url = f"{HOST_URL}/{url_host_id_list}"

        with self.app.app_context():
            self.patch(test_url, patch_doc, 200)

            response_data = self.get(test_url, 200)

        for host in response_data["results"]:
            for key in patch_doc:
                self.assertEqual(host[key], patch_doc[key])

    def test_patch_on_non_existent_host(self):
        non_existent_id = generate_uuid()

        patch_doc = {"ansible_host": "NEW_ansible_host"}

        with self.app.app_context():
            self.patch(f"{HOST_URL}/{non_existent_id}", patch_doc, status=404)

    def test_patch_on_multiple_hosts_with_some_non_existent(self):
        non_existent_id = generate_uuid()
        original_id = self.added_hosts[0].id

        patch_doc = {"ansible_host": "NEW_ansible_host"}

        with self.app.app_context():
            self.patch(f"{HOST_URL}/{non_existent_id},{original_id}", patch_doc)

    def test_invalid_data(self):
        original_id = self.added_hosts[0].id

        invalid_data_list = [
            {"ansible_host": "a" * 256},
            {"ansible_host": None},
            {},
            {"display_name": None},
            {"display_name": ""},
        ]

        for patch_doc in invalid_data_list:
            with self.subTest(invalid_patch_doc=patch_doc):
                with self.app.app_context():
                    response = self.patch(f"{HOST_URL}/{original_id}", patch_doc, status=400)

                self.verify_error_response(response, expected_title="Bad Request", expected_status=400)

    def test_invalid_host_id(self):
        patch_doc = {"display_name": "branch_id_test"}
        host_id_lists = ["notauuid", f"{self.added_hosts[0].id},notauuid"]

        for host_id_list in host_id_lists:
            with self.subTest(host_id_list=host_id_list):
                with self.app.app_context():
                    self.patch(f"{HOST_URL}/{host_id_list}", patch_doc, 400)

    def _base_patch_produces_update_event_test(self, host_to_patch, headers, expected_request_id):
        patch_doc = {"display_name": "patch_event_test"}

        with self.app.app_context():
            with patch("app.queue.events.datetime", **{"now.return_value": self.now_timestamp}):
                self.patch(f"{HOST_URL}/{host_to_patch.id}", patch_doc, 200, extra_headers=headers)

        expected_event_message = {
            "type": "updated",
            "host": {
                "account": host_to_patch.account,
                "ansible_host": host_to_patch.ansible_host,
                "bios_uuid": host_to_patch.bios_uuid,
                "created": host_to_patch.created,
                "culled_timestamp": (
                    dateutil.parser.parse(host_to_patch.stale_timestamp) + timedelta(weeks=2)
                ).isoformat(),
                "display_name": "patch_event_test",
                "external_id": host_to_patch.external_id,
                "fqdn": host_to_patch.fqdn,
                "id": host_to_patch.id,
                "insights_id": host_to_patch.insights_id,
                "ip_addresses": host_to_patch.ip_addresses,
                "mac_addresses": host_to_patch.mac_addresses,
                "reporter": host_to_patch.reporter,
                "rhel_machine_id": host_to_patch.rhel_machine_id,
                "satellite_id": host_to_patch.satellite_id,
                "stale_timestamp": host_to_patch.stale_timestamp,
                "stale_warning_timestamp": (
                    dateutil.parser.parse(host_to_patch.stale_timestamp) + timedelta(weeks=1)
                ).isoformat(),
                "subscription_manager_id": host_to_patch.subscription_manager_id,
                "system_profile": {},
                "tags": host_to_patch.tags,
                "updated": host_to_patch.updated,
            },
            "platform_metadata": None,
            "metadata": {"request_id": expected_request_id},
            "timestamp": self.now_timestamp.isoformat(),
        }

        self.assertEqual(json.loads(self.app.event_producer.event), expected_event_message)
        self.assertEqual(self.app.event_producer.key, host_to_patch.id)
        self.assertEqual(
            self.app.event_producer.headers,
            expected_headers("updated", expected_request_id, host_to_patch.insights_id),
        )

    def test_patch_produces_update_event_no_request_id(self):
        with self.app.app_context():
            self._base_patch_produces_update_event_test(self.added_hosts[0], {}, "-1")

    def test_patch_produces_update_event_with_request_id(self):
        request_id = generate_uuid()
        headers = {"x-rh-insights-request-id": request_id}
        with self.app.app_context():
            self._base_patch_produces_update_event_test(self.added_hosts[0], headers, request_id)

    def test_patch_produces_update_event_no_insights_id(self):
        host = HostWrapper(
            {
                "account": ACCOUNT,
                "subscription_manager_id": generate_uuid(),
                "stale_timestamp": now().isoformat(),
                "reporter": "test",
            }
        )
        response_data = self._create_host(host)
        created_host = HostWrapper(response_data["host"])

        with self.app.app_context():
            self._base_patch_produces_update_event_test(created_host, {}, ANY)

    def test_event_producer_instrumentation(self):
        from unittest.mock import Mock
        from unittest.mock import ANY

        class MockFuture:
            def __init__(self):
                self.callbacks = []
                self.errbacks = []

            def add_callback(self, *args, **kwargs):
                self.callbacks.append((args, kwargs))

            def add_errback(self, *args, **kwargs):
                self.errbacks.append((args, kwargs))

            def success(self):
                for args, kwargs in self.callbacks:
                    method = args[0]
                    args_ = args[1:] + (Mock(),)
                    method(*args_, **kwargs)

            def failure(self):
                for args, kwargs in self.errbacks:
                    method = args[0]
                    args_ = args[1:] + (Mock(),)
                    method(*args_, **kwargs)

        mock_future = MockFuture()

        from app.queue.event_producer import EventProducer

        with patch("app.queue.event_producer.KafkaProducer", **{"return_value.send.return_value": mock_future}):
            self.app.event_producer = EventProducer(self.app.config["INVENTORY_CONFIG"])

        patch_doc = {"display_name": "patch_event_test"}
        host_to_patch = self.added_hosts[0].id

        with self.app.app_context():
            with patch("app.queue.events.datetime", **{"now.return_value": self.now_timestamp}):
                with patch("app.queue.event_producer.message_produced") as message_produced:
                    with patch("app.queue.event_producer.message_not_produced") as message_not_produced:
                        self.patch(f"{HOST_URL}/{host_to_patch}", patch_doc, 200)
            mock_future.success()
            message_produced.assert_called_once_with(*mock_future.callbacks[0][0][1:], ANY)
            mock_future.failure()
            message_not_produced.assert_called_once_with(*mock_future.errbacks[0][0][1:], ANY)


if __name__ == "__main__":
    main()
