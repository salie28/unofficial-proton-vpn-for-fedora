"""
Recently used servers.

PLAN.md §5: Recents "does not exist on Linux. Must be built with our own store."
This is that store. It feeds both the tray menu (§6) and the window's Recents
nav (§4).

It is deliberately plain: a small JSON file of our own (never Proton's), written
atomically, and tolerant of being corrupt or missing. A broken recents file must
degrade to "no recents", never to a failed launch.
"""

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from .paths import recents_file

#: Bump when the on-disk shape changes incompatibly.
SCHEMA_VERSION = 1

#: How many servers to remember. The tray shows 3 (§6); the window's Recents
#: list can show more, so the file keeps a deeper history than either needs.
#: Beyond a handful it stops being a recents list and becomes a second
#: server list, which the sidebar already is.
MAX_ENTRIES = 8


@dataclass
class RecentServer:
    """One remembered server."""

    server_name: str                      # e.g. "AT#171"
    exit_country: str = ""                # e.g. "AT"
    city: str = ""                        # e.g. "Vienna"
    is_secure_core: bool = False
    last_used: str = ""                   # ISO-8601, UTC
    use_count: int = 0

    @property
    def label(self) -> str:
        """Menu label, e.g. 'Austria - AT#171'. Falls back gracefully."""
        left = self.city or self.exit_country
        return f"{left} - {self.server_name}" if left else self.server_name

    @classmethod
    def from_dict(cls, data: dict) -> Optional["RecentServer"]:
        """Build from stored JSON, or None if the entry is unusable.

        Only a missing or empty `server_name` makes an entry unusable. Every
        other field falls back to its default, so one bad value costs at most
        that value - never the entry, and never the whole file.
        """
        name = data.get("server_name")
        if not isinstance(name, str) or not name:
            return None

        try:
            use_count = int(data.get("use_count") or 0)
        except (TypeError, ValueError):
            use_count = 0

        return cls(
            server_name=name,
            exit_country=str(data.get("exit_country") or ""),
            city=str(data.get("city") or ""),
            is_secure_core=bool(data.get("is_secure_core", False)),
            last_used=str(data.get("last_used") or ""),
            use_count=use_count,
        )


@dataclass
class RecentsStore:
    """A most-recent-first list of servers, persisted as JSON.

    Reads are lazy and cached; writes are atomic (temp file + rename) so a
    crash mid-write cannot leave a truncated file behind.
    """

    path: Path = field(default_factory=recents_file)
    max_entries: int = MAX_ENTRIES
    _servers: Optional[List[RecentServer]] = field(default=None, init=False, repr=False)

    # -- reading ---------------------------------------------------------

    @property
    def servers(self) -> List[RecentServer]:
        """All remembered servers, most recent first."""
        if self._servers is None:
            self._servers = self._read()
        return self._servers

    def reload(self) -> None:
        """Drop the cache so the next read comes from disk.

        The window and the tray hold separate stores over the same file. The
        tray records connections; without this the window's copy keeps serving
        whatever it read at startup, so Recents looked broken in the app while
        working in the tray.
        """
        self._servers = None

    def most_recent(self, limit: int = 3) -> List[RecentServer]:
        """The `limit` most recently used servers."""
        return self.servers[:limit]

    def _read(self) -> List[RecentServer]:
        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return []
        except OSError:
            return []

        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            self._quarantine()
            return []

        if not isinstance(data, dict):
            self._quarantine()
            return []

        entries = data.get("servers")
        if not isinstance(entries, list):
            return []

        servers = []
        for entry in entries:
            if isinstance(entry, dict):
                server = RecentServer.from_dict(entry)
                if server is not None:
                    servers.append(server)
        return servers[: self.max_entries]

    def _quarantine(self) -> None:
        """Move an unreadable file aside rather than silently overwriting it."""
        try:
            self.path.replace(self.path.with_suffix(".json.corrupt"))
        except OSError:
            pass

    # -- writing ---------------------------------------------------------

    def record(
        self,
        server_name: str,
        exit_country: str = "",
        city: str = "",
        is_secure_core: bool = False,
        now: Optional[datetime] = None,
    ) -> Optional[RecentServer]:
        """Remember a connection, moving it to the front. Returns the entry.

        Re-connecting to a known server updates it in place and bumps its count
        rather than adding a duplicate.
        """
        if not server_name:
            return None

        timestamp = (now or datetime.now(timezone.utc)).isoformat()
        servers = list(self.servers)

        existing = next(
            (s for s in servers if s.server_name == server_name), None
        )
        if existing is not None:
            servers.remove(existing)
            existing.last_used = timestamp
            existing.use_count += 1
            # Refresh metadata: the server list may have gained a city name
            # since the last time we saw this server.
            existing.exit_country = exit_country or existing.exit_country
            existing.city = city or existing.city
            existing.is_secure_core = is_secure_core
            entry = existing
        else:
            entry = RecentServer(
                server_name=server_name,
                exit_country=exit_country,
                city=city,
                is_secure_core=is_secure_core,
                last_used=timestamp,
                use_count=1,
            )

        servers.insert(0, entry)
        self._servers = servers[: self.max_entries]
        self.save()
        return entry

    def forget(self, server_name: str) -> bool:
        """Drop one server. Returns whether anything was removed."""
        before = len(self.servers)
        self._servers = [s for s in self.servers if s.server_name != server_name]
        if len(self._servers) != before:
            self.save()
            return True
        return False

    def clear(self) -> None:
        """Forget everything."""
        self._servers = []
        self.save()

    def save(self) -> bool:
        """Write the store atomically. Returns whether it was written.

        Never raises: recents are a convenience, and failing to save them must
        not take down a connection flow.
        """
        payload = {
            "version": SCHEMA_VERSION,
            "servers": [asdict(s) for s in self.servers],
        }

        try:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            # Same directory, so os.replace is an atomic rename.
            handle, temp_path = tempfile.mkstemp(
                dir=self.path.parent, prefix=".recents-", suffix=".tmp"
            )
            try:
                with os.fdopen(handle, "w", encoding="utf-8") as file:
                    json.dump(payload, file, indent=2)
                    file.flush()
                    os.fsync(file.fileno())
                # Which servers someone connects to is private; keep it to them.
                os.chmod(temp_path, 0o600)
                os.replace(temp_path, self.path)
            except BaseException:
                Path(temp_path).unlink(missing_ok=True)
                raise
        except OSError:
            return False
        return True
