"""S13's local, scoped memory service.

This package deliberately has no dependency on the graph runner or gateway.
Those layers call this service; they do not get to bypass its scope and audit
rules.
"""

from .models import MemoryKind, MemoryRecord, MemoryScope, Principal, SourceRef
from .store import MemoryStore, PermissionDenied

__all__ = [
    "MemoryKind",
    "MemoryRecord",
    "MemoryScope",
    "MemoryStore",
    "PermissionDenied",
    "Principal",
    "SourceRef",
]
