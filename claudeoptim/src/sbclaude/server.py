from dataclasses import asdict
from pydantic import TypeAdapter
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from anyio import create_task_group
from sbclaude.runner import ClaudeRunner, CmdPrompt, CmdContinue, CmdStop, EvtInterrupt, EvtResult, Config
from sbclaude.schema import (
    CmdPromptModel,
    CmdContinueModel,
    CmdStopModel,
    CommandModel,
    EvtErrorModel,
    EvtInterruptModel,
    EvtResultModel,
)


app = FastAPI(title="Claude Runner API")


@app.get("/")
async def root():
    return {"message": "Claude Runner API", "endpoints": {"/ws": "WebSocket endpoint for Claude interaction"}}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        async with create_task_group() as tg:
            runner: ClaudeRunner | None = None
            while True:
                data = await websocket.receive_json()
                cmd_model = CommandModel.model_validate(data).root

                if isinstance(cmd_model, CmdPromptModel):
                    cmd = CmdPrompt(prompt=cmd_model.prompt)
                    if runner is None:
                        config_adapter: TypeAdapter[Config] = TypeAdapter(Config)
                        config = config_adapter.validate_python(cmd_model.config) if cmd_model.config else Config()
                        runner = ClaudeRunner(config=config)
                        tg.start_soon(runner.run)
                elif isinstance(cmd_model, CmdContinueModel):
                    if runner is None:
                        await websocket.send_json({"error": "No active runner. Send a prompt first."})
                        continue
                    cmd = CmdContinue()
                elif isinstance(cmd_model, CmdStopModel):
                    if runner is None:
                        await websocket.send_json({"error": "No active runner. Send a prompt first."})
                        continue
                    cmd = CmdStop()
                else:
                    raise ValueError(f"Unknown command type: {cmd_model}")

                await runner.send(cmd)
                event = await runner.receive()

                if isinstance(event, EvtInterrupt):
                    event_model = EvtInterruptModel.model_validate({
                        "input_data": event.input_data,
                        "tool_use_id": event.tool_use_id,
                        "messages": [asdict(msg) for msg in event.messages],
                    })
                elif isinstance(event, EvtResult):
                    event_model = EvtResultModel.model_validate({
                        "messages": [asdict(msg) for msg in event.messages],
                    })
                else:
                    continue # Not interested in other event types
                await websocket.send_json(event_model.model_dump())
    except* WebSocketDisconnect as excgroup:
        print("Client disconnected")
    except* Exception as excgroup:
        for exc in excgroup.exceptions:
            print(f"Error in agent loop: {exc}")
            error_model = EvtErrorModel.model_validate({"detail": str(exc)})
            await websocket.send_json(error_model.model_dump())

def main():
    """Entry point for the sbclaude-server CLI command."""
    import uvicorn
    import sys

    # Parse command line arguments
    host = "0.0.0.0"
    port = 8000

    for arg in sys.argv[1:]:
        if arg.startswith("--host="):
            host = arg.split("=")[1]
        elif arg.startswith("--port="):
            port = int(arg.split("=")[1])

    print(f"Starting sbclaude server on {host}:{port}")
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
