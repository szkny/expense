import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from src.expense.core.notification import NotificationManager


class TestNotificationManager(unittest.TestCase):
    def make_manager(self, directory: str) -> NotificationManager:
        manager = NotificationManager.__new__(NotificationManager)
        manager.channel = "web_push"
        manager.vapid_public_key = "public-key"
        manager.vapid_private_key = "private-key"
        manager.vapid_subject = "mailto:test@example.com"
        manager.subscription_path = Path(directory) / "subscriptions.json"
        manager._subscription_lock = threading.Lock()
        return manager

    def test_public_pem_is_converted_to_browser_application_server_key(
        self,
    ) -> None:
        private_key = ec.generate_private_key(ec.SECP256R1())
        pem = private_key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        manager = self.make_manager(".")
        manager.vapid_public_key = pem.decode("ascii")

        result = manager.get_public_config()

        self.assertTrue(result["enabled"])
        self.assertEqual(len(result["public_key"]), 87)
        self.assertNotIn("=", result["public_key"])

    def test_save_subscription_replaces_same_endpoint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = self.make_manager(directory)
            subscription = {
                "endpoint": "https://push.example/1",
                "keys": {"p256dh": "key", "auth": "auth"},
            }

            manager.save_subscription(subscription)
            manager.save_subscription({**subscription, "expirationTime": None})

            saved = json.loads(manager.subscription_path.read_text())
            self.assertEqual(saved, [{**subscription, "expirationTime": None}])

    def test_notify_sends_payload_to_each_subscription(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = self.make_manager(directory)
            manager.save_subscription(
                {
                    "endpoint": "https://push.example/1",
                    "keys": {"p256dh": "key", "auth": "auth"},
                }
            )

            with patch("src.expense.core.notification.webpush") as send:
                manager.notify("タイトル", "本文")

            send.assert_called_once()
            self.assertEqual(
                json.loads(send.call_args.kwargs["data"]),
                {
                    "title": "タイトル",
                    "body": "本文",
                },
            )


if __name__ == "__main__":
    unittest.main()
