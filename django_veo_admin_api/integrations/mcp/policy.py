"""Adapter-level MCP tool allow/deny policy."""

from dataclasses import dataclass
from fnmatch import fnmatchcase


@dataclass(frozen=True, slots=True)
class MCPToolPolicy:
    allow: tuple[str, ...] = ("*",)
    deny: tuple[str, ...] = ()

    def allows(self, tool_name: str) -> bool:
        return any(fnmatchcase(tool_name, pattern) for pattern in self.allow) and not any(
            fnmatchcase(tool_name, pattern) for pattern in self.deny
        )
