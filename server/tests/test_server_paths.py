import os
import sys
import tempfile
import unittest
from pathlib import Path


class ServerPathTests(unittest.TestCase):
    def test_runtime_paths_do_not_depend_on_cwd(self):
        original_cwd = os.getcwd()
        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            os.chdir(temp_dir)
            try:
                sys.path.insert(0, str(repo_root))
                from app.paths import STATIC_DIR, TEMPLATES_DIR, UPLOADS_DIR, VERSION_FILE

                self.assertTrue(STATIC_DIR.is_dir())
                self.assertTrue(TEMPLATES_DIR.is_dir())
                self.assertTrue(UPLOADS_DIR.is_dir())
                self.assertTrue(VERSION_FILE.is_file())
            finally:
                try:
                    sys.path.remove(str(repo_root))
                except ValueError:
                    pass
                os.chdir(original_cwd)


if __name__ == "__main__":
    unittest.main()
