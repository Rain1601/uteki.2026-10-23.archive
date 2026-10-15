"""Exclusive local catalog ownership, checked migrations and durable commit head."""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
from importlib import resources
import json
import os
from pathlib import Path
import sqlite3
import stat
import tempfile

from ..content.store import ContentStore, _directory, _fsync_directory
from ..contracts.common import CatalogError, CatalogView, canonical, digest, new_id, utc_now

MIGRATIONS = ((1, "0001_catalog.sql"),)


def migration_sources():
    return [(version, resources.files(__package__).joinpath("migrations", name).read_bytes())
            for version, name in MIGRATIONS]


def read_regular(path: Path) -> bytes:
    if not stat.S_ISREG(path.lstat().st_mode):
        raise CatalogError("CATALOG_INCONSISTENT", f"not a regular file: {path.name}")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise CatalogError("CATALOG_INCONSISTENT", "unsafe control file")
        return stream.read()


def ensure_directory(root: Path, relative: str) -> Path:
    current = root
    _directory(current, create=False)
    for part in Path(relative).parts:
        if part in {"..", "/"}:
            raise CatalogError("INVALID_ARGUMENT", "unsafe internal directory")
        current = current / part
        _directory(current, create=True)
    return current


def write_control(path: Path, raw: bytes, *, replace: bool = False) -> None:
    """Atomic complete-file visibility. Replacement is only for the commit head."""
    fd, name = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        if replace:
            if path.is_symlink():
                raise CatalogError("CATALOG_INCONSISTENT", "head must not be a link")
            os.replace(temporary, path)
        else:
            try:
                os.link(temporary, path)
            except FileExistsError:
                if read_regular(path) != raw:
                    raise CatalogError("CATALOG_INCONSISTENT", "immutable control file differs")
        _fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


class Database:
    def __init__(self, data_root, *, initialize=False, recover_head=False):
        self.root = ContentStore(data_root).data_root
        self.connection = None
        self.lock_fd = None
        self.closed = False
        self.head_uncertain = False
        self.owner_pid = os.getpid()
        try:
            self.lock_fd = os.open(self.root / ".catalog.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            if not stat.S_ISREG(os.fstat(self.lock_fd).st_mode):
                raise CatalogError("CATALOG_INCONSISTENT", "lock is not a regular file")
            try:
                fcntl.flock(self.lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise CatalogError("CATALOG_BUSY", "catalog already owned by a live handle") from error
            path = self.root / "catalog.sqlite"
            if initialize:
                self._initialize(path)
            if not path.exists():
                raise CatalogError("NOT_FOUND", "catalog must be explicitly initialized")
            if not stat.S_ISREG(path.lstat().st_mode):
                raise CatalogError("CATALOG_INCONSISTENT", "database is not a regular file")
            for suffix in ("-wal","-shm","-journal"):
                sidecar = path.with_name(path.name+suffix)
                if sidecar.is_symlink() or (sidecar.exists() and not stat.S_ISREG(sidecar.lstat().st_mode)):
                    raise CatalogError("CATALOG_INCONSISTENT", "unsafe SQLite sidecar")
            self.connection = sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, isolation_level=None, timeout=0)
            self.connection.row_factory = sqlite3.Row
            self.connection.execute("PRAGMA foreign_keys=ON")
            self.connection.execute("PRAGMA synchronous=FULL")
            self.connection.execute("PRAGMA journal_mode=WAL")
            self._check_migrations()
            self._check_head(recover=recover_head)
        except BaseException:
            self.close()
            raise

    def _initialize(self, path: Path):
        if path.exists() or path.is_symlink() or (self.root / "catalog-head.json").exists():
            raise CatalogError("INVALID_STATE", "catalog already exists; use open")
        for name in ("assets", "staging"):
            directory = self.root / name
            if directory.exists() or directory.is_symlink():
                if not stat.S_ISDIR(directory.lstat().st_mode) or any(directory.iterdir()):
                    raise CatalogError("CATALOG_INCONSISTENT", "cannot initialize over unsafe or existing catalog artifacts")
        fd, name = tempfile.mkstemp(prefix=".catalog-initializing-", suffix=".sqlite", dir=self.root)
        os.close(fd)
        temporary = Path(name)
        db = sqlite3.connect(temporary, isolation_level=None)
        stamp = utc_now()
        view = CatalogView(catalog_id=new_id("cat"), revision=0, token=new_id("rev"))
        try:
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            for version, raw in migration_sources():
                statement = ""
                for line in raw.decode("utf-8").splitlines(True):
                    statement += line
                    if sqlite3.complete_statement(statement):
                        db.execute(statement)
                        statement = ""
                if statement.strip():
                    raise CatalogError("MIGRATION_MISMATCH", "incomplete migration statement")
                db.execute("INSERT INTO schema_migrations VALUES (?,?,?,?)", (version, digest(raw), stamp, stamp))
            db.execute("INSERT INTO catalog_meta VALUES (1,?,?,?,?,?)", (view.catalog_id, 0, view.token, stamp, stamp))
            db.execute("INSERT INTO catalog_commits VALUES (?,?,NULL,?,?)", (0, view.token, stamp, stamp))
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()
        with temporary.open("rb") as stream:
            os.fsync(stream.fileno())
        os.link(temporary, path)
        _fsync_directory(self.root)
        temporary.unlink()
        write_control(self.root / "catalog-head.json", view.canonical_bytes())

    def _check_migrations(self):
        db = self.connection
        try:
            expected = [(version, digest(raw)) for version, raw in migration_sources()]
            actual = [tuple(row) for row in db.execute("SELECT version,sha256 FROM schema_migrations ORDER BY version")]
            if actual != expected or db.execute("PRAGMA user_version").fetchone()[0] != expected[-1][0]:
                raise CatalogError("MIGRATION_MISMATCH", "unsupported or changed migration history")
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or db.execute("PRAGMA foreign_key_check").fetchall():
                raise CatalogError("CATALOG_INCONSISTENT", "database integrity check failed")
        except sqlite3.DatabaseError as error:
            raise CatalogError("MIGRATION_MISMATCH", "catalog schema cannot be opened") from error

    def view(self) -> CatalogView:
        self.assert_open()
        row = self.connection.execute("SELECT catalog_id,revision,token FROM catalog_meta WHERE singleton=1").fetchone()
        if row is None:
            raise CatalogError("CATALOG_INCONSISTENT", "missing catalog identity")
        return CatalogView(**dict(row))

    def _check_head(self, *, recover=False):
        current = self.view()
        history = self.connection.execute("SELECT revision,token,parent_token FROM catalog_commits ORDER BY revision").fetchall()
        previous = None
        for index, row in enumerate(history):
            if row['revision'] != index or row['parent_token'] != previous:
                raise CatalogError("CATALOG_INCONSISTENT", "broken commit chain")
            previous = row['token']
        if len(history) != current.revision+1 or previous != current.token:
            raise CatalogError("CATALOG_INCONSISTENT", "head differs from database commit chain")
        path = self.root / "catalog-head.json"
        if not path.exists() and current.revision == 0:
            if not recover:
                raise CatalogError("RECOVERY_REQUIRED", "initialization head not acknowledged")
            write_control(path, current.canonical_bytes())
            return
        try:
            raw = read_regular(path)
            head = CatalogView.model_validate_json(raw)
            if head.canonical_bytes() != raw:
                raise ValueError("noncanonical head")
        except (ValueError, OSError) as error:
            raise CatalogError("CATALOG_INCONSISTENT", "invalid or missing catalog head") from error
        if head.catalog_id != current.catalog_id or head.revision > current.revision or history[head.revision]['token'] != head.token:
            raise CatalogError("CATALOG_INCONSISTENT", "database was replaced or rolled back independently")
        if head != current:
            if not recover:
                raise CatalogError("RECOVERY_REQUIRED", "database committed; filesystem head not acknowledged")
            write_control(path, current.canonical_bytes(), replace=True)

    def assert_open(self):
        if self.closed or self.connection is None or os.getpid() != self.owner_pid:
            raise CatalogError("INVALID_STATE", "closed catalog or connection inherited across processes")
        if self.head_uncertain:
            raise CatalogError("RECOVERY_REQUIRED", "reopen with explicit recovery before further operations")

    @contextmanager
    def transaction(self):
        self.assert_open()
        self._check_head()
        db = self.connection
        before = db.total_changes
        db.execute("BEGIN IMMEDIATE")
        committed = False
        try:
            yield db
            if db.total_changes != before:
                old = self.view()
                current = CatalogView(catalog_id=old.catalog_id, revision=old.revision+1, token=new_id("rev"))
                stamp = utc_now()
                db.execute("UPDATE catalog_meta SET revision=?,token=?,updated_at=? WHERE singleton=1", (current.revision,current.token,stamp))
                db.execute("INSERT INTO catalog_commits VALUES (?,?,?,?,?)", (current.revision,current.token,old.token,stamp,stamp))
            else:
                current = None
            db.commit()
            committed = True
            if current:
                try:
                    write_control(self.root / "catalog-head.json", current.canonical_bytes(), replace=True)
                except OSError as error:
                    self.head_uncertain = True
                    raise CatalogError("RECOVERY_REQUIRED", "commit succeeded but head sync failed") from error
        except BaseException:
            if not committed:
                db.rollback()
            raise

    def close(self):
        try:
            if self.connection is not None:
                try:
                    self.connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                finally:
                    self.connection.close()
                    self.connection = None
        finally:
            if self.lock_fd is not None:
                os.close(self.lock_fd)
                self.lock_fd = None
            self.closed = True
