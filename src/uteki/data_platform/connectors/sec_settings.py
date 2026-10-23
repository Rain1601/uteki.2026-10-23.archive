"""Resolve the SEC contact only; never execute dotenv content or export values."""
from __future__ import annotations

import os
from pathlib import Path
import re
import stat

KEY = 'UTEKI_SEC_USER_AGENT'
_ASSIGNMENT = re.compile(r'^\s*(?:export\s+)?' + KEY + r'\s*=\s*(.*)$')
_MENTION = re.compile(r'^\s*(?:export\s+)?' + KEY + r'\b')


def _contact(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('SEC contact must be a nonempty string')
    if any(ord(char) < 32 or ord(char) == 127 or char in '\u2028\u2029' for char in value):
        raise ValueError('SEC contact must be one line without control characters')
    return value.strip()


def _value(text):
    """Single-line quoted/unquoted literals; no substitutions or escape decoding."""
    if '\r' in text or '\n' in text:
        raise ValueError('SEC contact must not contain dotenv newlines')
    text = text.strip()
    if text.startswith(('"', "'")):
        quote = text[0]
        close = text.find(quote, 1)
        if close < 0:
            raise ValueError('SEC contact must not span multiple dotenv lines')
        tail = text[close + 1:].strip()
        if tail and not tail.startswith('#'):
            raise ValueError('Invalid quoted SEC contact assignment')
        text = text[1:close]
    else:
        text = re.split(r'\s+#', text, maxsplit=1)[0]
    return _contact(text)


def _local_contact(settings_root):
    """Use directory FDs so neither the file nor its ancestors follow symlinks."""
    root = Path(settings_root)
    if '..' in root.parts:
        raise ValueError('Invalid SEC settings root')
    path = Path(os.path.abspath(root / '.env'))
    directory = file_fd = None
    try:
        directory = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY)
        for component in path.parts[1:-1]:
            next_fd = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = next_fd
        file_fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        info = os.fstat(file_fd)
        if (not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_uid != os.geteuid()):
            raise ValueError('Local SEC settings must be an owned private regular file (mode 600)')
        stream = os.fdopen(file_fd, 'r', encoding='utf-8-sig', newline='')
        file_fd = None
        found = None
        with stream:
            for line in stream:
                # Remove only the physical line ending; controls inside a value remain invalid.
                line = line[:-2] if line.endswith('\r\n') else line[:-1] if line.endswith('\n') else line
                if not _MENTION.match(line):
                    continue
                if found is not None:
                    raise ValueError('Duplicate SEC contact entry')
                match = _ASSIGNMENT.fullmatch(line)
                if not match:
                    raise ValueError('Invalid SEC contact assignment')
                found = _value(match[1])
        return found
    except FileNotFoundError:
        return None
    except (OSError, UnicodeError) as error:
        raise ValueError('Local SEC settings are unavailable or unsafe') from error
    finally:
        if file_fd is not None:
            os.close(file_fd)
        if directory is not None:
            os.close(directory)


def resolve_sec_contact(*, explicit=None, configured=None, settings_root: Path):
    """Return (contact, origin), or (None, 'unconfigured') when absent.

    Order: explicit CLI, environment, nonblank company configuration, local .env.
    Blank company config means absent. An explicitly selected CLI/environment or
    dotenv assignment must be valid; invalid higher-priority values never fall back.
    Lower-priority files are not opened when a higher-priority value is selected.
    """
    if explicit is not None:
        return _contact(explicit), 'cli'
    if KEY in os.environ:
        return _contact(os.environ[KEY]), 'environment'
    if configured is not None:
        if not isinstance(configured, str):
            raise ValueError('Company SEC contact must be a string')
        if configured.strip() or any(ord(char) < 32 or ord(char) == 127 or char in '\u2028\u2029' for char in configured):
            return _contact(configured), 'company_config'
    local = _local_contact(settings_root)
    return (local, 'local_env_file') if local is not None else (None, 'unconfigured')
