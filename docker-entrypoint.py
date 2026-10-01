"""Prepare mounted runtime files, then launch the bot as the app user."""

import os
from pathlib import Path
import pwd
import stat
import sys


def make_writable(path, uid, gid):
    metadata = path.lstat()
    # Do not change targets outside the runtime directory via symlinks.
    if stat.S_ISLNK(metadata.st_mode):
        return
    if (metadata.st_uid, metadata.st_gid) != (uid, gid):
        os.chown(path, uid, gid, follow_symlinks=False)
    required = stat.S_IRUSR | stat.S_IWUSR
    if stat.S_ISDIR(metadata.st_mode):
        required |= stat.S_IXUSR
    mode = stat.S_IMODE(metadata.st_mode)
    if mode & required != required:
        path.chmod(mode | required)


def prepare_runtime_directories(uid, gid, base_dir=Path('/app')):
    directories = (
        Path(os.environ.get('FIREFLY_PARSER_WORKDIR', base_dir / 'workdir')).expanduser(),
        Path(os.environ.get('FIREFLY_PARSER_LOG_DIR', base_dir / 'logs')).expanduser(),
        base_dir / 'downloads',
    )
    for directory in directories:
        if directory.is_symlink():
            raise RuntimeError(f'Runtime directory must not be a symlink: {directory}')
        directory.mkdir(parents=True, exist_ok=True)
        make_writable(directory, uid, gid)

        def walk_error(error):
            raise error

        for root, subdirectories, files in os.walk(directory, onerror=walk_error):
            for name in subdirectories + files:
                make_writable(Path(root) / name, uid, gid)


def main():
    if os.geteuid() == 0:
        account = pwd.getpwnam('app')
        try:
            prepare_runtime_directories(account.pw_uid, account.pw_gid)
        except (OSError, RuntimeError) as error:
            sys.exit(f'Cannot prepare writable bot runtime directories: {error}')
        os.setgroups([])
        os.setgid(account.pw_gid)
        os.setuid(account.pw_uid)
        os.environ['HOME'] = account.pw_dir
    command = sys.argv[1:] or ['python', '-m', 'app']
    os.execvp(command[0], command)


if __name__ == '__main__':
    main()
