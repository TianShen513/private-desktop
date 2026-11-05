import sys
import time
import unittest

from private_desktop.process import capture, ProcessError


class BoundedProcessTests(unittest.TestCase):
    def test_output_captured_without_stderr(self):
        data = capture([sys.executable, "-c", "import sys; print('ok'); print('PRIVATE', file=sys.stderr)"])
        self.assertEqual(data, b"ok\n" if sys.platform != "win32" else b"ok\r\n")

    def test_oversized_output_killed(self):
        with self.assertRaises(ProcessError):
            capture([sys.executable, "-c", "print('S'*100000)"], limit=128)

    def test_timeout(self):
        with self.assertRaises(ProcessError):
            capture([sys.executable, "-c", "import time; time.sleep(30)"], timeout=0.1)

    def test_failure_does_not_include_private_output(self):
        with self.assertRaises(ProcessError) as raised:
            capture([sys.executable, "-c", "print('SECRET_VALUE'); raise SystemExit(1)"])
        self.assertNotIn("SECRET_VALUE", str(raised.exception))

    def test_inherited_stdout_cannot_hold_the_capture_open(self):
        child = "import time; time.sleep(8)"
        code = "import subprocess,sys; subprocess.Popen([sys.executable,'-c'," + repr(child) + "])"
        started = time.monotonic()
        with self.assertRaises(ProcessError):
            capture([sys.executable, "-c", code], timeout=1)
        self.assertLess(time.monotonic() - started, 6)


if __name__ == "__main__":
    unittest.main()
