import tempfile
import unittest
from pathlib import Path

from comment_crawler.cli import _task_lock


class TaskLockTests(unittest.TestCase):
    def test_same_output_rejects_concurrent_writer(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "run"
            with _task_lock(output):
                with self.assertRaisesRegex(ValueError, "正在被另一进程使用"):
                    with _task_lock(output):
                        pass
            with _task_lock(output):
                pass
