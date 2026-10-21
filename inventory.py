"""Read Cloud Files attributes without opening file contents or following links."""

import os
from dataclasses import dataclass, field
from pathlib import Path

PINNED = 0x80000
RECALL = 0x400000


@dataclass
class Scan:
    selected: dict = field(default_factory=dict)
    seen: set = field(default_factory=set)
    unavailable: set = field(default_factory=set)

    def uncertain(self, rel):
        return any(
            not prefix or rel == prefix or rel.startswith(prefix + "/")
            for prefix in self.unavailable
        )


def scan(root):
    root = Path(root)
    result = Scan()
    stack = [root]
    while stack:
        folder = stack.pop()
        try:
            with os.scandir(folder) as entries:
                for entry in entries:
                    rel = Path(entry.path).relative_to(root).as_posix()
                    try:
                        if entry.is_symlink() or entry.is_junction():
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            if entry.name != ".sync":
                                stack.append(Path(entry.path))
                            continue
                        stat = entry.stat(follow_symlinks=False)
                        result.seen.add(rel)
                        if stat.st_file_attributes & PINNED:
                            result.selected[rel] = {
                                "path": rel,
                                "name": entry.name,
                                "size": stat.st_size,
                                "cloud_pending": bool(stat.st_file_attributes & RECALL),
                            }
                    except OSError:
                        result.unavailable.add(rel)
        except OSError:
            result.unavailable.add(folder.relative_to(root).as_posix() if folder != root else "")
    return result
