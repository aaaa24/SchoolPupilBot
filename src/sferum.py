import os
import time

import requests
import telebot
import ydb

from funcs import except_429

code = '''var all_messages = API.messages.getHistory({{"peer_id": {peer_id}, "count": {count}, "offset": -{count}, "start_message_id": {start_message_id}}}).items;
var i = 0;
var messages = [];
while (i < all_messages.length) {{
var arr = all_messages[i];
arr.push(API.users.get({{"user_ids": arr.from_id}})[0]);
messages.push(arr);
i = i + 1;}}
return messages;'''


def remixdsid2token(remixdsid):
    cookies = {'remixdsid': remixdsid}
    query = {'act': 'web_token', 'app_id': int(os.getenv('VK_APP_ID'))}

    response = requests.get(
        'https://web.vk.me/',
        params=query,
        cookies=cookies,
        allow_redirects=False,
        timeout=3,
    )
    print(response.json())
    return response.json()[1]['access_token']


def get_name_sender(access_token, from_id):
    r = requests.post('https://api.vk.com/method/users.get',
                      params={'access_token': access_token, 'lang': 'ru', 'user_ids': from_id, 'v': 5.131}).json()

    sender = r['response'][0]
    name_sender = f'{sender["last_name"]} {sender["first_name"]}'
    return name_sender


def message_processing(access_token, message, is_forwarded=False):
    result = {'text': message['text'], 'docs': [], 'photos': [], 'audios': [], 'videos': [], 'fwd_messages': []}
    localtime = time.localtime(message['date'] + 10800)
    result['time'] = time.strftime('%H:%M:%S %d.%m.%Y', localtime)
    if is_forwarded:
        result['sender'] = get_name_sender(access_token, message['from_id'])
    else:
        result['sender'] = f'{message["0"]["last_name"]} {message["0"]["first_name"]}'

    for attachment in message['attachments']:
        if attachment['type'] == 'doc':
            doc = attachment['doc']
            result['docs'].append({'title': doc['title'], 'url': doc['url'], 'ext': doc['ext']})
        elif attachment['type'] == 'photo':
            photo = attachment['photo']
            result['photos'].append({'url': max(photo['sizes'], key=lambda s: s['width'])['url']})
        elif attachment['type'] == 'video':
            video = attachment['video']
            result['videos'].append({'title': video['title']})
        elif attachment['type'] == 'audio':
            audio = attachment['audio']
            result['audios'].append({'title': audio['title'], 'url': audio['url']})

    if 'fwd_messages' in message:
        for fwd_message in message['fwd_messages']:
            result['fwd_messages'].append(message_processing(access_token, fwd_message, True))

    return result


def is_result_not_empty(result):
    return any(result[x] for x in ('text', 'docs', 'videos', 'audios', 'photos')) or \
        any(is_result_not_empty(m) for m in result['fwd_messages'])


def create_text_tg_message(message, is_forwarded=False):
    if is_forwarded:
        text = f'<b>Пересланное сообщение\n{message["sender"]}, {message["time"]}</b>'
    else:
        text = f'<b>{message["time"]}, {message["sender"]}</b>'

    if message['text']:
        text += f'\n\n{message["text"]}'

    if len(message['videos']) == 1:
        text += f'\n\nК сообщению прикреплена видеозапись с заголовком <code>{message["videos"][0]["title"]}</code>'
    elif len(message['videos']) > 1:
        text += f'\n\nК сообщению прикреплены видеозаписи с заголовками '
        text += ', '.join([f'<code>{v["title"]}</code>' for v in message['videos']])

    return text


def get_fwd_messages(message, result_messages):
    for fwd_message in message['fwd_messages']:
        text = create_text_tg_message(fwd_message, True)
        result_messages.append(
            {'text': text, 'photos': fwd_message['photos'], 'audios': fwd_message['audios'],
             'docs': fwd_message['docs']}
        )
        get_fwd_messages(fwd_message, result_messages)


def get_messages(access_token, peer_id, start_message_id):
    messages = []
    count = 24
    while True:
        format_code = code.format(peer_id=peer_id, start_message_id=start_message_id, count=count)
        r = requests.post('https://api.vk.com/method/execute',
                          params={'access_token': access_token, 'lang': 'ru', 'code': format_code, 'v': 5.131}).json()
        messages.extend(r['response'][::-1])
        if len(r['response']) < count:
            break
        start_message_id = messages[-1]['id']

    result_messages = []
    for message in messages:
        result = message_processing(access_token, message)
        if is_result_not_empty(result):
            text = create_text_tg_message(result)
            if len(result['fwd_messages']) == 1 and not result['fwd_messages'][0]['fwd_messages']:
                reply_text = create_text_tg_message(result['fwd_messages'][0], True)
                text += f'\n\n{reply_text}'
                fwd = result['fwd_messages'][0]
                result['photos'].extend(fwd['photos'])
                result['audios'].extend(fwd['audios'])
                result['docs'].extend(fwd['docs'])
            result_messages.append(
                {'text': text, 'photos': result['photos'], 'audios': result['audios'], 'docs': result['docs']}
            )

            if len(result['fwd_messages']) > 1 or len(result['fwd_messages']) == 1 and result['fwd_messages'][0][
                'fwd_messages']:
                result_fwd_messages = []
                get_fwd_messages(message, result_fwd_messages)
                result_messages.extend(result_fwd_messages)

    if messages:
        last_id = messages[-1]['id']
    else:
        last_id = None
    return result_messages, last_id


def get_doc_file(url):
    doc_file = requests.get(url)
    return doc_file.content


def chat_processing(bot, session, logger, line):
    start_time = time.time()
    logger.debug('Запущена функция chat_processing')
    log_info = {
        'line': line.copy(), 'last_id': None, 'count_messages': None,
    }

    if line['access_token'] is None:
        access_token = remixdsid2token(line['remixdsid'])
    else:
        access_token = line['access_token']

    chat_id = line['chat_id']
    messages, last_id = get_messages(access_token, line['peer_id'], line['last_id'])

    for message in messages:
        text = '#Сферум\n' + message['text']
        photos = message['photos']
        audios = message['audios']
        docs = message['docs']

        if not (photos or audios or docs):
            except_429(
                "k['bot'].send_message(k['chat_id'], k['text'], parse_mode = 'HTML', disable_web_page_preview = True)",
                bot=bot, chat_id=chat_id, text=text
            )

        else:
            media = []
            for photo in photos:
                media.append(telebot.types.InputMediaPhoto(photo['url']))
            for audio in audios:
                media.append(telebot.types.InputMediaAudio(audio['url']))
            for doc in docs:
                if doc['ext'] in ('gif', 'pdf', 'zip'):
                    media.append(telebot.types.InputMediaDocument(doc['url']))
                else:
                    doc_file = get_doc_file(doc['url'])
                    media.append(telebot.types.InputMediaDocument(doc_file))

            if len(text) > 1023:

                for itog_media in [media[i:i + 10] for i in range(0, len(media), 10)]:
                    except_429(
                        "k['bot'].send_media_group(k['chat_id'], k['itog_media'])",
                        bot=bot, chat_id=chat_id, itog_media=itog_media
                    )
                except_429(
                    "k['bot'].send_message(k['chat_id'], k['text'], parse_mode = 'HTML', disable_web_page_preview = True)",
                    bot=bot, chat_id=chat_id, text=text
                )

            else:
                last_element = media[-(len(media) % 10)]
                last_element.caption = text
                last_element.parse_mode = 'HTML'
                last_element.disable_web_page_preview = True
                for itog_media in [media[i:i + 10] for i in range(0, len(media), 10)]:
                    except_429(
                        "k['bot'].send_media_group(k['chat_id'], k['itog_media'])",
                        bot=bot, chat_id=chat_id, itog_media=itog_media
                    )

    line['last_id'] = last_id

    log_info['last_id'] = last_id
    log_info['count_messages'] = len(messages)
    logger.debug('Завершена функция chat_processing', extra={'duration': time.time() - start_time, 'info': log_info})
    return line


def record_last_ids(lines, session):
    values = ', '.join([f'({line["id"]}, {line["last_id"]})' for line in lines])
    text_request = f'UPSERT INTO sferum (id, last_id) VALUES {values}'
    request = session.transaction().execute(
        text_request,
        commit_tx=True,
        settings=ydb.BaseRequestSettings().with_timeout(3).with_operation_timeout(2)
    )


def mailing_sferum(bot, session, logger):
    start_time = time.time()
    logger.debug('Запущена функция mailing_sferum')
    log_info = {
        'count_lines': None
    }

    request = session.transaction().execute(
        f'SELECT * FROM sferum',
        commit_tx=True,
        settings=ydb.BaseRequestSettings().with_timeout(3).with_operation_timeout(2)
    )

    lines = request[0].rows
    new_lines = []
    for line in lines:
        new_line = chat_processing(bot, session, logger, line)
        if not new_line['last_id'] is None:
            new_lines.append(new_line)
    if new_lines:
        record_last_ids(new_lines, session)

    log_info['count_lines'] = len(lines)
    logger.debug('Завершена функция mailing_sferum', extra={'duration': time.time() - start_time, 'info': log_info})
