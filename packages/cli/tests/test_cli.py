import contextlib
import io
import stat
import tempfile
import unittest
from pathlib import Path

from localpay_cli.cli import Client, CliError, init_env, parser


class CliTests(unittest.TestCase):
    def test_init_creates_private_environment_and_preserves_existing_file(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            path = Path(directory) / ".env"
            init_env(path)
            first = path.read_text()
            self.assertIn("LOCALPAY_ADMIN_TOKEN=", first)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            init_env(path)
            self.assertEqual(path.read_text(), first)

    def test_invalid_commands_and_identifiers_are_rejected(self) -> None:
        for command in (["unknown"], ["--project", "bad", "health"], ["test", "run"]):
            with (
                contextlib.redirect_stderr(io.StringIO()),
                self.assertRaises(SystemExit) as exc,
            ):
                parser().parse_args(command)
            self.assertEqual(exc.exception.code, 2)

    def test_non_origin_api_urls_are_rejected(self) -> None:
        for origin in (
            "file:///etc/passwd",
            "https://a:b@localhost",
            "http://localhost/path",
            "https://api.razorpay.com",
        ):
            with self.assertRaises(CliError):
                Client(origin, None)
