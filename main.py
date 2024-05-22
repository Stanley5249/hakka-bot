import asyncio
import json
import os
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Annotated, AsyncIterator, cast

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
)

from chat import ChatFlow
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

parser = WebhookParser(CHANNEL_SECRET)
line_config = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
line_client = AsyncApiClient(line_config)
line_api = AsyncMessagingApi(line_client)

# ================================================================
# FastAPI setup
# ================================================================


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    loop = asyncio.get_event_loop()
    loop.set_task_factory(asyncio.eager_task_factory)  # type: ignore
    try:
        yield
    finally:
        await line_client.close()


app = FastAPI(lifespan=lifespan)
chat_flow = ChatFlow()


async def line_parse_events(
    request: Request,
    x_line_signature: Annotated[str, Header()],
) -> list[Event]:
    body = await request.body()
    body = body.decode()

    try:
        events = parser.parse(body, x_line_signature)
    except InvalidSignatureError as e:
        logger.exception(e.message)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, e.message)

    if TYPE_CHECKING:
        events = cast(list[Event], events)

    return events


async def line_reply_message(
    reply_token: str, messages: list[Message]
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
    events: list[Event] = Depends(line_parse_events),
) -> str:
    for event in events:
        match event:
            case Event(
                source=Source(user_id=str(user_id)),
                reply_token=str(reply_token),
            ):
                user_chat = chat_flow[user_id]

            case _:
                continue

        match event:
            case MessageEvent(message=TextMessageContent(text=text)):
                user_chat = user_chat.transition(text)
                chat_flow[user_id] = user_chat

            case FollowEvent():
                pass

            case _:
                continue

        await line_reply_message(
            reply_token,
            user_chat.get_messages(),
        )

    return "OK"
