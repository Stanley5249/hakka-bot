from __future__ import annotations

from abc import abstractmethod
from collections import defaultdict
from dataclasses import dataclass
from os import PathLike
from pathlib import Path
from typing import Any, Protocol, TypeGuard

import yaml
from linebot.v3.messaging import FlexContainer, FlexMessage, Message, TextMessage

__all__ = ["ChatFlow"]

PATH_CHATFLOW = "resource/chatflow.yaml"


def load_chatflow(
    path: str | PathLike[str] = PATH_CHATFLOW,
) -> dict[str, list[Message]]:
    with Path(path).open(encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    assert is_lists_by_str(raw), "invalid chatflow"
    return {key: [match_message(x) for x in val] for key, val in raw.items()}


def is_lists_by_str(x: Any) -> TypeGuard[dict[str, list[Any]]]:
    return isinstance(x, dict) and all(
        isinstance(k, str) and isinstance(v, list) for k, v in x.items()
    )


def match_message(data: Any) -> Message:
    match data:
        case {"type": "text", "data": str(text)}:
            return TextMessage(
                quickReply=None,
                text=text,
                quoteToken=None,
            )
        case {"type": "flex", "data": str(js)}:
            return FlexMessage(
                quickReply=None,
                altText="",
                contents=FlexContainer.from_json(js),
            )
    raise ValueError(f"invalid message type, {data}")


class ChatLike(Protocol):
    history: list[str]

    def __init__(self, history: list[str]) -> None: ...

    @abstractmethod
    def get_messages(self) -> list[Message]: ...

    @abstractmethod
    def transition(self, text: str) -> ChatLike: ...


@dataclass
class Chat(ChatLike):
    history: list[str]


class MessagesMixin(Chat):
    data = load_chatflow()
    messages: list[Message]

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        prefix = "Chat"
        if not cls.__name__.startswith(prefix):
            raise ValueError(f"subclass name must start with {prefix}")
        key = cls.__name__[len(prefix) :]
        if key not in cls.data:
            raise ValueError(f"key {key} not found in chat data")
        cls.messages = cls.data[key]

    def get_messages(self) -> list[Message]:
        return self.messages


class NextMixin(Chat):
    dest: str

    def __init_subclass__(cls, dest: str, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        cls.dest = dest

    def transition(self, text: str) -> ChatLike:
        self.history.append(text)
        return globals()["Chat" + self.dest](self.history)


class ChatBegin(NextMixin, MessagesMixin, dest="Q1Intro"):
    pass


class ChatQ1Intro(NextMixin, MessagesMixin, dest="Q1S1"):
    pass


class ChatQ1S1(NextMixin, MessagesMixin, dest="Q1S2"):
    pass


class ChatQ1S2(NextMixin, MessagesMixin, dest="Begin"):
    pass


class ChatInit(Chat):
    def get_messages(self) -> list[Message]:
        return []

    def transition(self, text: str) -> ChatLike:
        return ChatBegin(self.history)


class ChatFlow(defaultdict[str, ChatLike]):
    def __missing__(self, key: str) -> ChatLike:
        return ChatInit([])
