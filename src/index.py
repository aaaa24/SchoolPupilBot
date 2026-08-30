from json import dumps, loads

import telebot

from main import bot, logger, process_max_callback, process_command_message, process_text_message, set_connect, \
    set_log_messenger, log_traceback, telegram_client
from messengers import (
    MaxMessengerClient,
    Messenger,
    MessengerChat,
    MessengerUser,
    UnifiedCallbackMessage,
    UnifiedCallbackQuery,
    UnifiedMessage,
    UnifiedPhoto,
    max_keyboard_to_markup,
)


def _is_command(text):
    return isinstance(text, str) and text.startswith('/')


def _is_processed_max_chat(max_message):
    chat = max_message.message.chat if hasattr(max_message, 'data') else max_message.chat
    return chat.type == 'private' or chat.id == Messenger.MAX.techno_chat_id


def _max_photos(body):
    return [
        UnifiedPhoto(attachment['payload']['token'], attachment['payload'].get('url'))
        for attachment in body.get('attachments', []) or []
        if attachment.get('type') == 'image' and attachment.get('payload', {}).get('token')
    ]


_MAX_CHAT_TYPES = {'dialog': 'private', 'chat': 'group', 'channel': 'channel'}


def _max_chat(recipient):
    chat_id = recipient.get('chat_id') or recipient.get('user_id')
    if chat_id is None:
        return None
    return MessengerChat(id=int(chat_id), type=_MAX_CHAT_TYPES.get(recipient.get('chat_type'), 'private'))


def _max_user(data):
    return MessengerUser(
        id=int(data['user_id']),
        first_name=data.get('first_name', data.get('name', 'Пользователь')),
        last_name=data.get('last_name'),
        username=data.get('username'),
    )


def _max_reply_to_message(link, chat):
    if not link or link.get('type') != 'reply':
        return None

    body = link.get('message', {}) or {}
    sender = link.get('sender', {}) or {}
    if not sender.get('user_id'):
        return None

    photos = _max_photos(body)
    return UnifiedCallbackMessage(
        messenger=Messenger.MAX,
        user=_max_user(sender),
        chat=chat,
        text=body.get('text') or '',
        caption=body.get('text') if photos else None,
        message_id=body.get('mid'),
        reply_markup=max_keyboard_to_markup(body.get('attachments')),
        photos=photos or None,
    )


def _parse_max_update(payload, context):
    update_type = payload.get('update_type')

    if update_type == 'message_created':
        message = payload.get('message', {})
        body = message.get('body', {}) or {}
        sender = message.get('sender', {}) or {}
        recipient = message.get('recipient', {}) or {}

        text = body.get('text')
        user_id = sender.get('user_id')
        chat = _max_chat(recipient)

        photos = _max_photos(body)
        link = message.get('link', {}) or {}
        if not photos and link.get('type') == 'forward':
            # у пересылки фотографии и подпись лежат в исходном сообщении
            forwarded = link.get('message', {}) or {}
            photos = _max_photos(forwarded)
            text = text or forwarded.get('text')

        if user_id is None or chat is None or (text is None and not photos):
            return None

        return UnifiedMessage(
            messenger=Messenger.MAX,
            user=_max_user(sender),
            chat=chat,
            text=None if photos else text,
            caption=text if photos else None,
            photos=photos or None,
            message_id=body.get('mid'),
            reply_to_message=_max_reply_to_message(link, chat),
            context=context,
        )

    if update_type == 'message_callback':
        callback = payload.get('callback', {}) or {}
        callback_id = callback.get('callback_id')
        callback_payload = callback.get('payload')
        message = payload.get('message', {}) or {}
        callback_user = callback.get('user', {}) or {}
        recipient = message.get('recipient', {}) or {}
        body = message.get('body', {}) or {}

        user_id = callback_user.get('user_id')
        chat = _max_chat(recipient)
        if callback_id is None or callback_payload is None or user_id is None or chat is None:
            return None

        user = _max_user(callback_user)
        callback_message = UnifiedCallbackMessage(
            messenger=Messenger.MAX,
            user=user,
            chat=chat,
            text=body.get('text') or '',
            message_id=body.get('mid'),
            reply_markup=max_keyboard_to_markup(body.get('attachments')),
            photos=_max_photos(body) or None,
            reply_to_message=_max_reply_to_message(message.get('link', {}) or {}, chat),
        )
        return UnifiedCallbackQuery(
            messenger=Messenger.MAX,
            id=str(callback_id),
            user=user,
            data=str(callback_payload),
            message=callback_message,
            context=context,
        )

    if update_type == 'bot_started':
        user_data = payload.get('user', {})
        user_id = user_data.get('user_id')
        chat_id = payload.get('chat_id')
        if user_id is None or chat_id is None:
            return None

        payload_text = payload.get('payload')
        text = '/start' if payload_text is None else f'/start {payload_text}'
        return UnifiedMessage(messenger=Messenger.MAX, user=_max_user(user_data),
                              chat=MessengerChat(id=int(chat_id)), text=text, context=context)

    return None


def handler(event, context):
    if 'httpMethod' in event:
        if event['path'] in ('/telegram', '/yookassa'):
            set_log_messenger(Messenger.TELEGRAM)
        elif event['path'] == '/max':
            set_log_messenger(Messenger.MAX)

        if event['path'] == '/telegram':
            message = telebot.types.Update.de_json(event['body'])
            logger.info('Получено событие Telegram',
                        extra={"update": loads(dumps(message, default=vars, ensure_ascii=False))})

            if message.message:
                message.message.context = context
                message.message.messenger = Messenger.TELEGRAM
            if message.callback_query:
                message.callback_query.context = context
                message.callback_query.messenger = Messenger.TELEGRAM
                message.callback_query.message.messenger = Messenger.TELEGRAM

            bot.process_new_updates([message])

        elif event['path'] == '/max':
            payload = loads(event['body'])
            logger.info('Получено событие MAX', extra={'update': payload})

            max_message = _parse_max_update(payload, context)
            if max_message is not None and not _is_processed_max_chat(max_message):
                logger.debug('Событие не обрабатывается')
            elif max_message is not None:
                max_client = MaxMessengerClient()
                try:
                    if hasattr(max_message, 'data'):
                        process_max_callback(max_message, max_client)
                    elif _is_command(max_message.text):
                        process_command_message(max_message, max_client)
                    else:
                        process_text_message(max_message, max_client)
                except Exception:
                    log_traceback('Ошибка при обработке события MAX')

        elif event['path'] == '/yookassa':
            session, _ = set_connect(50)
            if not session is None:
                from pay import successful_payment
                payment = loads(event['body'])['object']
                successful_payment(bot, payment, session, logger)
                session.closing()

    elif 'details' in event and 'payload' in event['details']:
        clients = {
            Messenger.TELEGRAM: telegram_client,
            Messenger.MAX: MaxMessengerClient(),
        }
        if event['details']['payload'] == 'daily_statistics':
            from statistics import daily_statistics
            daily_statistics(clients, context, logger)
        elif event['details']['payload'] == 'mailing_changes_tt':
            session, _ = set_connect(50)
            if not session is None:
                from changes_tt import mailing_changes_tt
                mailing_changes_tt(clients, session, logger)
                session.closing()

    return {'statusCode': 200, 'body': '!'}
