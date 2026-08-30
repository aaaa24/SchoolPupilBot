from __future__ import annotations

import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from io import BytesIO
from typing import Any, Optional

import requests
from telebot import apihelper, types


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


@dataclass
class ScreenState:
    chat_id: int
    message_id: Optional[Any] = None
    content_type: Optional[str] = None


@dataclass
class MediaItem:
    id: Optional[str] = None
    data: Optional[bytes] = None
    filename: Optional[str] = None
    content_type: Optional[str] = None


class SentMessage:
    def __init__(self, chat_id, message_id, content_type='text'):
        self.chat = AttrDict(id=chat_id)
        self.message_id = message_id
        self.id = message_id
        self.content_type = content_type


# Суффикс отмечает кнопки экрана, у которого фотографии отправлены отдельно от подписи с клавиатурой
# (медиагруппа в Telegram). Такой экран нельзя изменить, не оторвав фотографии от подписи,
# поэтому по нажатию его кнопок всегда отправляется новый экран
DETACHED_SUFFIX = '$grp'


def force_new_screen(data) -> bool:
    if not data:
        return False
    return '$new' in data or '$sdel' in data or DETACHED_SUFFIX in data


def mark_detached(reply_markup):
    if reply_markup is None:
        return None

    marked = types.InlineKeyboardMarkup()
    for row in reply_markup.keyboard:
        buttons = []
        for button in row:
            if button.callback_data and DETACHED_SUFFIX not in button.callback_data:
                buttons.append(types.InlineKeyboardButton(button.text,
                                                          callback_data=button.callback_data + DETACHED_SUFFIX))
            else:
                buttons.append(button)
        marked.row(*buttons)
    return marked


class Messenger(Enum):
    TELEGRAM = 'telegram'
    MAX = 'max'

    @property
    def nice_name(self) -> str:
        return {'telegram': 'Telegram', 'max': 'MAX'}[self.value]

    @property
    def table_name(self) -> str:
        return f'users_{self.value}'

    @property
    def superadmin_id(self) -> Optional[int]:
        value = os.getenv(f'{self.value.upper()}_SUPERADMIN')
        return int(value) if value else None

    @property
    def techno_chat_id(self) -> Optional[int]:
        value = os.getenv(f'{self.value.upper()}_TECHNO_INFO')
        return int(value) if value else None

    @property
    def text_limit(self) -> int:
        return {'telegram': 4096, 'max': 4000}[self.value]


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

    @abstractmethod
    def download_photo(self, photo):
        pass

    @abstractmethod
    def send_photos(self, chat_id: int, media: list[MediaItem], caption: str, reply_markup=None, **kwargs):
        pass

    @abstractmethod
    def send_message_to_user(self, user_id, text, media=None, reply_markup=None, **kwargs):
        pass

    @abstractmethod
    def forward_message(self, chat_id, from_chat_id, message_id):
        pass

    @abstractmethod
    def render_screen(self, state, text, media, reply_markup=None, force_new=False):
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

    def download_photo(self, photo):
        file_info = self._bot.get_file(photo.file_id)
        return self._bot.download_file(file_info.file_path), None

    def _input_photo(self, item: MediaItem):
        if item.id:
            return item.id
        stream = BytesIO(item.data)
        stream.name = item.filename or 'photo.jpg'
        return stream

    def send_photos(self, chat_id: int, media: list[MediaItem], caption: str, reply_markup=None, **kwargs):
        if not media:
            return self._bot.send_message(chat_id, caption, reply_markup=reply_markup, **kwargs)

        if len(media) == 1:
            message = self._bot.send_photo(chat_id, photo=self._input_photo(media[0]), caption=caption,
                                           reply_markup=reply_markup, **kwargs)
            media[0].id = message.photo[-1].file_id
            return message

        for start in range(0, len(media), 10):
            chunk = media[start:start + 10]
            messages = self._bot.send_media_group(chat_id, [types.InputMediaPhoto(self._input_photo(item))
                                                            for item in chunk])
            for item, message in zip(chunk, messages):
                item.id = message.photo[-1].file_id
        return self._bot.send_message(chat_id, caption, reply_markup=mark_detached(reply_markup), **kwargs)

    def send_message_to_user(self, user_id, text, media=None, reply_markup=None, **kwargs):
        if media:
            return self.send_photos(user_id, media, text, reply_markup=reply_markup, **kwargs)
        return self._bot.send_message(user_id, text, reply_markup=reply_markup, **kwargs)

    def forward_message(self, chat_id, from_chat_id, message_id):
        return self._bot.forward_message(chat_id, from_chat_id, message_id)

    def render_screen(self, state, text, media, reply_markup=None, force_new=False):
        media = media or []

        if state.message_id is not None and not force_new:
            try:
                if len(media) == 1 and state.content_type == 'photo':
                    photo = types.InputMediaPhoto(self._input_photo(media[0]), caption=text)
                    message = self._bot.edit_message_media(photo, state.chat_id, state.message_id,
                                                           reply_markup=reply_markup)
                    if getattr(message, 'photo', None):
                        media[0].id = message.photo[-1].file_id
                    return message
                if not media and state.content_type == 'text':
                    return self._bot.edit_message_text(text, state.chat_id, state.message_id, reply_markup=reply_markup)
            except apihelper.ApiTelegramException as e:
                if 'message is not modified' in str(e):
                    return None

        return self.send_photos(state.chat_id, media, text, reply_markup=reply_markup)


_max_me_id = None


class MaxMessengerClient(BaseMessengerClient):
    platform = Messenger.MAX

    def __init__(self):
        self.base_url = os.getenv('MAX_API_BASE_URL', 'https://platform-api2.max.ru')
        self.token = os.getenv('MAX_BOT_TOKEN')
        self._active_callback_id = None
        self._active_callback_mid = None
        self._callback_answered = False
        self._pending_callback_message = None
        self._pending_callback_notification = None

    def _request(self, method: str, path: str, **kwargs):
        if not self.token:
            raise RuntimeError('MAX_BOT_TOKEN is not configured')

        headers = kwargs.pop('headers', {})
        headers['Authorization'] = self.token
        return requests.request(method, f'{self.base_url}{path}', headers=headers, timeout=5, **kwargs)

    def _send_body(self, method: str, path: str, params: dict, payload: dict):
        delay = 1
        for attempt in range(5):
            response = self._request(method, path, params=params,
                                     headers={'Content-Type': 'application/json'}, json=payload)
            if response.ok:
                return response.json()
            if response.status_code != 400 or 'attachment.not.ready' not in response.text or attempt == 4:
                response.raise_for_status()
            time.sleep(delay)
            delay *= 2

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

    def _build_message_body(self, text: Optional[str] = None, attachments=None, **kwargs):
        body = {}
        if text is not None:
            body['text'] = text

        keyboard_attachments = self._build_attachments(kwargs.get('reply_markup'))
        if attachments is not None:
            body['attachments'] = attachments + (keyboard_attachments or [])
        elif keyboard_attachments is not None:
            body['attachments'] = keyboard_attachments

        parse_mode = kwargs.get('parse_mode')
        if parse_mode:
            parse_mode = parse_mode.lower()
            if parse_mode in ('markdown', 'markdownv2'):
                body['format'] = 'markdown'
            elif parse_mode == 'html':
                body['format'] = 'html'

        reply_to_message_id = kwargs.get('reply_to_message_id')
        if reply_to_message_id:
            body['link'] = {'type': 'reply', 'mid': str(reply_to_message_id)}

        return body

    def begin_callback(self, callback_id: str, text=None, photos=None, reply_markup=None, message_id=None):
        self._active_callback_id = callback_id
        self._active_callback_mid = message_id
        self._callback_answered = False
        self._pending_callback_notification = None

        image_attachments = [{'type': 'image', 'payload': {'token': photo.file_id}} for photo in (photos or [])]
        self._pending_callback_message = {
            'attachments': image_attachments + (self._build_attachments(reply_markup) or []),
        }
        if text is not None:
            self._pending_callback_message['text'] = text

    def _is_callback_message(self, message_id):
        if not self._active_callback_id or self._callback_answered:
            return False
        return message_id is None or self._active_callback_mid is None or \
            str(message_id) == str(self._active_callback_mid)

    def _enqueue_callback_message(self, message_body, message_id=None):
        if not self._is_callback_message(message_id):
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

    def _sent_message(self, result, chat_id=None, content_type='text'):
        message = (result or {}).get('message') or {}
        body = message.get('body') or {}
        recipient = message.get('recipient') or {}
        if chat_id is None:
            chat_id = recipient.get('chat_id') or recipient.get('user_id')
        return SentMessage(chat_id, body.get('mid'), content_type)

    def send_message(self, chat_id: int, text: str, **kwargs):
        result = self._send_body('POST', '/messages', {'chat_id': chat_id},
                                 self._build_message_body(text=text, **kwargs))
        return self._sent_message(result, chat_id)

    def send_message_to_user(self, user_id, text, media=None, reply_markup=None, **kwargs):
        if media:
            return self.send_photos(user_id, media, text, reply_markup=reply_markup, target='user_id', **kwargs)

        result = self._send_body('POST', '/messages', {'user_id': user_id},
                                 self._build_message_body(text=text, reply_markup=reply_markup, **kwargs))
        return self._sent_message(result)

    def forward_message(self, chat_id, from_chat_id, message_id):
        result = self._send_body('POST', '/messages', {'chat_id': chat_id},
                                 {'link': {'type': 'forward', 'mid': str(message_id)}})
        return self._sent_message(result, chat_id)

    def edit_message_text(self, text, chat_id, message_id, **kwargs):
        payload = self._build_message_body(text=text, **kwargs)
        if self._enqueue_callback_message(payload, message_id):
            return {'success': True}

        return self._send_body('PUT', '/messages', {'message_id': message_id}, payload)

    def edit_message_reply_markup(self, chat_id, message_id, reply_markup=None, **kwargs):
        payload = {'attachments': self._build_attachments(reply_markup) or []}
        if self._enqueue_callback_message(payload, message_id):
            return {'success': True}

        return self._send_body('PUT', '/messages', {'message_id': message_id}, payload)

    def delete_message(self, chat_id, message_id):
        response = self._request('DELETE', '/messages', params={'message_id': message_id})
        response.raise_for_status()

        if self._is_callback_message(message_id) and self._active_callback_mid is not None:
            self._callback_answered = True
            self._active_callback_id = None
            self._active_callback_mid = None
            self._pending_callback_message = None
            self._pending_callback_notification = None
        return response.json()

    def get_message(self, message_id):
        response = self._request('GET', f'/messages/{message_id}')
        response.raise_for_status()
        result = response.json()
        return result.get('message', result)

    def send_photo(self, chat_id, photo, caption=None, **kwargs):
        return self.send_photos(chat_id, [MediaItem(id=photo)], caption or '', **kwargs)

    def download_photo(self, photo):
        if not getattr(photo, 'url', None):
            raise ValueError('У фотографии MAX отсутствует URL для скачивания')
        response = requests.get(photo.url, timeout=15)
        response.raise_for_status()
        return response.content, response.headers.get('Content-Type')

    def upload_photo(self, data: bytes, filename: str, content_type: str | None = None):
        response = self._request('POST', '/uploads', params={'type': 'image'})
        response.raise_for_status()
        upload_url = response.json()['url']
        response = requests.post(
            upload_url,
            files={'data': (filename, data, content_type or 'image/jpeg')},
            timeout=30,
        )
        response.raise_for_status()
        photos = response.json().get('photos')
        if not photos:
            raise RuntimeError('MAX не вернул токен загруженного изображения')
        token = tuple(photos.values())[0]['token']
        return token

    def _image_attachments(self, media: list[MediaItem]):
        attachments = []
        for item in media:
            if not item.id:
                item.id = self.upload_photo(item.data, item.filename or 'photo.jpg', item.content_type)
            attachments.append({'type': 'image', 'payload': {'token': item.id}})
        return attachments

    def send_photos(self, chat_id: int, media: list[MediaItem], caption: str, reply_markup=None, **kwargs):
        target = kwargs.pop('target', 'chat_id')
        if not media:
            if target == 'user_id':
                return self.send_message_to_user(chat_id, caption, reply_markup=reply_markup, **kwargs)
            return self.send_message(chat_id, caption, reply_markup=reply_markup, **kwargs)

        chunk_size = 11 if reply_markup else 12
        result = None
        for start in range(0, len(media), chunk_size):
            is_last_chunk = start + chunk_size >= len(media)
            payload = self._build_message_body(
                caption if is_last_chunk else '',
                attachments=self._image_attachments(media[start:start + chunk_size]),
                reply_markup=reply_markup if is_last_chunk else None,
                **kwargs,
            )
            result = self._send_body('POST', '/messages', {target: chat_id}, payload)
        return self._sent_message(result, chat_id if target == 'chat_id' else None, 'photo')

    def render_screen(self, state, text, media, reply_markup=None, force_new=False):
        media = media or []
        limit = 11 if reply_markup else 12

        if state.message_id is not None and not force_new and len(media) <= limit:
            payload = self._build_message_body(text, attachments=self._image_attachments(media),
                                               reply_markup=reply_markup)
            if self._enqueue_callback_message(payload, state.message_id):
                return {'success': True}

            return self._send_body('PUT', '/messages', {'message_id': state.message_id}, payload)

        return self.send_photos(state.chat_id, media, text, reply_markup=reply_markup)

    def answer_callback_query(self, callback_query_id: str, **kwargs):
        if self._callback_answered:
            return None

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

        result = self._send_body('POST', '/answers', {'callback_id': callback_id}, body)

        if not result.get('success', False):
            raise RuntimeError(f"Ошибка ответа на callback MAX: {result.get('message', 'неизвестная ошибка')}")

        self._callback_answered = True
        self._active_callback_id = None
        self._active_callback_mid = None
        self._pending_callback_message = None
        self._pending_callback_notification = None
        return result

    def get_me_id(self) -> int:
        global _max_me_id
        if _max_me_id is not None:
            return _max_me_id

        response = self._request('GET', '/me')
        response.raise_for_status()
        _max_me_id = int(response.json()['user_id'])
        return _max_me_id

    def get_me(self):
        return AttrDict(id=self.get_me_id())

    def get_chat(self, chat_id: int):
        raise NotImplementedError('В MAX нет получения пользователя по id')


def get_client(bot):
    if isinstance(bot, BaseMessengerClient):
        return bot
    return TelegramMessengerClient(bot)


class AttrDict:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class UnifiedPhoto:
    def __init__(self, file_id: str, url: Optional[str] = None):
        self.file_id = file_id
        self.url = url


class UnifiedMessage:
    def __init__(self, *, messenger: Messenger, user: MessengerUser, chat: MessengerChat, text: Optional[str], context: Any = None,
                 photos=None, caption: Optional[str] = None, message_id=None, reply_to_message=None):
        self.messenger = messenger
        self.from_user = AttrDict(
            id=user.id,
            first_name=user.first_name,
            last_name=user.last_name,
            username=user.username,
        )
        self.chat = AttrDict(id=chat.id, type=chat.type)
        self.text = text
        self.caption = caption
        self.content_type = 'photo' if photos else 'text'
        self.photo = photos
        self.entities = []
        self.message_id = message_id
        self.id = message_id
        self.reply_to_message = reply_to_message
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
                 reply_markup=None, photos=None, reply_to_message=None, caption=None):
        self.messenger = messenger
        self.from_user = AttrDict(
            id=user.id,
            first_name=user.first_name,
            last_name=user.last_name,
            username=user.username,
        )
        self.chat = AttrDict(id=chat.id, type=chat.type)
        self.text = text
        self.caption = caption
        self.content_type = 'photo' if photos else 'text'
        self.photo = photos
        self.message_id = message_id
        self.id = message_id
        self.reply_markup = reply_markup
        self.reply_to_message = reply_to_message


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
