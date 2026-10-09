from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class AppImageEntry:
    name: str
    path: str
    executable: bool
    size: int = 0
    mtime: float = 0.0

    display_name: str = ""
    comment: str = ""
    categories: str = ""
    icon: str = ""
    version: str = ""
    desktop_integrated: bool = False

    def effective_display_name(self) -> str:
        return self.display_name or self.name

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "path": self.path,
            "executable": self.executable,
            "size": self.size,
            "mtime": self.mtime,
            "display_name": self.display_name,
            "comment": self.comment,
            "categories": self.categories,
            "icon": self.icon,
            "version": self.version,
            "desktop_integrated": self.desktop_integrated,
        }

    @classmethod
    def from_dict(cls, data: dict) -> AppImageEntry:
        return cls(
            name=data.get("name", ""),
            path=data.get("path", ""),
            executable=bool(data.get("executable", False)),
            size=int(data.get("size", 0)),
            mtime=float(data.get("mtime", 0.0)),
            display_name=str(data.get("display_name", "")),
            comment=str(data.get("comment", "")),
            categories=str(data.get("categories", "")),
            icon=str(data.get("icon", "")),
            version=str(data.get("version", "")),
            desktop_integrated=bool(data.get("desktop_integrated", False)),
        )
