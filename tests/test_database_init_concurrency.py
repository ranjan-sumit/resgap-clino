"""
init_db() runs on the first use of a database file, and the pipeline calls the
cache helpers from worker threads -- so on a fresh database several threads
reach init_db() at once. They used to race to apply the same migration and the
loser died with "UNIQUE constraint failed: schema_migrations.version".
"""
import sys
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import utils.database as db
from tests.pg_test_utils import new_test_schema, drop_test_schema


class InitDbConcurrencyTests(unittest.TestCase):
    def setUp(self):
        self.path = new_test_schema()
        self.patcher = patch.object(db, "_SCHEMA", self.path)
        self.patcher.start()
        db._INITIALIZED.discard(self.path)

    def tearDown(self):
        self.patcher.stop()
        db._INITIALIZED.discard(self.path)
        drop_test_schema(self.path)

    def test_many_threads_initialising_a_fresh_database_do_not_collide(self):
        n = 16
        barrier = threading.Barrier(n)

        def worker(_):
            barrier.wait()          # release every thread into init_db() together
            db.init_db()

        with ThreadPoolExecutor(max_workers=n) as pool:
            list(pool.map(worker, range(n)))   # re-raises any worker exception

        conn = db._get_conn()
        versions = [r["version"] for r in conn.execute("SELECT version FROM schema_migrations")]
        conn.close()
        self.assertEqual(sorted(versions), sorted(set(versions)), "a migration was recorded twice")
        self.assertGreaterEqual(len(versions), 4)

    def test_init_db_is_idempotent_across_repeated_calls(self):
        db.init_db()
        db._INITIALIZED.discard(self.path)
        db.init_db()   # already-applied migrations must be skipped, not re-run or re-recorded
        conn = db._get_conn()
        count = conn.execute("SELECT COUNT(*) AS c FROM schema_migrations WHERE version LIKE '%.sql'").fetchone()["c"]
        conn.close()
        self.assertEqual(count, len(list(db.MIGRATIONS_DIR.glob("*.sql"))))


if __name__ == "__main__":
    unittest.main()
