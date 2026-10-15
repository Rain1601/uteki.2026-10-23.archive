"""Run M0 in a fresh Python worker without inherited provider credentials/settings."""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile

from uteki.agents.sdk_probe.profiles import worker_environment


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--python', type=Path, required=True)
    parser.add_argument('--fixture', type=Path, required=True)
    parser.add_argument('--profiles', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    # Do not resolve a venv interpreter symlink to the base interpreter: its
    # lexical path is how Python discovers the isolated environment.
    interpreter = args.python.absolute()
    with tempfile.TemporaryDirectory(prefix='uteki-m0-worker-') as directory:
        env = worker_environment(path=os.pathsep.join([str(interpreter.parent), '/usr/bin', '/bin']),
                                  config_directory=Path(directory) / 'claude-config')
        result = subprocess.run([str(interpreter), '-I', '-m', 'uteki.agents.sdk_probe.offline',
            '--fixture', str(args.fixture.resolve()), '--profiles', str(args.profiles.resolve()),
            '--output', str(args.output.resolve())], env=env, cwd=directory, timeout=60)
    return result.returncode


if __name__ == '__main__':
    raise SystemExit(main())
