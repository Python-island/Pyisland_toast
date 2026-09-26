"""??????????????"""

import subprocess
import unittest
from unittest.mock import patch

from pyisland_toast.method import network_watcher


class NetworkWatcherTests(unittest.TestCase):
    def test_wifi_query_hides_the_console(self):
        completed = subprocess.CompletedProcess(["netsh"], 0, stdout=b"", stderr=b"")
        with patch("pyisland_toast.method.network_watcher.subprocess.run", return_value=completed) as run:
            self.assertIsNone(network_watcher._get_wifi_ssid())
        kwargs = run.call_args.kwargs
        self.assertEqual(kwargs["creationflags"], subprocess.CREATE_NO_WINDOW)
        self.assertEqual(run.call_args.args[0], ["netsh", "wlan", "show", "interfaces"])


if __name__ == "__main__":
    unittest.main()
