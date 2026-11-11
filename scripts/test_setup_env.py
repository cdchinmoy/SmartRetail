import tempfile
import unittest
from pathlib import Path
from setup_env import configure

class SetupTests(unittest.TestCase):
    def test_generates_distinct_secrets_and_is_repeatable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / '.env.example').write_text('DB_PASSWORD=\nAPP_DB_PASSWORD=\nJWT_SECRET=\nSECURE_COOKIES=false\n')
            self.assertEqual(configure(root), 3)
            before = (root / '.env').read_text()
            values = dict(line.split('=', 1) for line in before.splitlines())
            self.assertEqual(len({values[k] for k in ('DB_PASSWORD','APP_DB_PASSWORD','JWT_SECRET')}), 3)
            self.assertEqual(configure(root), 0)
            self.assertEqual((root / '.env').read_text(), before)

    def test_preserves_database_passwords(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / '.env').write_text("DB_PASSWORD=existing-db\nAPP_DB_PASSWORD=existing-app\nJWT_SECRET=''\n")
            self.assertEqual(configure(root), 1)
            result = (root / '.env').read_text()
            self.assertIn('DB_PASSWORD=existing-db\n', result)
            self.assertIn('APP_DB_PASSWORD=existing-app\n', result)

    def test_duplicate_keys_fail_without_changing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            before = 'DB_PASSWORD=a\nDB_PASSWORD=b\n'
            (root / '.env').write_text(before)
            with self.assertRaises(ValueError):
                configure(root)
            self.assertEqual((root / '.env').read_text(), before)

if __name__ == '__main__':
    unittest.main()
