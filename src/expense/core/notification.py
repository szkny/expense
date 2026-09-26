import base64
import json
import logging
import os
import re
import threading
from typing import Any

from dotenv import load_dotenv
from pywebpush import WebPushException, webpush
from py_vapid import Vapid
from cryptography.hazmat.primitives import serialization

from .base import Base

log: logging.Logger = logging.getLogger("expense")


class NotificationManager(Base):
    """Send notifications through the configured delivery channel."""

    def __init__(self) -> None:
        super().__init__()
        load_dotenv()
        notification_config: dict[str, Any] = self.config.get(
            "notification", {}
        )
        self.channel: str = notification_config.get("channel", "termux")
        web_push_config: dict[str, Any] = notification_config.get(
            "web_push", {}
        )
        self.vapid_public_key: str = str(
            web_push_config.get("vapid_public_key", "")
        )
        private_key_env = str(
            web_push_config.get(
                "vapid_private_key_env", "EXPENSE_VAPID_PRIVATE_KEY"
            )
        )
        self.vapid_private_key: str = os.getenv(private_key_env, "")
        self.vapid_subject: str = str(web_push_config.get("vapid_subject", ""))
        self.subscription_path = self.data_path / "web_push_subscriptions.json"
        self._subscription_lock = threading.Lock()

    @property
    def web_push_enabled(self) -> bool:
        return self.channel == "web_push" and bool(self.vapid_public_key)

    def get_public_config(self) -> dict[str, Any]:
        return {
            "enabled": self.web_push_enabled,
            "public_key": (
                self._get_browser_public_key() if self.web_push_enabled else ""
            ),
        }

    def _get_browser_public_key(self) -> str:
        value = self.vapid_public_key.strip()
        app_server_key_prefix = "Application Server Key ="
        if app_server_key_prefix in value:
            value = value.split(app_server_key_prefix, 1)[1].strip()

        try:
            if "-----BEGIN PUBLIC KEY-----" in value:
                public_key = serialization.load_pem_public_key(
                    value.encode("ascii")
                )
                if public_key.curve.name != "secp256r1":
                    raise ValueError
                raw_key = public_key.public_bytes(
                    serialization.Encoding.X962,
                    serialization.PublicFormat.UncompressedPoint,
                )
            else:
                encoded_key = re.sub(r"\s+", "", value).strip("\"'")
                encoded_key = encoded_key.replace("-", "+").replace("_", "/")
                raw_key = base64.b64decode(
                    encoded_key + "=" * (-len(encoded_key) % 4),
                    validate=True,
                )
            if len(raw_key) != 65 or raw_key[0] != 4:
                raise ValueError
        except Exception as error:
            raise ValueError(
                "vapid_public_key must be an uncompressed P-256 public key, "
                "PEM public key, or Application Server Key value."
            ) from error

        return base64.urlsafe_b64encode(raw_key).decode("ascii").rstrip("=")

    def save_subscription(self, subscription: dict[str, Any]) -> None:
        endpoint = subscription.get("endpoint")
        keys = subscription.get("keys")
        if not isinstance(endpoint, str) or not endpoint:
            raise ValueError("Invalid Web Push subscription endpoint.")
        if (
            not isinstance(keys, dict)
            or not keys.get("p256dh")
            or not keys.get("auth")
        ):
            raise ValueError("Invalid Web Push subscription keys.")

        with self._subscription_lock:
            subscriptions = self._load_subscriptions()
            subscriptions = [
                item
                for item in subscriptions
                if item.get("endpoint") != endpoint
            ]
            subscriptions.append(subscription)
            self.subscription_path.write_text(
                json.dumps(subscriptions, ensure_ascii=False), encoding="utf-8"
            )

    def delete_subscription(self, endpoint: str) -> None:
        with self._subscription_lock:
            subscriptions = self._load_subscriptions()
            subscriptions = [
                item
                for item in subscriptions
                if item.get("endpoint") != endpoint
            ]
            self.subscription_path.write_text(
                json.dumps(subscriptions, ensure_ascii=False), encoding="utf-8"
            )

    def notify(self, title: str, content: str, timeout: int = 30) -> None:
        if self.channel == "web_push":
            self._notify_web_push(title, content)
            return

        from .termux_api import TermuxAPI

        TermuxAPI().notify(title, content, timeout)

    def _notify_web_push(self, title: str, content: str) -> None:
        if not self.web_push_enabled:
            log.warning("Web Push is selected but VAPID public key is missing.")
            return
        if not self.vapid_private_key or not self.vapid_subject:
            log.warning("Web Push VAPID credentials are not configured.")
            return

        with self._subscription_lock:
            subscriptions = self._load_subscriptions()
        if not subscriptions:
            log.warning("Web Push has no registered subscriptions.")
            return

        expired_endpoints: list[str] = []
        payload = json.dumps({"title": title, "body": content})
        private_key: Any = self.vapid_private_key
        if "-----BEGIN" in self.vapid_private_key:
            private_key = Vapid.from_pem(self.vapid_private_key.encode("utf-8"))
        for subscription in subscriptions:
            try:
                response = webpush(
                    subscription_info=subscription,
                    data=payload,
                    vapid_private_key=private_key,
                    vapid_claims={"sub": self.vapid_subject},
                )
                log.info(
                    "Web Push accepted by push service (status=%s).",
                    getattr(response, "status_code", "unknown"),
                )
            except WebPushException as error:
                status_code = getattr(error.response, "status_code", None)
                if status_code in (404, 410):
                    expired_endpoints.append(subscription["endpoint"])
                log.warning(
                    "Failed to send Web Push notification (status=%s, reason=%s).",
                    status_code,
                    getattr(error.response, "reason", "unknown"),
                )
            except Exception:
                log.exception("Failed to send Web Push notification.")

        for endpoint in expired_endpoints:
            self.delete_subscription(endpoint)

    def _load_subscriptions(self) -> list[dict[str, Any]]:
        try:
            data = json.loads(
                self.subscription_path.read_text(encoding="utf-8")
            )
        except (FileNotFoundError, json.JSONDecodeError):
            return []
        if not isinstance(data, list):
            return []
        return [item for item in data if isinstance(item, dict)]
