"""Small A2A boundary for S13Core.

This package is intentionally independent of the graph runtime.  A graph node
can use :class:`A2AClient` as a remote worker without gaining access to local
memory, policy, or gateway credentials.
"""

from .client import A2AClient, DiscoveredAgent
from .grpc_binding import A2AGrpcClient, A2AGrpcServer
from .server import A2ADemoServer, TaskState
from .trust import AgentCardTrustPolicy, CardTrustError, sign_card

__all__ = [
    "A2AClient",
    "A2ADemoServer",
    "A2AGrpcClient",
    "A2AGrpcServer",
    "AgentCardTrustPolicy",
    "CardTrustError",
    "DiscoveredAgent",
    "TaskState",
    "sign_card",
]
