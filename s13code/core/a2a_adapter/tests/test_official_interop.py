import grpc
import pytest
from a2a.types import a2a_pb2 as p
from a2a.types import a2a_pb2_grpc as pb_grpc

from s13code.core.a2a_adapter.official import OfficialA2AServer
from s13code.core.a2a_adapter.server import A2ADemoServer

CARD={"name":"official","description":"interop","version":"1.0.0",
      "supportedInterfaces":[{"url":"grpc://127.0.0.1:0","protocolBinding":"GRPC","protocolVersion":"1.0"}],
      "defaultInputModes":["text/plain"],"defaultOutputModes":["text/plain"],
      "skills":[{"id":"echo","name":"Echo","description":"Echo","tags":["test"]}]}

@pytest.mark.asyncio
async def test_official_generated_stub_interoperates(tmp_path):
    server=OfficialA2AServer(A2ADemoServer(CARD), tmp_path / "push.db")
    channel=grpc.aio.insecure_channel(await server.start()); stub=pb_grpc.A2AServiceStub(channel)
    try:
        req=p.SendMessageRequest(message=p.Message(message_id="m", role=p.ROLE_USER, parts=[p.Part(text="slow report")]))
        task=(await stub.SendMessage(req)).task
        assert task.status.state == p.TASK_STATE_WORKING
        cancelled=await stub.CancelTask(p.CancelTaskRequest(id=task.id))
        assert cancelled.status.state == p.TASK_STATE_CANCELED
        config=await stub.CreateTaskPushNotificationConfig(p.TaskPushNotificationConfig(id="pc1",task_id=task.id,url="https://callback.test"))
        assert (await stub.GetTaskPushNotificationConfig(p.GetTaskPushNotificationConfigRequest(id=config.id))).url == "https://callback.test"
    finally:
        await channel.close(); await server.stop()
