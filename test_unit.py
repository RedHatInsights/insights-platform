#!/usr/bin/env python
from base64 import b64encode
from datetime import datetime
from json import dumps
from random import choice
from unittest import main
from unittest import TestCase
from unittest.mock import Mock
from unittest.mock import patch
from uuid import uuid4

from api import api_operation
from api.host import _order_how
from api.host import _params_to_order_by
from app.auth.identity import from_auth_header
from app.auth.identity import from_bearer_token
from app.auth.identity import Identity
from app.auth.identity import SHARED_SECRET_ENV_VAR
from app.auth.identity import validate
from app.config import Config
from app.exceptions import InputFormatException
from app.exceptions import InventoryException
from app.models import Host as ModelsHost
from app.serialization import CanonicalFacts
from app.serialization import Facts
from app.serialization import Host as SerializationHost
from test_utils import set_environment


class ApiOperationTestCase(TestCase):
    """
    Test the API operation decorator that increments the request counter with every
    call.
    """

    @patch("api.api_request_count.inc")
    def test_counter_is_incremented(self, inc):
        @api_operation
        def func():
            pass

        func()
        inc.assert_called_once_with()

    def test_arguments_are_passed(self):
        old_func = Mock()
        old_func.__name__ = "old_func"
        new_func = api_operation(old_func)

        args = (Mock(),)
        kwargs = {"some_arg": Mock()}

        new_func(*args, **kwargs)
        old_func.assert_called_once_with(*args, **kwargs)

    def test_return_value_is_passed(self):
        old_func = Mock()
        old_func.__name__ = "old_func"
        new_func = api_operation(old_func)
        self.assertEqual(old_func.return_value, new_func())


class AuthIdentityConstructorTestCase(TestCase):
    """
    Tests the Identity module constructors.
    """

    @staticmethod
    def _identity():
        return Identity(account_number="some number")


class AuthIdentityFromAuthHeaderTestCase(AuthIdentityConstructorTestCase):
    """
    Tests creating an Identity from a Base64 encoded JSON string, which is what is in
    the HTTP header.
    """

    def test_valid(self):
        """
        Initialize the Identity object with an encoded payload – a base64-encoded JSON.
        That would typically be a raw HTTP header content.
        """
        expected_identity = self._identity()

        identity_data = expected_identity._asdict()

        identity_data_dicts = [
            identity_data,
            # Test with extra data in the identity dict
            {**identity_data, **{"extra_data": "value"}},
        ]

        for identity_data in identity_data_dicts:
            with self.subTest(identity_data=identity_data):
                identity = {"identity": identity_data}
                json = dumps(identity)
                base64 = b64encode(json.encode())

                try:
                    actual_identity = from_auth_header(base64)
                    self.assertEqual(expected_identity, actual_identity)
                except (TypeError, ValueError):
                    self.fail()

                self.assertEqual(actual_identity.is_trusted_system, False)

    def test_invalid_type(self):
        """
        Initializing the Identity object with an invalid type that can’t be a Base64
        encoded payload should raise a TypeError.
        """
        with self.assertRaises(TypeError):
            from_auth_header(["not", "a", "string"])

    def test_invalid_value(self):
        """
        Initializing the Identity object with an invalid Base6č encoded payload should
        raise a ValueError.
        """
        with self.assertRaises(ValueError):
            from_auth_header("invalid Base64")

    def test_invalid_format(self):
        """
        Initializing the Identity object with an valid Base64 encoded payload
        that does not contain the "identity" field.
        """
        identity = self._identity()

        dict_ = identity._asdict()
        json = dumps(dict_)
        base64 = b64encode(json.encode())

        with self.assertRaises(KeyError):
            from_auth_header(base64)


class AuthIdentityValidateTestCase(TestCase):
    def test_valid(self):
        try:
            identity = Identity(account_number="some number")
            validate(identity)
            self.assertTrue(True)
        except ValueError:
            self.fail()

    def test_invalid(self):
        account_numbers = [None, ""]
        for account_number in account_numbers:
            with self.subTest(account_number=account_number):
                with self.assertRaises(ValueError):
                    Identity(account_number=account_number)


class TrustedIdentityTestCase(TestCase):
    shared_secret = "ImaSecret"

    def _build_id(self):
        identity = from_bearer_token(self.shared_secret)
        return identity

    def test_validation(self):
        identity = self._build_id()

        with set_environment({SHARED_SECRET_ENV_VAR: self.shared_secret}):
            validate(identity)

    def test_validation_with_invalid_identity(self):
        identity = from_bearer_token("InvalidPassword")

        with self.assertRaises(ValueError):
            validate(identity)

    def test_validation_env_var_not_set(self):
        identity = self._build_id()

        with set_environment({}):
            with self.assertRaises(ValueError):
                validate(identity)

    def test_validation_token_is_None(self):
        tokens = [None, ""]
        for token in tokens:
            with self.subTest(token_value=token):
                with self.assertRaises(ValueError):
                    Identity(token=token)

    def test_is_trusted_system(self):
        identity = self._build_id()

        self.assertEqual(identity.is_trusted_system, True)

    def test_account_number_is_not_set_for_trusted_system(self):
        identity = self._build_id()

        self.assertEqual(identity.account_number, None)


class ConfigTestCase(TestCase):
    def test_configuration_with_env_vars(self):
        app_name = "brontocrane"
        path_prefix = "r/slaterock/platform"
        expected_base_url = f"/{path_prefix}/{app_name}"
        expected_api_path = f"{expected_base_url}/v1"
        expected_mgmt_url_path_prefix = "/mgmt_testing"

        new_env = {
            "INVENTORY_DB_USER": "fredflintstone",
            "INVENTORY_DB_PASS": "bedrock1234",
            "INVENTORY_DB_HOST": "localhost",
            "INVENTORY_DB_NAME": "SlateRockAndGravel",
            "INVENTORY_DB_POOL_TIMEOUT": "3",
            "INVENTORY_DB_POOL_SIZE": "8",
            "APP_NAME": app_name,
            "PATH_PREFIX": path_prefix,
            "INVENTORY_MANAGEMENT_URL_PATH_PREFIX": expected_mgmt_url_path_prefix,
        }

        with set_environment(new_env):

            conf = Config()

            self.assertEqual(conf.db_uri, "postgresql://fredflintstone:bedrock1234@localhost/SlateRockAndGravel")
            self.assertEqual(conf.db_pool_timeout, 3)
            self.assertEqual(conf.db_pool_size, 8)
            self.assertEqual(conf.api_url_path_prefix, expected_api_path)
            self.assertEqual(conf.mgmt_url_path_prefix, expected_mgmt_url_path_prefix)

    def test_config_default_settings(self):
        expected_api_path = "/api/inventory/v1"
        expected_mgmt_url_path_prefix = "/"

        # Make sure the environment variables are not set
        with set_environment(None):

            conf = Config()

            self.assertEqual(conf.db_uri, "postgresql://insights:insights@localhost/insights")
            self.assertEqual(conf.api_url_path_prefix, expected_api_path)
            self.assertEqual(conf.mgmt_url_path_prefix, expected_mgmt_url_path_prefix)
            self.assertEqual(conf.db_pool_timeout, 5)
            self.assertEqual(conf.db_pool_size, 5)

    def test_config_development_settings(self):
        with set_environment({"INVENTORY_DB_POOL_TIMEOUT": "3"}):

            conf = Config()

            self.assertEqual(conf.db_pool_timeout, 3)


class HostOrderHowTestCase(TestCase):
    def test_asc(self):
        column = Mock()
        result = _order_how(column, "ASC")
        self.assertEqual(result, column.asc())

    def test_desc(self):
        column = Mock()
        result = _order_how(column, "DESC")
        self.assertEqual(result, column.desc())

    def test_error(self):
        invalid_values = (None, "asc", "desc", "BBQ")
        for invalid_value in invalid_values:
            with self.subTest(order_how=invalid_value):
                with self.assertRaises(ValueError):
                    _order_how(Mock(), invalid_value)


@patch("api.host._order_how")
@patch("api.host.Host.modified_on")
class HostParamsToOrderByTestCase(TestCase):
    def test_default_is_updated_desc(self, modified_on, order_how):
        actual = _params_to_order_by(None, None)
        expected = (modified_on.desc.return_value,)
        self.assertEqual(actual, expected)
        order_how.assert_not_called()

    def test_default_for_updated_is_desc(self, modified_on, order_how):
        actual = _params_to_order_by("updated", None)
        expected = (modified_on.desc.return_value,)
        self.assertEqual(actual, expected)
        order_how.assert_not_called()

    def test_order_by_updated_asc(self, modified_on, order_how):
        actual = _params_to_order_by("updated", "ASC")
        expected = (order_how.return_value,)
        self.assertEqual(actual, expected)
        order_how.assert_called_once_with(modified_on, "ASC")

    def test_order_by_updated_desc(self, modified_on, order_how):
        actual = _params_to_order_by("updated", "DESC")
        expected = (order_how.return_value,)
        self.assertEqual(actual, expected)
        order_how.assert_called_once_with(modified_on, "DESC")

    @patch("api.host.Host.display_name")
    def test_default_for_display_name_is_asc(self, display_name, modified_on, order_how):
        actual = _params_to_order_by("display_name")
        expected = (display_name.asc.return_value, modified_on.desc.return_value)
        self.assertEqual(actual, expected)
        order_how.assert_not_called()

    @patch("api.host.Host.display_name")
    def test_order_by_display_name_asc(self, display_name, modified_on, order_how):
        actual = _params_to_order_by("display_name", "ASC")
        expected = (order_how.return_value, modified_on.desc.return_value)
        self.assertEqual(actual, expected)
        order_how.assert_called_once_with(display_name, "ASC")

    @patch("api.host.Host.display_name")
    def test_order_by_display_name_desc(self, display_name, modified_on, order_how):
        actual = _params_to_order_by("display_name", "DESC")
        expected = (order_how.return_value, modified_on.desc.return_value)
        self.assertEqual(actual, expected)
        order_how.assert_called_once_with(display_name, "DESC")


class HostParamsToOrderByErrorsTestCase(TestCase):
    def test_order_by_bad_field_raises_error(self):
        with self.assertRaises(ValueError):
            _params_to_order_by(Mock(), "fqdn")

    def test_order_by_only_how_raises_error(self):
        with self.assertRaises(ValueError):
            _params_to_order_by(Mock(), order_how="ASC")


class SerializationHostFromJsonCompoundTestCase(TestCase):
    def test_with_all_fields(self):
        canonical_facts = {
            "insights_id": str(uuid4()),
            "rhel_machine_id": str(uuid4()),
            "subscription_manager_id": str(uuid4()),
            "satellite_id": str(uuid4()),
            "bios_uuid": str(uuid4()),
            "ip_addresses": ["10.10.0.1", "10.0.0.2"],
            "fqdn": "some fqdn",
            "mac_addresses": ["c2:00:d0:c8:61:01"],
            "external_id": "i-05d2313e6b9a42b16",
        }
        unchanged_input = {
            "display_name": "some display name",
            "ansible_host": "some ansible host",
            "account": "some account",
        }
        input = {
            **canonical_facts,
            **unchanged_input,
            "facts": [
                {"namespace": "some namespace", "facts": {"some key": "some value"}},
                {"namespace": "another namespace", "facts": {"another key": "another value"}},
            ],
            "system_profile": {
                "number_of_cpus": 1,
                "number_of_sockets": 2,
                "cores_per_socket": 3,
                "system_memory_bytes": 4,
            },
        }

        actual = SerializationHost.from_json(input)
        expected = {
            "canonical_facts": canonical_facts,
            **unchanged_input,
            "facts": {item["namespace"]: item["facts"] for item in input["facts"]},
            "system_profile_facts": input["system_profile"],
        }

        self.assertIs(ModelsHost, type(actual))
        for key, value in expected.items():
            self.assertEqual(value, getattr(actual, key))

    def test_with_only_one_canonical_fact(self):
        canonical_fact_fields = (
            "insights_id",
            "rhel_machine_id",
            "subscription_manager_id",
            "satellite_id",
            "bios_uuid",
            "ip_addresses",
            "fqdn",
            "mac_addresses",
            "external_id",
        )
        for field in canonical_fact_fields:
            with self.subTest(canonical_fact=field):
                canonical_facts = {field: "some value"}
                host = SerializationHost.from_json(canonical_facts)

                self.assertIs(ModelsHost, type(host))
                self.assertEqual(canonical_facts, host.canonical_facts)
                self.assertIsNone(host.display_name)
                self.assertIsNone(host.ansible_host)
                self.assertIsNone(host.account)
                self.assertEqual({}, host.facts)
                self.assertEqual({}, host.system_profile_facts)

    def test_without_canonical_facts(self):
        inputs = (
            {},
            {"display_name": "some display name"},
            {"account": "some account"},
            {"ansible_host": "some ansible_host"},
            {"facts": {"some namespace": {"some key": "some value"}}},
            {"system_profile": {"number_of_cpus": 1}},
        )
        for input_ in inputs:
            with self.subTest(input=input_):
                with self.assertRaises(InventoryException):
                    SerializationHost.from_json(input_)

    def test_with_ansible_host_empty_string(self):
        input_ = {"fqdn": "some fqdn", "ansible_host": ""}
        host = SerializationHost.from_json(input_)

        self.assertIs(ModelsHost, type(host))
        self.assertIsNotNone(host.ansible_host)
        self.assertEqual("", host.ansible_host)


@patch("app.serialization.ModelsHost")
@patch("app.serialization.Facts.from_json")
@patch("app.serialization.CanonicalFacts.from_json")
class SerializationHostFromJsonMockedTestCase(TestCase):
    COMMON_INPUT = {
        "display_name": "some display name",
        "ansible_host": "some ansible host",
        "account": "some account",
        "insights_id": str(uuid4()),
        "rhel_machine_id": str(uuid4()),
        "subscription_manager_id": str(uuid4()),
        "satellite_id": str(uuid4()),
        "bios_uuid": str(uuid4()),
        "ip_addresses": ["10.10.0.1", "10.0.0.2"],
        "fqdn": "some fqdn",
        "mac_addresses": ["c2:00:d0:c8:61:01"],
        "external_id": "i-05d2313e6b9a42b16",
        "facts": {"some namespace": {"some key": "some value"}, "another namespace": {"another key": "another value"}},
        "system_profile": {
            "number_of_cpus": 1,
            "number_of_sockets": 2,
            "cores_per_socket": 3,
            "system_memory_bytes": 4,
        },
    }
    DEFAULT_VALUES = (
        ("display_name", (None, ""), None),
        ("ansible_host", (None,), None),
        ("system_profile", (None, {}), {}),
    )

    def _reset_mocks(self, mocks):
        for mock in mocks:
            mock.reset_mock()

    def test_with_all_fields(self, canonical_facts_from_json, facts_from_json, models_host):
        full_input = self.COMMON_INPUT

        result = SerializationHost.from_json(full_input)
        self.assertEqual(models_host.return_value, result)

        canonical_facts_from_json.assert_called_once_with(full_input)
        facts_from_json.assert_called_once_with(full_input["facts"])
        models_host.assert_called_once_with(
            canonical_facts=canonical_facts_from_json.return_value,
            facts=facts_from_json.return_value,
            display_name=full_input["display_name"],
            ansible_host=full_input["ansible_host"],
            account=full_input["account"],
            system_profile_facts=full_input["system_profile"],
        )

    def test_without_facts(self, canonical_facts_from_json, facts_from_json, models_host):
        full_input = {key: value for key, value in self.COMMON_INPUT.items() if key != "facts"}

        result = SerializationHost.from_json(full_input)
        self.assertEqual(models_host.return_value, result)

        canonical_facts_from_json.assert_called_once_with(full_input)
        facts_from_json.assert_called_once_with(None)
        models_host.assert_called_once_with(
            canonical_facts=canonical_facts_from_json.return_value,
            facts=facts_from_json.return_value,
            display_name=full_input["display_name"],
            ansible_host=full_input["ansible_host"],
            account=full_input["account"],
            system_profile_facts=full_input["system_profile"],
        )

    def test_default_values_when_missing(self, canonical_facts_from_json, facts_from_json, models_host):
        for input_field, _, default_value in self.DEFAULT_VALUES:
            with self.subTest(input_field=input_field):
                self._reset_mocks((canonical_facts_from_json, facts_from_json, models_host))

                full_input = {key: value for key, value in self.COMMON_INPUT.items() if key != input_field}

                result = SerializationHost.from_json(full_input)
                self.assertEqual(models_host.return_value, result)

                canonical_facts_from_json.assert_called_once_with(full_input)
                facts_from_json.assert_called_once_with(full_input["facts"])

                models_host.assert_called_once_with(
                    canonical_facts=canonical_facts_from_json.return_value,
                    facts=facts_from_json.return_value,
                    account=full_input["account"],
                    display_name=default_value if input_field == "display_name" else full_input["display_name"],
                    ansible_host=default_value if input_field == "ansible_host" else full_input["ansible_host"],
                    system_profile_facts=default_value
                    if input_field == "system_profile"
                    else full_input["system_profile"],
                )

    def test_default_values_when_empty(self, canonical_facts_from_json, facts_from_json, models_host):
        for input_field, empty_input_values, default_value in self.DEFAULT_VALUES:
            for input_value in empty_input_values:
                with self.subTest(field=input_field, input_value=input_value):
                    self._reset_mocks((canonical_facts_from_json, facts_from_json, models_host))

                    full_input = {**{key: value for key, value in self.COMMON_INPUT.items()}, input_field: input_value}

                    result = SerializationHost.from_json(full_input)
                    self.assertEqual(models_host.return_value, result)

                    canonical_facts_from_json.assert_called_once_with(full_input)
                    facts_from_json.assert_called_once_with(full_input["facts"])
                    models_host.assert_called_once_with(
                        canonical_facts=canonical_facts_from_json.return_value,
                        facts=facts_from_json.return_value,
                        account=full_input["account"],
                        display_name=default_value if input_field == "display_name" else full_input["display_name"],
                        ansible_host=default_value if input_field == "ansible_host" else full_input["ansible_host"],
                        system_profile_facts=default_value
                        if input_field == "system_profile"
                        else full_input["system_profile"],
                    )

    def test_ansible_host_can_be_empty_string(self, canonical_facts_from_json, facts_from_json, models_host):
        full_input = {**self.COMMON_INPUT, "ansible_host": ""}

        result = SerializationHost.from_json(full_input)
        self.assertEqual(models_host.return_value, result)

        canonical_facts_from_json.assert_called_once_with(full_input)
        facts_from_json.assert_called_once_with(full_input["facts"])
        models_host.assert_called_once_with(
            canonical_facts=canonical_facts_from_json.return_value,
            facts=facts_from_json.return_value,
            display_name=full_input["display_name"],
            ansible_host=full_input["ansible_host"],
            account=full_input["account"],
            system_profile_facts=full_input["system_profile"],
        )


class SerializationHostToJsonBaseTestCase(TestCase):
    @staticmethod
    def _timestamp_to_str(timestamp):
        formatted = timestamp.isoformat()
        return f"{formatted}Z"

    @staticmethod
    def _generate_host_saved_values():
        return {"id": uuid4(), "created_on": datetime.utcnow(), "modified_on": datetime.utcnow()}

    @classmethod
    def _convert_host_saved_values(cls, attrs):
        return {
            "id": str(attrs["id"]),
            "created": cls._timestamp_to_str(attrs["created_on"]),
            "updated": cls._timestamp_to_str(attrs["modified_on"]),
        }

    @staticmethod
    def _convert_facts(facts):
        return [{"namespace": namespace, "facts": facts} for namespace, facts in facts.items()]


class SerializationHostToJsonCompoundTestCase(SerializationHostToJsonBaseTestCase):
    def test_with_all_fields(self):
        canonical_facts = {
            "insights_id": str(uuid4()),
            "rhel_machine_id": str(uuid4()),
            "subscription_manager_id": str(uuid4()),
            "satellite_id": str(uuid4()),
            "bios_uuid": str(uuid4()),
            "ip_addresses": ["10.10.0.1", "10.0.0.2"],
            "fqdn": "some fqdn",
            "mac_addresses": ["c2:00:d0:c8:61:01"],
            "external_id": "i-05d2313e6b9a42b16",
        }
        raw_values = {
            "display_name": "some display name",
            "ansible_host": "some ansible host",
            "account": "some account",
        }
        facts = {"some namespace": {"some key": "some value"}, "another namespace": {"another key": "another value"}}
        saved_values = self._generate_host_saved_values()

        host = ModelsHost(canonical_facts=canonical_facts, **raw_values, facts=facts, **saved_values)

        self.assertEqual(
            {
                **canonical_facts,
                **raw_values,
                "facts": self._convert_facts(facts),
                **self._convert_host_saved_values(saved_values),
            },
            SerializationHost.to_json(host),
        )

    def test_with_only_required_fields(self):
        canonical_facts = {"fqdn": "some fqdn"}
        raw_values = {"display_name": None, "account": None}  # Required only because of a bug
        saved_values = self._generate_host_saved_values()
        host = ModelsHost(canonical_facts=canonical_facts, **raw_values, facts={}, **saved_values)
        self.assertEqual(
            {
                **canonical_facts,
                "insights_id": None,
                "rhel_machine_id": None,
                "subscription_manager_id": None,
                "satellite_id": None,
                "bios_uuid": None,
                "ip_addresses": None,
                "mac_addresses": None,
                "external_id": None,
                **raw_values,
                "ansible_host": None,
                "facts": [],
                **self._convert_host_saved_values(saved_values),
            },
            SerializationHost.to_json(host),
        )

    def test_with_ansible_host_empty_string(self):
        canonical_facts = {"fqdn": "some fqdn"}
        raw_values = {"display_name": None, "account": None, "ansible_host": ""}
        saved_values = self._generate_host_saved_values()
        host = ModelsHost(canonical_facts=canonical_facts, **raw_values, facts={}, **saved_values)

        serialized = SerializationHost.to_json(host)
        self.assertIn("ansible_host", serialized)
        self.assertIsNotNone(serialized["ansible_host"])
        self.assertEquals("", serialized["ansible_host"])


@patch("app.serialization.Facts.to_json")
@patch("app.serialization.CanonicalFacts.to_json")
class SerializationHostToJsonMockedTestCase(SerializationHostToJsonBaseTestCase):
    def test_with_all_fields(self, canonical_facts_to_json, facts_to_json):
        canonical_facts = {
            "insights_id": str(uuid4()),
            "rhel_machine_id": str(uuid4()),
            "subscription_manager_id": str(uuid4()),
            "satellite_id": str(uuid4()),
            "bios_uuid": str(uuid4()),
            "ip_addresses": ["10.10.0.1", "10.0.0.2"],
            "fqdn": "some fqdn",
            "mac_addresses": ["c2:00:d0:c8:61:01"],
            "external_id": "i-05d2313e6b9a42b16",
        }
        canonical_facts_to_json.return_value = canonical_facts

        facts = {"some namespace": {"some key": "some value"}, "another namespace": {"another key": "another value"}}
        facts_to_json.return_value = self._convert_facts(facts)

        raw_values = {
            "display_name": "some display name",
            "ansible_host": "some ansible host",
            "account": "some account",
        }
        saved_values = self._generate_host_saved_values()
        host = ModelsHost(canonical_facts=canonical_facts, **raw_values, facts=facts, **saved_values)

        self.assertEqual(
            {
                **canonical_facts,
                **raw_values,
                "facts": facts_to_json.return_value,
                **self._convert_host_saved_values(saved_values),
            },
            SerializationHost.to_json(host),
        )

        canonical_facts_to_json.assert_called_once_with(canonical_facts)
        facts_to_json.assert_called_once_with(facts)

    def test_with_ansible_host_empty_string(self, canonical_facts_to_json, facts_to_json):
        canonical_facts = {
            "insights_id": str(uuid4()),
            "rhel_machine_id": str(uuid4()),
            "subscription_manager_id": str(uuid4()),
            "satellite_id": str(uuid4()),
            "bios_uuid": str(uuid4()),
            "ip_addresses": ["10.10.0.1", "10.0.0.2"],
            "fqdn": "some fqdn",
            "mac_addresses": ["c2:00:d0:c8:61:01"],
            "external_id": "i-05d2313e6b9a42b16",
        }
        canonical_facts_to_json.return_value = canonical_facts
        facts_to_json.return_value = []

        raw_values = {"display_name": "some display name", "ansible_host": "", "account": "some account"}
        saved_values = self._generate_host_saved_values()
        host = ModelsHost(canonical_facts=canonical_facts, **raw_values, facts={}, **saved_values)

        serialized = SerializationHost.to_json(host)
        self.assertIn("ansible_host", serialized)
        self.assertIsNotNone(serialized["ansible_host"])
        self.assertEqual("", serialized["ansible_host"])


class SerializationHostToSystemProfileJsonTestCase(TestCase):
    def test_non_empty_profile_is_not_changed(self):
        system_profile_facts = {
            "number_of_cpus": 1,
            "number_of_sockets": 2,
            "cores_per_socket": 3,
            "system_memory_bytes": 4,
        }
        host = ModelsHost(
            canonical_facts={"fqdn": "some fqdn"},
            display_name="some display name",
            system_profile_facts=system_profile_facts,
        )
        host.id = uuid4()

        actual = SerializationHost.to_system_profile_json(host)
        expected = {"id": str(host.id), "system_profile": system_profile_facts}
        self.assertEqual(expected, actual)

    def test_empty_profile_is_empty_dict(self):
        host = ModelsHost(canonical_facts={"fqdn": "some fqdn"}, display_name="some display name")
        host.id = uuid4()
        host.system_profile_facts = None

        actual = SerializationHost.to_system_profile_json(host)
        expected = {"id": str(host.id), "system_profile": {}}
        self.assertEqual(expected, actual)


class SerializationCanonicalFactsFromJson(TestCase):
    def _format_uuid_without_hyphens(self, uuid_):
        return uuid_.hex

    def _format_uuid_with_hyphens(self, uuid_):
        return str(uuid_)

    def _randomly_formatted_uuid(self, uuid_):
        transformation = choice((self._format_uuid_without_hyphens, self._format_uuid_with_hyphens))
        return transformation(uuid_)

    def _randomly_formatted_sequence(self, seq):
        transformation = choice((list, tuple))
        return transformation(seq)

    def test_values_are_stored_unchanged(self):
        input = {
            "insights_id": self._randomly_formatted_uuid(uuid4()),
            "rhel_machine_id": self._randomly_formatted_uuid(uuid4()),
            "subscription_manager_id": self._randomly_formatted_uuid(uuid4()),
            "satellite_id": self._randomly_formatted_uuid(uuid4()),
            "bios_uuid": self._randomly_formatted_uuid(uuid4()),
            "ip_addresses": self._randomly_formatted_sequence(("10.10.0.1", "10.10.0.2")),
            "fqdn": "some fqdn",
            "mac_addresses": self._randomly_formatted_sequence(("c2:00:d0:c8:61:01",)),
            "external_id": "i-05d2313e6b9a42b16",
        }
        result = CanonicalFacts.from_json(input)
        self.assertEqual(result, input)

    def test_unknown_fields_are_rejected(self):
        canonical_facts = {
            "insights_id": str(uuid4()),
            "rhel_machine_id": str(uuid4()),
            "subscription_manager_id": str(uuid4()),
            "satellite_id": str(uuid4()),
            "bios_uuid": str(uuid4()),
            "ip_addresses": ("10.10.0.1", "10.10.0.2"),
            "fqdn": "some fqdn",
            "mac_addresses": ["c2:00:d0:c8:61:01"],
            "external_id": "i-05d2313e6b9a42b16",
        }
        input = {**canonical_facts, "unknown": "something"}
        result = CanonicalFacts.from_json(input)
        self.assertEqual(result, canonical_facts)

    def test_empty_fields_are_rejected(self):
        canonical_facts = {"fqdn": "some fqdn"}
        input = {
            **canonical_facts,
            "insights_id": "",
            "rhel_machine_id": None,
            "ip_addresses": [],
            "mac_addresses": tuple(),
        }
        result = CanonicalFacts.from_json(input)
        self.assertEqual(result, canonical_facts)


class SerializationCanonicalFactsToJsonTestCase(TestCase):
    def test_contains_all_values_unchanged(self):
        canonical_facts = {
            "insights_id": str(uuid4()),
            "rhel_machine_id": str(uuid4()),
            "subscription_manager_id": str(uuid4()),
            "satellite_id": str(uuid4()),
            "bios_uuid": str(uuid4()),
            "ip_addresses": ("10.10.0.1", "10.10.0.2"),
            "fqdn": "some fqdn",
            "mac_addresses": ("c2:00:d0:c8:61:01",),
            "external_id": "i-05d2313e6b9a42b16",
        }
        self.assertEqual(canonical_facts, CanonicalFacts.to_json(canonical_facts))

    def test_missing_fields_are_filled_with_none(self):
        canonical_fact_fields = (
            "insights_id",
            "rhel_machine_id",
            "subscription_manager_id",
            "satellite_id",
            "bios_uuid",
            "ip_addresses",
            "fqdn",
            "mac_addresses",
            "external_id",
        )
        self.assertEqual({field: None for field in canonical_fact_fields}, CanonicalFacts.to_json({}))


class SerializationFactsFromJsonTestCase(TestCase):
    def test_non_empty_namespaces_become_dict_items(self):
        input = [
            {"namespace": "first namespace", "facts": {"first key": "first value", "second key": "second value"}},
            {"namespace": "second namespace", "facts": {"third key": "third value"}},
        ]
        self.assertEqual({item["namespace"]: item["facts"] for item in input}, Facts.from_json(input))

    def test_empty_namespaces_remain_unchanged(self):
        for empty_facts in ({}, None):
            with self.subTest(empty_facts=empty_facts):
                input = [
                    {"namespace": "first namespace", "facts": {"first key": "first value"}},
                    {"namespace": "second namespace", "facts": empty_facts},
                ]
                self.assertEqual({item["namespace"]: item["facts"] for item in input}, Facts.from_json(input))

    def test_duplicate_namespaces_are_merged(self):
        input = [
            {"namespace": "first namespace", "facts": {"first key": "first value", "second key": "second value"}},
            {"namespace": "second namespace", "facts": {"third key": "third value"}},
            {"namespace": "first namespace", "facts": {"first key": "fourth value"}},
        ]
        actual = Facts.from_json(input)
        expected = {
            "first namespace": {"first key": "fourth value", "second key": "second value"},
            "second namespace": {"third key": "third value"},
        }
        self.assertEqual(expected, actual)

    def test_none_becomes_empty_dict(self):
        self.assertEqual({}, Facts.from_json(None))

    def test_missing_key_raises_exception(self):
        invalid_items = (
            {"spacename": "second namespace", "facts": {"second key": "second value"}},
            {"namespace": "second namespace", "fact": {"second key": "second value"}},
            {"namespace": "second namespace"},
            {},
        )
        for invalid_item in invalid_items:
            with self.subTest(invalid_item=invalid_item):
                input = [{"namespace": "first namespace", "facts": {"first key": "first value"}}, invalid_item]
                with self.assertRaises(InputFormatException):
                    Facts.from_json(input)


class SerializationFactsToJsonTestCase(TestCase):
    def test_empty_dict_becomes_empty_list(self):
        self.assertEqual([], Facts.to_json({}))

    def test_non_empty_namespaces_become_list_of_dicts(self):
        facts = {
            "first namespace": {"first key": "first value", "second key": "second value"},
            "second namespace": {"third key": "third value"},
        }
        self.assertEqual(
            [{"namespace": namespace, "facts": facts} for namespace, facts in facts.items()], Facts.to_json(facts)
        )

    def test_empty_namespaces_have_facts_as_empty_dicts(self):
        for empty_value in {}, None:
            with self.subTest(empty_value=empty_value):
                facts = {"first namespace": empty_value, "second namespace": {"first key": "first value"}}
                self.assertEqual(
                    [{"namespace": namespace, "facts": facts or {}} for namespace, facts in facts.items()],
                    Facts.to_json(facts),
                )


if __name__ == "__main__":
    main()
