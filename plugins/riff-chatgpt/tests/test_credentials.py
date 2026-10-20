"""Headless hosts must retain functional, explicitly session-only settings."""
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
from runtime import secret_service_session_available

class CredentialSessionTests(unittest.TestCase):
    def test_installed_command_without_session_is_unavailable(self):
        with patch.dict(os.environ, {}, clear=True), patch("runtime.shutil.which", return_value="/usr/bin/secret-tool"):
            self.assertFalse(secret_service_session_available())

    def test_explicit_session_bus_is_available(self):
        with patch.dict(os.environ, {"DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/test/bus"}, clear=True), patch("runtime.shutil.which", return_value="/usr/bin/secret-tool"):
            self.assertTrue(secret_service_session_available())

    def test_missing_command_is_unavailable_even_with_bus(self):
        with patch.dict(os.environ, {"DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/test/bus"}, clear=True), patch("runtime.shutil.which", return_value=None):
            self.assertFalse(secret_service_session_available())

    def test_default_runtime_bus_socket_is_available(self):
        with patch.dict(os.environ, {"XDG_RUNTIME_DIR": "/run/user/test"}, clear=True), patch("runtime.shutil.which", return_value="/usr/bin/secret-tool"), patch("runtime.Path.is_socket", return_value=True):
            self.assertTrue(secret_service_session_available())
