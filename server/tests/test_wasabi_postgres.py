import unittest
from unittest.mock import patch

from app import wasabi_postgres


class WasabiPostgresTest(unittest.TestCase):
    def test_uses_sudo_docker_for_standalone_postgres_when_needed(self):
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            return type("Result", (), {"returncode": 1 if cmd[0] == "docker" else 0})()

        with patch("app.wasabi_postgres.shutil.which", return_value="/usr/bin/docker"):
            with patch("app.wasabi_postgres.subprocess.run", side_effect=fake_run):
                self.assertEqual(
                    wasabi_postgres._docker_cmd(),
                    ["sudo", "-n", "docker"],
                )

        self.assertEqual(calls[0][:3], ["docker", "inspect", "cal_postgres"])
        self.assertEqual(calls[1][:4], ["sudo", "-n", "docker", "inspect"])

    def test_direct_postgres_for_non_container_host(self):
        with patch("app.wasabi_postgres._docker_cmd", return_value=["docker"]):
            self.assertFalse(
                wasabi_postgres._uses_standalone_postgres({"host": "db.example.com"})
            )


if __name__ == "__main__":
    unittest.main()
