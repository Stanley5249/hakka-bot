from __future__ import annotations

import string
from abc import abstractmethod
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from functools import partial
from os import PathLike
from pathlib import Path
from typing import Any, Protocol, TypedDict, TypeGuard
from urllib.parse import parse_qs, quote, urljoin

import yaml
from linebot.v3.messaging import (
    FlexContainer,
    FlexMessage,
    ImageMessage,
    Message,
    TextMessage,
)

__all__ = ["Chatflow"]


UNKNOWN_ERROR = "很抱歉，我有點不太懂。"
QUESTION_MISMATCH = "你似乎看錯題目了。"
WRONG_ANSWER = "再試試看吧！"
DUPLICATE_ANSWER = "你已經選過了喔。"


class RawChat(TypedDict):
    messages: list[RawMessage]
    action: RawAction


class RawMessage(TypedDict):
    type: str
    data: Any


class RawAction(TypedDict):
    type: str
    data: Any


class RawResult(TypedDict):
    original: str
    preview: str
    text: str


class ChatMaker(Protocol):
    def __call__(self, *, state: Counter[str]) -> ChatLike: ...


class MessageMaker(Protocol):
    def __call__(self, **kwargs: Any) -> Message: ...


class ChatLike(Protocol):
    @abstractmethod
    def get_messages(self, **kwargs: Any) -> list[Message]: ...

    @abstractmethod
    def transition(self, text: str) -> ChatLike: ...


@dataclass
class ChatDefault(ChatLike):
    dest: str
    messages: list[MessageMaker]
    state: Counter[str] = field(kw_only=True)

    def get_messages(self, **kwargs: Any) -> list[Message]:
        return [m(**kwargs) for m in self.messages]

    def transition(self, text: str) -> ChatLike:
        return CHATFLOW_MAKERS[self.dest](state=self.state)


@dataclass
class ChatQA(ChatDefault):
    label: str
    answer: str
    attempt: set[str] = field(default_factory=set)

    def transition(self, text: str) -> ChatLike:
        qa = parse_qs(text)

        match qa:
            case {"q": [q], "a": [a]}:
                pass
            case _:
                self.messages = [partial(make_text_message, UNKNOWN_ERROR)]
                return self

        if q != self.label:
            self.messages = [partial(make_text_message, QUESTION_MISMATCH)]
            return self

        if a in self.attempt:
            self.messages = [partial(make_text_message, DUPLICATE_ANSWER)]
            return self

        if a != self.answer:
            self.attempt.add(a)
            self.messages = [partial(make_text_message, WRONG_ANSWER)]
            return self

        return super().transition(text)


@dataclass
class ChatStore(ChatDefault):
    label: str

    def transition(self, text: str) -> ChatLike:
        qa = parse_qs(text)

        match qa:
            case {"q": [q], "a": [a]}:
                pass
            case _:
                self.messages = [partial(make_text_message, UNKNOWN_ERROR)]
                return self

        if q != self.label:
            self.messages = [partial(make_text_message, QUESTION_MISMATCH)]
            return self

        self.state[a] += 1
        return super().transition(text)


@dataclass
class ChatEnd(ChatDefault):
    data: list[RawResult]

    def get_messages(self, **kwargs: Any) -> list[Message]:
        ((k, v),) = self.state.most_common(1)
        i = ord(k) - ord("A")
        if i < len(self.data):
            x = self.data[i]
            return [
                make_image_message(x["original"], x["preview"], **kwargs),
                make_text_message(x["text"], **kwargs),
            ]
        return [make_text_message(UNKNOWN_ERROR, **kwargs)]

    def transition(self, text: str) -> ChatLike:
        return CHATFLOW_MAKERS[self.dest](state=Counter())


@dataclass
class ChatInit(ChatLike):
    def get_messages(self, **kwargs: Any) -> list[Message]:
        return []

    def transition(self, text: str) -> ChatLike:
        return CHATFLOW_MAKERS["Begin"](state=Counter())


class Chatflow(defaultdict[str, ChatLike]):
    def __missing__(self, key: str) -> ChatLike:
        return ChatInit()


def load_chatflow(path: str | PathLike[str]) -> dict[str, ChatMaker]:
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    assert validate_chatflow(raw)
    return parse_chatflow(raw)


def validate_chatflow(raw: Any) -> TypeGuard[dict[str, RawChat]]:
    if not isinstance(raw, dict):
        raise ValueError("input object must be a dict")

    for k, v in raw.items():
        if not isinstance(k, str):
            raise ValueError(f"key {k} must be a str")

        match v:
            case {"messages": [*messages], "action": action}:
                pass
            case _:
                raise ValueError(f"{v} at {k} must have 'messages' and 'action' keys")

        for m in messages:
            match m:
                case {"type": str()}:
                    pass
                case _:
                    raise ValueError(f"invalid message {m} at {k}")

        match action:
            case {"type": str()}:
                pass
            case _:
                raise ValueError(f"invalid action {action} at {k}")
    return True


def parse_chatflow(raw: dict[str, RawChat]) -> dict[str, ChatMaker]:
    return {key: parse_chat(val) for key, val in raw.items()}


def parse_chat(raw: RawChat) -> ChatMaker:
    messages = [parse_message(m) for m in raw["messages"]]

    match raw["action"]:
        case {"type": "default", "data": {"dest": str(dest)}}:
            return partial(ChatDefault, dest, messages)
        case {
            "type": "qa",
            "data": {"dest": str(dest), "label": str(label), "answer": str(ans)},
        }:
            return partial(ChatQA, dest, messages, label, ans)
        case {"type": "store", "data": {"dest": str(dest), "label": str(label)}}:
            return partial(ChatStore, dest, messages, label)
        case {
            "type": "end",
            "data": {"dest": str(dest), "results": [*results]},
        } if all(validate_result(r) for r in results):
            return partial(ChatEnd, dest, messages, results)
    raise ValueError(f"invalid action type, {raw['action']}")


def parse_message(raw: RawMessage) -> MessageMaker:
    match raw:
        case {"type": "text", "data": str(data)}:
            return partial(make_text_message, data)
        case {
            "type": "image",
            "data": {
                "original": str(original),
                "preview": str(preview),
            },
        }:
            return partial(make_image_message, original, preview)
        case {"type": "flex", "data": {**data}}:
            return partial(make_flex_message, data)
        case {
            "type": "template",
            "data": {
                "id": int(id),
                "label": str(label),
                "title": str(title),
                "options": [*options],
                "fg": str(fg),
                "bg": str(bg),
            },
        } if all(isinstance(opt, str) for opt in options):
            if id == 1:
                data = make_contents_from_template_1(label, title, options, fg, bg)
            elif id == 2:
                data = make_contents_from_template_2(label, title, options, fg, bg)
            else:
                raise ValueError(f"invalid template id, {id}")
            return partial(make_flex_message, data)
    raise ValueError(f"invalid message type, {raw}")


def validate_result(raw: Any) -> TypeGuard[RawResult]:
    match raw:
        case {"original": str(), "preview": str(), "text": str()}:
            return True
    return False


def make_text_message(text: str, **kwargs: Any) -> TextMessage:
    return TextMessage(
        quickReply=None,
        text=text,
        quoteToken=None,
    )


def make_image_message(
    original: str,
    preview: str,
    url: str,
    **kwargs: Any,
) -> ImageMessage:
    return ImageMessage(
        quickReply=None,
        originalContentUrl=urljoin(url, quote(original)),
        previewImageUrl=urljoin(url, quote(preview)),
    )


def make_flex_message(contents: dict[str, Any], **kwargs: Any) -> FlexMessage:
    return FlexMessage(
        quickReply=None,
        altText="flex",
        contents=FlexContainer.from_dict(contents),
    )


def make_contents_from_template_1(
    label: str,
    title: str,
    options: Sequence[str],
    fg: str,
    bg: str,
) -> dict[str, Any]:
    return {
        "body": {
            "contents": [{"text": title, "type": "text", "wrap": True}],
            "layout": "vertical",
            "type": "box",
        },
        "footer": {
            "contents": [
                {"color": fg, "type": "separator"},
                *(
                    {
                        "action": {
                            "data": f"q={label}&a={a}",
                            "displayText": f"我選{q}！",
                            "label": q,
                            "type": "postback",
                        },
                        "color": fg,
                        "type": "button",
                    }
                    for q, a in zip(options, string.ascii_uppercase)
                ),
                {"color": fg, "type": "separator"},
            ],
            "layout": "vertical",
            "spacing": "sm",
            "type": "box",
        },
        "styles": {"body": {"backgroundColor": bg}, "footer": {"backgroundColor": bg}},
        "type": "bubble",
    }


def make_contents_from_template_2(
    label: str,
    title: str,
    options: Sequence[str],
    fg: str,
    bg: str,
) -> dict[str, Any]:
    return {
        "type": "carousel",
        "contents": [
            {
                "type": "bubble",
                "size": "nano",
                "body": {
                    "type": "box",
                    "layout": "vertical",
                    "contents": [
                        {"type": "text", "text": title, "wrap": True, "size": "sm"}
                    ],
                },
                "styles": {"body": {"backgroundColor": bg}},
            },
            *(
                {
                    "type": "bubble",
                    "size": "nano",
                    "body": {
                        "type": "box",
                        "layout": "vertical",
                        "contents": [{"type": "text", "text": opt, "wrap": True}],
                    },
                    "footer": {
                        "type": "box",
                        "layout": "vertical",
                        "contents": [
                            {"type": "separator", "color": fg},
                            {
                                "type": "button",
                                "action": {
                                    "type": "postback",
                                    "label": a,
                                    "data": f"q={label}&a={a}",
                                    "displayText": f"我選{a}！",
                                },
                                "color": fg,
                            },
                        ],
                    },
                    "styles": {
                        "body": {"backgroundColor": bg},
                        "footer": {"backgroundColor": bg},
                    },
                }
                for opt, a in zip(options, string.ascii_uppercase)
            ),
        ],
    }


CHATFLOW_MAKERS = load_chatflow(Path("resource/chatflow.yaml"))
