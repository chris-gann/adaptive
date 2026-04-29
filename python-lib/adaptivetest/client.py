import logging
import xml.etree.ElementTree as ET

import requests

from .errors import AdaptiveError

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.adaptiveplanning.com/api"
DEFAULT_API_VERSION = "v40"
DEFAULT_TIMEOUT = 120


class AdaptiveClient(object):
    def __init__(self, instance_code, username, password,
                 api_version=DEFAULT_API_VERSION, base_url=DEFAULT_BASE_URL,
                 caller_name="Dataiku-DSS", timeout=DEFAULT_TIMEOUT, session=None):
        if not instance_code:
            raise ValueError("instance_code is required")
        if not username:
            raise ValueError("username is required")
        if password is None:
            raise ValueError("password is required")
        self.instance_code = instance_code
        self.username = username
        self._password = password
        self.api_version = api_version or DEFAULT_API_VERSION
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self.caller_name = caller_name
        self.timeout = timeout
        self._session = session or requests.Session()

    @classmethod
    def from_preset(cls, preset):
        if not preset:
            raise ValueError("Adaptive credentials preset is empty")
        return cls(
            instance_code=preset.get("instance_code"),
            username=preset.get("username"),
            password=preset.get("password"),
            api_version=preset.get("api_version") or DEFAULT_API_VERSION,
            base_url=preset.get("base_url") or DEFAULT_BASE_URL,
        )

    @property
    def endpoint(self):
        return "{}/{}".format(self.base_url, self.api_version)

    @property
    def login(self):
        if "@" in self.username:
            return self.username
        return "{}@{}".format(self.username, self.instance_code)

    def post(self, method, body_elements=None):
        envelope = ET.Element("call", {"method": method, "callerName": self.caller_name})
        ET.SubElement(envelope, "credentials", {
            "login": self.login,
            "password": self._password,
        })
        for el in (body_elements or []):
            envelope.append(el)
        payload = ET.tostring(envelope, encoding="utf-8", xml_declaration=True)
        logger.debug("POST %s method=%s bytes=%d", self.endpoint, method, len(payload))
        try:
            response = self._session.post(
                self.endpoint,
                data=payload,
                headers={"Content-Type": "application/xml", "Accept": "application/xml"},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise AdaptiveError(str(exc), method=method)
        if response.status_code >= 400:
            raise AdaptiveError(
                "HTTP error: {}".format(response.text[:500]),
                http_status=response.status_code,
                method=method,
            )
        try:
            root = ET.fromstring(response.content)
        except ET.ParseError as exc:
            raise AdaptiveError(
                "Could not parse response XML: {}".format(exc),
                http_status=response.status_code,
                method=method,
            )
        success = root.get("success")
        if success is not None and success != "1":
            messages = [m.text or "" for m in root.iter("message") if (m.text or "").strip()]
            detail = "; ".join(messages) or "Adaptive returned success=0"
            raise AdaptiveError(detail, http_status=response.status_code, method=method)
        return root
