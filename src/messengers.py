from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
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


class Messenger(Enum):
    TELEGRAM = 'telegram'
    MAX = 'max'

    @property
    def nice_name(self) -> str:
        return {'telegram': 'Telegram', 'max': 'MAX'}[self.value]

    @property
    def table_name(self) -> str:
        return f'users_{self.value}'


class BaseMessengerClient(ABC):
    platform: Messenger

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
    platform = Messenger.TELEGRAM

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
    platform = Messenger.MAX

    def __init__(self):
        self.base_url = os.getenv('MAX_API_BASE_URL', 'https://platform-api.max.ru')
        self.token = os.getenv('MAX_BOT_TOKEN')
        self._me_id = None
        self._active_callback_id = None
        self._callback_answered = False
        self._pending_callback_message = None
        self._pending_callback_notification = None

    def _request(self, method: str, path: str, **kwargs):
        if not self.token:
            raise RuntimeError('MAX_BOT_TOKEN is not configured')

        headers = kwargs.pop('headers', {})
        headers['Authorization'] = self.token
        return requests.request(method, f'{self.base_url}{path}', headers=headers, timeout=5, **kwargs)

    def _build_attachments(self, reply_markup):
        if reply_markup is None:
            return None

        keyboard = []
        for row in getattr(reply_markup, 'keyboard', []):
            max_row = []
            for button in row:
                if getattr(button, 'url', None):
                    max_row.append({'type': 'link', 'text': button.text, 'url': button.url})
                elif getattr(button, 'callback_data', None) is not None:
                    max_row.append({'type': 'callback', 'text': button.text, 'payload': button.callback_data})
            if max_row:
                keyboard.append(max_row)

        if not keyboard:
            return []

        return [{'type': 'inline_keyboard', 'payload': {'buttons': keyboard}}]

    def _build_message_body(self, text: Optional[str] = None, **kwargs):
        body = {}
        if text is not None:
            body['text'] = text

        attachments = self._build_attachments(kwargs.get('reply_markup'))
        if attachments is not None:
            body['attachments'] = attachments

        parse_mode = kwargs.get('parse_mode')
        if parse_mode:
            parse_mode = parse_mode.lower()
            if parse_mode in ('markdown', 'markdownv2'):
                body['format'] = 'markdown'
            elif parse_mode == 'html':
                body['format'] = 'html'

        return body

    def begin_callback(self, callback_id: str, reply_markup=None):
        self._active_callback_id = callback_id
        self._callback_answered = False
        self._pending_callback_message = {}
        self._pending_callback_notification = None

        attachments = self._build_attachments(reply_markup)
        if attachments is not None:
            self._pending_callback_message['attachments'] = attachments

    def _enqueue_callback_message(self, message_body):
        if not self._active_callback_id or self._callback_answered:
            return False

        if self._pending_callback_message is None:
            self._pending_callback_message = {}

        for key in ('text', 'attachments', 'format'):
            if key in message_body:
                self._pending_callback_message[key] = message_body[key]

        return True

    def _enqueue_callback_notification(self, notification: Optional[str]):
        if not self._active_callback_id or self._callback_answered:
            return False

        self._pending_callback_notification = notification
        return True

    def send_message(self, chat_id: int, text: str, **kwargs):
        payload = self._build_message_body(text=text, **kwargs)
        response = self._request(
            'POST',
            '/messages',
            params={'chat_id': chat_id},
            headers={'Content-Type': 'application/json'},
            json=payload,
        )
        response.raise_for_status()
        return response.json()

    def edit_message_text(self, text, chat_id, message_id, **kwargs):
        payload = self._build_message_body(text=text, **kwargs)
        if self._enqueue_callback_message(payload):
            return {'success': True}

        return {
            'success': False,
            'message': 'Редактирование сообщений MAX возможно только через /answers в контексте callback',
        }

    def edit_message_reply_markup(self, chat_id, message_id, reply_markup=None, **kwargs):
        payload = {'attachments': self._build_attachments(reply_markup) or []}
        if self._enqueue_callback_message(payload):
            return {'success': True}

        return {
            'success': False,
            'message': 'Редактирование клавиатуры MAX доступно только в контексте callback через /answers',
        }

    def delete_message(self, chat_id, message_id):
        response = self._request('DELETE', '/messages', params={'message_id': message_id})
        response.raise_for_status()
        return response.json()

    def send_photo(self, chat_id, photo, caption=None, **kwargs):
        text = caption or ''
        return self.send_message(chat_id, text, **kwargs)

    def answer_callback_query(self, callback_query_id: str, **kwargs):
        callback_id = callback_query_id or self._active_callback_id
        if not callback_id:
            return None

        notification = kwargs.get('notification')
        if notification is not None:
            self._enqueue_callback_notification(notification)

        body = {}
        if self._pending_callback_message:
            body['message'] = self._pending_callback_message
        if self._pending_callback_notification is not None:
            body['notification'] = self._pending_callback_notification

        response = self._request(
            'POST',
            '/answers',
            params={'callback_id': callback_id},
            headers={'Content-Type': 'application/json'},
            json=body,
        )
        response.raise_for_status()
        result = response.json()
        if not result.get('success', False):
            raise RuntimeError(f"Ошибка ответа на callback MAX: {result.get('message', 'неизвестная ошибка')}")

        self._callback_answered = True
        self._active_callback_id = None
        self._pending_callback_message = None
        self._pending_callback_notification = None
        return result

    def get_me_id(self) -> int:
        if self._me_id is not None:
            return self._me_id

        response = self._request('GET', '/me')
        response.raise_for_status()
        self._me_id = int(response.json()['user_id'])
        return self._me_id

    def get_me(self):
        return AttrDict(id=self.get_me_id())

    def get_chat(self, chat_id: int):
        return type('Chat', (), {'id': chat_id, 'has_private_forwards': True})


class AttrDict:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class UnifiedMessage:
    def __init__(self, *, messenger: Messenger, user: MessengerUser, chat: MessengerChat, text: str, context: Any = None):
        self.messenger = messenger
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


class UnifiedInlineKeyboardButton:
    def __init__(self, text, callback_data=None, url=None):
        self.text = text
        self.callback_data = callback_data
        self.url = url


class UnifiedInlineKeyboardMarkup:
    def __init__(self, keyboard):
        self.keyboard = keyboard


class UnifiedCallbackMessage:
    def __init__(self, *, messenger: Messenger, user: MessengerUser, chat: MessengerChat, text: str, message_id: Optional[str],
                 reply_markup=None):
        self.messenger = messenger
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
        self.message_id = message_id
        self.id = message_id
        self.reply_markup = reply_markup


class UnifiedCallbackQuery:
    def __init__(self, *, messenger: Messenger, id: str, user: MessengerUser, data: str, message: UnifiedCallbackMessage,
                 context: Any = None):
        self.messenger = messenger
        self.id = id
        self.from_user = AttrDict(
            id=user.id,
            first_name=user.first_name,
            last_name=user.last_name,
            username=user.username,
        )
        self.data = data
        self.message = message
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


def max_keyboard_to_markup(attachments):
    if not attachments:
        return None

    keyboard_attachment = None
    for attachment in attachments:
        if attachment.get('type') == 'inline_keyboard':
            keyboard_attachment = attachment
            break

    if keyboard_attachment is None:
        return None

    buttons = keyboard_attachment.get('payload', {}).get('buttons', [])
    rows = []
    for row in buttons:
        row_buttons = []
        for button in row:
            if button.get('type') == 'link':
                row_buttons.append(UnifiedInlineKeyboardButton(button.get('text', ''), url=button.get('url')))
            elif button.get('type') == 'callback':
                row_buttons.append(
                    UnifiedInlineKeyboardButton(button.get('text', ''), callback_data=button.get('payload', ''))
                )
        if row_buttons:
            rows.append(row_buttons)

    return UnifiedInlineKeyboardMarkup(rows) if rows else None
