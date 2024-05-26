import asyncio
import json
import os
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Annotated, Any, AsyncIterator, cast

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.staticfiles import StaticFiles
from linebot.v3 import WebhookParser
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    ApiException,
    AsyncApiClient,
    AsyncMessagingApi,
    Configuration,
    ReplyMessageRequest,
)
from linebot.v3.webhooks import (
    Event,
    FollowEvent,
    MessageEvent,
    PostbackEvent,
    Source,
    TextMessageContent,
)

from chat import Chatflow
from logger import get_logger

# ================================================================
# setup logging
# ================================================================

logger = get_logger(__name__)


# ================================================================
# setup line bot sdk
# ================================================================

CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")

assert CHANNEL_SECRET is not None, "LINE_CHANNEL_SECRET is not set"
assert CHANNEL_ACCESS_TOKEN is not None, "LINE_CHANNEL_ACCESS_TOKEN is not set"


# ================================================================
# FastAPI setup
# ================================================================


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[dict[str, Any]]:
    loop = asyncio.get_event_loop()
    loop.set_task_factory(asyncio.eager_task_factory)  # type: ignore

    parser = WebhookParser(CHANNEL_SECRET)
    line_config = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
    line_client = AsyncApiClient(line_config)
    line_api = AsyncMessagingApi(line_client)
    chatflow = Chatflow()

    async with line_client:
        yield {
            "parser": parser,
            "line_api": line_api,
            "chatflow": chatflow,
        }


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")


async def line_parse_events(
    request: Request,
    x_line_signature: Annotated[str, Header()],
) -> list[Event]:
    parser: WebhookParser = app.state.parser

    body = await request.body()
    body = body.decode()

    try:
        events = parser.parse(body, x_line_signature)

    except InvalidSignatureError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, e.message)

    if TYPE_CHECKING:
        events = cast(list[Event], events)

    return events


@app.post("/callback")
async def handle_callback(
    events: Annotated[list[Event], Depends(line_parse_events)],
) -> str:
    chatflow: Chatflow = app.state.chatflow
    for event in events:
        await handle_event(chatflow, event)
    return "OK"


async def handle_event(chatflow: Chatflow, event: Event) -> None:
    match event:
        case Event(
            source=Source(user_id=str(user_id)),
            reply_token=str(token),
        ):
            chat = chatflow[user_id]
        case _:
            return

    match event:
        case MessageEvent(message=TextMessageContent(text=text)):
            chat = chat.transition(text)
            chatflow[user_id] = chat

        case PostbackEvent(postback=postback):
            chat = chat.transition(postback.data)
            chatflow[user_id] = chat

        case FollowEvent():
            pass

        case _:
            return

    line_api: AsyncMessagingApi = app.state.line_api

    req = ReplyMessageRequest(
        replyToken=token,
        messages=chat.get_messages(),
        notificationDisabled=None,
    )
    try:
        await line_api.reply_message(req)

    except ApiException as e:
        if TYPE_CHECKING:
            e.body = cast(str, e.body)
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            json.loads(e.body),
        )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app)
