import asyncio
import json
import os
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Annotated, Any, AsyncIterator, cast

from fastapi import FastAPI, Header, HTTPException, Request, status
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
        yield dict(
            parser=parser,
            line_api=line_api,
            chatflow=chatflow,
        )


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.post("/callback")
async def handle_callback(
    request: Request,
    x_line_signature: Annotated[str, Header()],
) -> str:
    state = request.state
    parser: WebhookParser = state.parser
    line_api: AsyncMessagingApi = state.line_api
    chatflow: Chatflow = state.chatflow

    url = str(request.base_url.replace(scheme="https"))

    logger.info(f"request url: {url}")

    body = await request.body()
    body = body.decode()

    events = await line_parse_events(x_line_signature, body, parser)

    for event in events:
        await handle_event(event, line_api, chatflow, url)

    return "OK"


async def line_parse_events(
    x_line_signature: str,
    body: str,
    parser: WebhookParser,
) -> list[Event]:
    try:
        events = parser.parse(body, x_line_signature)

    except InvalidSignatureError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, e.message)

    if TYPE_CHECKING:
        events = cast(list[Event], events)

    return events


async def handle_event(
    event: Event,
    line_api: AsyncMessagingApi,
    chatflow: Chatflow,
    url: str,
) -> None:
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

    req = ReplyMessageRequest(
        replyToken=token,
        messages=chat.get_messages(url=url),
        notificationDisabled=None,
    )
    try:
        res = await line_api.reply_message(req)

    except ApiException as e:
        data = json.loads(e.body)  # type: ignore
        logger.error(data)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, data)

    else:
        logger.debug(res)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app)
