import importlib.util
import os
from pathlib import Path
import sqlite3
import stat
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch


ENTRYPOINT_PATH = Path(__file__).resolve().parent.parent / 'docker-entrypoint.py'
spec = importlib.util.spec_from_file_location('docker_entrypoint', ENTRYPOINT_PATH)
entrypoint = importlib.util.module_from_spec(spec)
spec.loader.exec_module(entrypoint)


class DockerEntrypointTests(unittest.TestCase):
    def setUp(self):
        self.runtime = TemporaryDirectory()
        self.addCleanup(self.runtime.cleanup)
        self.root = Path(self.runtime.name)

    def prepare(self):
        with patch.dict(os.environ, {}, clear=True):
            entrypoint.prepare_runtime_directories(os.getuid(), os.getgid(), self.root)

    def test_existing_readonly_session_and_logs_become_writable(self):
        workdir = self.root / 'workdir'
        workdir.mkdir()
        session = workdir / 'bot.session'
        with sqlite3.connect(session) as database:
            database.execute('CREATE TABLE version (number INTEGER)')
            database.execute('INSERT INTO version VALUES (1)')
        session.chmod(0o444)
        journal = workdir / 'bot.session-wal'
        journal.write_bytes(b'existing journal')
        journal.chmod(0o444)
        logdir = self.root / 'logs'
        logdir.mkdir()
        logfile = logdir / 'app.log'
        logfile.write_text('existing log\n')
        logfile.chmod(0o444)
        workdir.chmod(0o555)
        logdir.chmod(0o555)

        self.prepare()

        self.assertEqual(journal.read_bytes(), b'existing journal')
        self.assertTrue(journal.stat().st_mode & stat.S_IWUSR)
        with sqlite3.connect(session) as database:
            self.assertEqual(database.execute('SELECT number FROM version').fetchone(), (1,))
            database.execute('UPDATE version SET number = 2')
        with logfile.open('a') as log:
            log.write('new log\n')
        self.assertEqual(logfile.read_text(), 'existing log\nnew log\n')
        self.assertTrue((self.root / 'downloads').is_dir())

    def test_foreign_owned_file_is_assigned_to_app_user(self):
        file = self.root / 'session'
        file.write_bytes(b'existing session')
        with patch.object(entrypoint.os, 'chown') as chown:
            entrypoint.make_writable(file, os.getuid() + 1, os.getgid() + 1)
        chown.assert_called_once_with(file, os.getuid() + 1, os.getgid() + 1, follow_symlinks=False)
        self.assertEqual(file.read_bytes(), b'existing session')

    def test_runtime_path_overrides_and_symlinks_preserve_unrelated_files(self):
        outside = self.root / 'config.ini'
        outside.write_text('unchanged')
        outside.chmod(0o444)
        workdir = self.root / 'custom-workdir'
        workdir.mkdir()
        (workdir / 'external-file').symlink_to(outside)
        with patch.dict(os.environ, {
            'FIREFLY_PARSER_WORKDIR': str(workdir),
            'FIREFLY_PARSER_LOG_DIR': str(self.root / 'custom-logs'),
        }, clear=True):
            entrypoint.prepare_runtime_directories(os.getuid(), os.getgid(), self.root)
        self.assertEqual(stat.S_IMODE(outside.stat().st_mode), 0o444)
        self.assertTrue((self.root / 'custom-logs').is_dir())
        self.assertFalse((self.root / 'workdir').exists())

    def test_root_startup_drops_privileges_before_exec(self):
        account = SimpleNamespace(pw_uid=1000, pw_gid=1000, pw_dir='/home/app')
        operations = []
        with patch.object(entrypoint.os, 'geteuid', return_value=0), patch.object(
            entrypoint.pwd, 'getpwnam', return_value=account
        ), patch.object(entrypoint, 'prepare_runtime_directories', side_effect=lambda *args: operations.append(('prepare', args))), patch.object(
            entrypoint.os, 'setgroups', side_effect=lambda *args: operations.append(('groups', args))
        ), patch.object(entrypoint.os, 'setgid', side_effect=lambda *args: operations.append(('gid', args))), patch.object(
            entrypoint.os, 'setuid', side_effect=lambda *args: operations.append(('uid', args))
        ), patch.object(entrypoint.os, 'execvp', side_effect=lambda *args: operations.append(('exec', args))), patch.object(
            entrypoint.sys, 'argv', ['entrypoint', 'python', '-m', 'app']
        ), patch.dict(os.environ, {}, clear=True):
            entrypoint.main()
            self.assertEqual(os.environ['HOME'], '/home/app')
        self.assertEqual(operations, [
            ('prepare', (1000, 1000)), ('groups', ([],)),
            ('gid', (1000,)), ('uid', (1000,)),
            ('exec', ('python', ['python', '-m', 'app'])),
        ])

    def test_nonroot_startup_executes_command_without_chown(self):
        with patch.object(entrypoint.os, 'geteuid', return_value=1000), patch.object(
            entrypoint, 'prepare_runtime_directories'
        ) as prepare, patch.object(entrypoint.os, 'execvp') as execute, patch.object(
            entrypoint.sys, 'argv', ['entrypoint', 'python', '-c', 'print(1)']
        ):
            entrypoint.main()
        prepare.assert_not_called()
        execute.assert_called_once_with('python', ['python', '-c', 'print(1)'])

    def test_failed_permission_repair_stops_before_starting_bot(self):
        account = SimpleNamespace(pw_uid=1000, pw_gid=1000, pw_dir='/home/app')
        with patch.object(entrypoint.os, 'geteuid', return_value=0), patch.object(
            entrypoint.pwd, 'getpwnam', return_value=account
        ), patch.object(entrypoint, 'prepare_runtime_directories', side_effect=PermissionError('read-only mount')), patch.object(
            entrypoint.os, 'execvp'
        ) as execute:
            with self.assertRaisesRegex(SystemExit, 'Cannot prepare writable bot runtime directories'):
                entrypoint.main()
        execute.assert_not_called()


if __name__ == '__main__':
    unittest.main()
