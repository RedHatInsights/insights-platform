import json
import re
import urllib

#TODO: REMOVE
from app.logging import get_logger
logger = get_logger(__name__)

class HostWrapper:
    def __init__(self, data=None):
        self.__data = data or {}

    def data(self):
        return self.__data

    def __delattr__(self, name):
        if name in self.__data:
            del self.__data[name]
        # else:
        #    raise AttributeError("No such attribute: " + name)

    @property
    def insights_id(self):
        return self.__data.get("insights_id", None)

    @insights_id.setter
    def insights_id(self, cf):
        self.__data["insights_id"] = cf

    @property
    def rhel_machine_id(self):
        return self.__data.get("rhel_machine_id", None)

    @rhel_machine_id.setter
    def rhel_machine_id(self, cf):
        self.__data["rhel_machine_id"] = cf

    @property
    def subscription_manager_id(self):
        return self.__data.get("subscription_manager_id", None)

    @subscription_manager_id.setter
    def subscription_manager_id(self, cf):
        self.__data["subscription_manager_id"] = cf

    @property
    def satellite_id(self):
        return self.__data.get("satellite_id", None)

    @satellite_id.setter
    def satellite_id(self, cf):
        self.__data["satellite_id"] = cf

    @property
    def bios_uuid(self):
        return self.__data.get("bios_uuid", None)

    @bios_uuid.setter
    def bios_uuid(self, cf):
        self.__data["bios_uuid"] = cf

    @property
    def ip_addresses(self):
        return self.__data.get("ip_addresses", None)

    @ip_addresses.setter
    def ip_addresses(self, cf):
        self.__data["ip_addresses"] = cf

    @property
    def fqdn(self):
        return self.__data.get("fqdn")

    @fqdn.setter
    def fqdn(self, cf):
        self.__data["fqdn"] = cf

    @property
    def mac_addresses(self):
        return self.__data.get("mac_addresses", None)

    @mac_addresses.setter
    def mac_addresses(self, cf):
        self.__data["mac_addresses"] = cf

    @property
    def external_id(self):
        return self.__data.get("external_id")

    @external_id.setter
    def external_id(self, cf):
        self.__data["external_id"] = cf

    @property
    def facts(self):
        return self.__data.get("facts", None)

    @facts.setter
    def facts(self, facts):
        self.__data["facts"] = facts

    @property
    def tags(self):
        return self.__data.get("tags", None)

    @tags.setter
    def tags(self, tags):
        self.__data["tags"] = tags

    @property
    def id(self):
        return self.__data.get("id", None)

    @id.setter
    def id(self, id):
        self.__data["id"] = id

    @property
    def account(self):
        return self.__data.get("account", None)

    @account.setter
    def account(self, account):
        self.__data["account"] = account

    @property
    def display_name(self):
        return self.__data.get("display_name", None)

    @display_name.setter
    def display_name(self, display_name):
        self.__data["display_name"] = display_name

    @property
    def ansible_host(self):
        return self.__data.get("ansible_host", None)

    @ansible_host.setter
    def ansible_host(self, ansible_host):
        self.__data["ansible_host"] = ansible_host

    def to_json(self):
        return json.dumps(self.__data)

    @classmethod
    def from_json(cls, d):
        return cls(json.loads(d))

'''
Tagging: functions for converting tags between valid representations
'''
class Tag: 
    def __init__(self, namespace=None, key=None, value=None):
        self.__data = {
            "namespace": namespace,
            "key": key,
            "value": value
        }

    def data(self):
        return self.__data

    @property
    def namespace(self):
        return self.__data.get("namespace", None)

    @namespace.setter
    def namespace(self, namespace):
        self.__data["namespace"] = namespace

    @property
    def key(self):
        return self.__data.get("key", None)

    @key.setter
    def key(self, key):
        self.__data["key"] = key

    @property
    def value(self):
        return self.__data.get("value", None)

    @value.setter
    def value(self, value):
        self.__data["value"] = value

    def _split_string_tag(self, string_tag):
        namespace = None
        key = None 
        value = None

        if(re.match(r"\w+\/\w+=\w+", string_tag)):  # NS/key=value
            namespace, key, value = re.split(r"/|=", string_tag)
        elif(re.match(r"\w+\/\w+", string_tag)):  # NS/key
            namespace, key = re.split(r"/", string_tag)
        elif(re.match(r"\w+=\w+", string_tag)):  # key=value
            key, value = re.split(r"=", string_tag)
        else:  # key
            key = string_tag

        return (namespace, key, value)

    def _create_nested(self, namespace, key, value):
        return {
            namespace: {
                key: [
                    value
                ]
            }
        }

    def from_string(self, string_tag):
        namespace, key, value = self._split_string_tag(string_tag)

        self.namespace = namespace
        self.key = key
        self.value = value

        return self

    def from_nested(self, nested_tag):
        namespace, key, value = None, None, None

        if len(nested_tag.keys()) > 1:
            return "too many keys"
        else:
            namespace = list(nested_tag.keys())[0]
            if len(nested_tag[namespace].keys()) > 1:
                return "too many keys"
            else:
                key = list(nested_tag[namespace].keys())[0]
                if len(nested_tag[namespace][key]) > 1:
                    return "too many values"
                else:
                    logger.info("proper nested tag format")
                    value = nested_tag[namespace][key][0]
        
        self.namespace = namespace
        self.key = key
        self.value = value

        return self

    def to_string(self):
        return f"{self.namespace}/{self.key}={self.value}"

    def to_nested(self):
        return {
            self.namespace: {
                self.key: [
                    self.value
                ]
            }
        }

    @staticmethod
    def create_nested_from_tags(tags):
        '''
        accepts an array of structured tags and makes a combined nested version
        of the tags
        '''
        nested_tags = {}

        for tag in tags:
            namespace, key, value = tag.namespace, tag.key, tag.value
            if namespace in nested_tags:
                if value == None:
                    if key not in nested_tags[namespace]:
                        nested_tags[namespace][key] = []
                else:
                    if key in nested_tags[namespace]:
                        nested_tags[namespace][key].append(value)
                    else:
                        nested_tags[namespace][key] = [value]
            else:
                if value == None:
                    nested_tags[namespace] = {key: []}
                else:
                    nested_tags[namespace] = {key: [value]}

        return nested_tags