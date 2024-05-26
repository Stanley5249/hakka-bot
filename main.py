import asyncio
import json
import os
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Annotated, AsyncIterator, Sequence, cast

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from linebot.v3 import WebhookParser
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    ApiException,
    AsyncApiClient,
    AsyncMessagingApi,
    Configuration,
    Message,
    ReplyMessageRequest,
    ReplyMessageResponse,
)
from linebot.v3.webhooks import (
    Event,
    FollowEvent,
    MessageEvent,
    Source,
    TextMessageContent,
    PostbackEvent,
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

parser = WebhookParser(CHANNEL_SECRET)

# ================================================================
# FastAPI setup
# ================================================================


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    loop = asyncio.get_event_loop()
    loop.set_task_factory(asyncio.eager_task_factory)  # type: ignore

    line_config = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
    line_client = AsyncApiClient(line_config)
    line_api = AsyncMessagingApi(line_client)

    app.state.line_api = line_api

    async with line_client:
        yield


app = FastAPI(lifespan=lifespan)
chatflow = Chatflow()


async def line_parse_events(
    request: Request,
    x_line_signature: Annotated[str, Header()],
) -> list[Event]:
    body = await request.body()
    body = body.decode()

    try:
        events = parser.parse(body, x_line_signature)

    except InvalidSignatureError as e:
        logger.exception(e)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, e.message)

    if TYPE_CHECKING:
        events = cast(list[Event], events)

    return events


async def line_reply_message(
    line_api: AsyncMessagingApi,
    reply_token: str,
    messages: Sequence[Message],
) -> ReplyMessageResponse:
    req = ReplyMessageRequest(
        replyToken=reply_token,
        messages=messages,
        notificationDisabled=None,
    )
    try:
        return await line_api.reply_message(req)

    except ApiException as e:
        logger.exception(e)

        if TYPE_CHECKING:
            e.body = cast(str, e.body)

        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            json.loads(e.body),
        )


@app.post("/callback")
async def handle_callback(
    events: Annotated[list[Event], Depends(line_parse_events)],
) -> str:
    for event in events:
        await handle_event(event)
    return "OK"


async def handle_event(event: Event) -> None:
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

    await line_reply_message(
        app.state.line_api,
        token,
        chat.get_messages(),
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app)
