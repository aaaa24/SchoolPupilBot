from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional

import requests


@dataclass
class MessengerUser:
    id: int
    first_name: str
    last_name: Optional[str] = None
    username: Optional[str] = None


@dataclass
class MessengerChat:
    id: int
    type: str = 'private'


class BaseMessengerClient(ABC):
    platform: str

    @abstractmethod
    def send_message(self, chat_id: int, text: str, **kwargs):
        pass

    @abstractmethod
    def answer_callback_query(self, callback_query_id: str, **kwargs):
        pass

    @abstractmethod
    def get_me_id(self) -> int:
        pass

    @abstractmethod
    def get_chat(self, chat_id: int):
        pass


class TelegramMessengerClient(BaseMessengerClient):
    platform = 'telegram'

    def __init__(self, telebot_client):
        self._bot = telebot_client

    def send_message(self, chat_id: int, text: str, **kwargs):
        return self._bot.send_message(chat_id, text, **kwargs)

    def answer_callback_query(self, callback_query_id: str, **kwargs):
        return self._bot.answer_callback_query(callback_query_id, **kwargs)

    def get_me_id(self) -> int:
        return self._bot.get_me().id

    def get_chat(self, chat_id: int):
        return self._bot.get_chat(chat_id)


class MaxMessengerClient(BaseMessengerClient):
    platform = 'max'

    def __init__(self):
        self.base_url = os.getenv('MAX_API_BASE_URL', 'https://platform-api.max.ru')
        self.token = os.getenv('MAX_BOT_TOKEN')

    def _request(self, method: str, path: str, **kwargs):
        if not self.token:
            raise RuntimeError('MAX_BOT_TOKEN is not configured')

        headers = kwargs.pop('headers', {})
        headers['Authorization'] = self.token
        return requests.request(method, f'{self.base_url}{path}', headers=headers, timeout=5, **kwargs)

    def send_message(self, chat_id: int, text: str, **kwargs):
        payload = {'text': text}
        response = self._request(
            'POST',
            '/messages',
            params={'chat_id': chat_id},
            headers={'Content-Type': 'application/json'},
            json=payload,
        )
        response.raise_for_status()
        return response.json()

    def answer_callback_query(self, callback_query_id: str, **kwargs):
        if not callback_query_id:
            return None

        body = {}
        if 'notification' in kwargs:
            body['notification'] = kwargs['notification']
        response = self._request(
            'POST',
            '/answers',
            params={'callback_id': callback_query_id},
            headers={'Content-Type': 'application/json'},
            json=body,
        )
        response.raise_for_status()
        return response.json()

    def get_me_id(self) -> int:
        response = self._request('GET', '/me')
        response.raise_for_status()
        return int(response.json()['user_id'])

    def get_chat(self, chat_id: int):
        return type('Chat', (), {'id': chat_id, 'has_private_forwards': True})


class AttrDict:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class UnifiedMessage:
    def __init__(self, *, user: MessengerUser, chat: MessengerChat, text: str, context: Any = None):
        self.from_user = AttrDict(
            id=user.id,
            first_name=user.first_name,
            last_name=user.last_name,
            username=user.username,
        )
        self.chat = AttrDict(id=chat.id, type=chat.type)
        self.text = text
        self.caption = None
        self.content_type = 'text'
        self.photo = None
        self.entities = []
        self.reply_to_message = None
        self.is_edit_text = False
        self.context = context
        self.json = {
            'from': {
                'id': user.id,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'username': user.username,
                'is_bot': False,
            }
        }
