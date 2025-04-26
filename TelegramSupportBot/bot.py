import config
import core
import telebot
import markup
import sys
from telebot import apihelper
from threading import Timer

active_buttons = {}
user_req_messages = {}
user_req_timers   = {}


class ButtonManager:
    def __init__(self, bot, timeout=86400):
        self.bot = bot
        self.timeout = timeout
        # Для каждого chat_id храним кортеж (message_id, Timer)
        self._data = {}

    def send(self, chat_id, text, reply_markup=None, parse_mode=None):
        # 2. Отправляем новое сообщение
        sent = self.bot.send_message(chat_id, text,
                                     reply_markup=reply_markup,
                                     parse_mode=parse_mode)
        msg_id = sent.message_id

        # 3. Запускаем таймер на удаление через timeout секунд
        def _delete():
            try:
                self.bot.delete_message(chat_id, msg_id)
            except:
                pass
            # чистим запись
            self._data.pop(chat_id, None)

        t = Timer(self.timeout, _delete)
        t.start()

        # 4. Сохраняем таймер и message_id
        self._data[chat_id] = (msg_id, t)
        return sent
    
bot = telebot.TeleBot(config.TOKEN, skip_pending=True)
button_mgr = ButtonManager(bot, timeout=600)

def remove_buttons(chat_id, message_id):
    try:
        bot.edit_message_reply_markup(chat_id=chat_id, message_id=message_id, reply_markup=None)
    except Exception as e:
        print(f"Ошибка при удалении кнопок: {e}")

def manage_agent_buttons(chat_id, markup):
    if chat_id in active_buttons:
        try:
            old = active_buttons[chat_id]
            bot.edit_message_reply_markup(chat_id=chat_id, message_id=old['message_id'], reply_markup=None)
            old['timer'].cancel()
        except Exception as e:
            print(f"Ошибка при удалении предыдущих кнопок: {e}")

    msg = button_mgr.send(chat_id, "📋 Меню агента поддержки", reply_markup=markup)

    timer = Timer(1800, remove_buttons, args=[chat_id, msg.message_id])
    timer.start()

    active_buttons[chat_id] = {'message_id': msg.message_id, 'timer': timer}

if config.PROXY_URL:
    apihelper.proxy = {'https': config.PROXY_URL}

@bot.message_handler(commands=['start'])
def start(message):
    bot.send_message(message.chat.id, '👋🏻 Привет! Это бот для технической поддержки участников хакатона ИТыГерой.\nЕсли у тебя есть какой-либо вопрос или проблема - нажми на кнопку <b>Написать запрос</b> и наши сотрудники в скором времени тебе ответят!', parse_mode='html', reply_markup=markup.markup_main())


@bot.message_handler(commands=['agent'])
def agent(message):
    user_id = message.from_user.id

    if core.check_agent_status(user_id) == True: 
        button_mgr.send(message.chat.id, '🔑 Вы авторизованы как Агент поддержки', parse_mode='html', reply_markup=markup.markup_agent())

    else:
        take_password_message = bot.send_message(message.chat.id, '⚠️ Тебя нет в базе. Отправь одноразовый пароль доступа.', reply_markup=markup.markup_cancel())

        bot.clear_step_handler_by_chat_id(message.chat.id)
        bot.register_next_step_handler(take_password_message, get_password_message)


@bot.message_handler(commands=['admin'])
def admin(message):
    user_id = message.from_user.id

    maksim = config.ADMIN_ID[1]
    andrey = config.ADMIN_ID[0]
    if str(user_id) == maksim:
        button_mgr.send(message.chat.id, '🔑 Вы авторизованы как Админ', reply_markup=markup.markup_admin())
    else:
        bot.send_message(message.chat.id, '🚫 Эта команда доступна только администратору.')


@bot.message_handler(content_types=['text'])
def send_text(message):
    user_id = message.from_user.id

    if message.text == '✏️ Написать запрос':
        take_new_request = bot.send_message(message.chat.id, 'Введите свой запрос и наши сотрудники скоро с вами свяжутся.\nВы можете прикреплять к вопросу файлы/фотографии/видео', reply_markup=markup.markup_cancel())

        bot.clear_step_handler_by_chat_id(message.chat.id)
        bot.register_next_step_handler(take_new_request, get_new_request)

    elif message.text == '✉️ Мои запросы':
        # 1. Отменяем прошлый таймер и удаляем старое сообщение (если есть)
        if user_id in user_req_timers:
            user_req_timers[user_id].cancel()
        if user_id in user_req_messages:
            try:
                bot.delete_message(user_id, user_req_messages[user_id])
            except: pass

        # 2. Получаем новый список
        markup_req, value = markup.markup_reqs(user_id, 'my_reqs', '1')
        if value == 0:
            sent = bot.send_message(user_id, 'У вас пока ещё нет вопросов.', reply_markup=markup.markup_main())
        else:
            sent = button_mgr.send(user_id,
                                    'Ваши вопросы:',
                                    reply_markup=markup_req)

        # 3. Сохраняем message_id и запускаем таймер на удаление через 30 мин
        user_req_messages[user_id] = sent.message_id

        def _del():
            try: bot.delete_message(user_id, sent.message_id)
            except: pass
            user_req_messages.pop(user_id, None)
            user_req_timers.pop(user_id, None)

        t = Timer(1800, _del)
        t.start()
        user_req_timers[user_id] = t
    
    elif message.text == '👤 Агент поддержки':
        agent(message)
    else:
        bot.send_message(message.chat.id, 'Вы возвращены в главное меню.', parse_mode='html', reply_markup=markup.markup_main())


def get_password_message(message):
    password = message.text
    user_id = message.from_user.id

    if password == None:
        send_message = bot.send_message(message.chat.id, '⚠️ Вы отправляете не текст. Попробуйте еще раз.', reply_markup=markup.markup_cancel())

        bot.clear_step_handler_by_chat_id(message.chat.id)
        bot.register_next_step_handler(send_message, get_password_message)

    elif password.lower() == 'отмена':
        bot.send_message(message.chat.id, 'Отменено.', reply_markup=markup.markup_main())
        return

    elif core.valid_password(password) == True:
        core.delete_password(password)
        core.add_agent(user_id)

        bot.send_message(message.chat.id, '🔑 Вы авторизованы как Агент поддержки', parse_mode='html', reply_markup=markup.markup_main())
        button_mgr.send(message.chat.id, 'Выберите раздел технической панели:', parse_mode='html', reply_markup=markup.markup_agent())

    else:
        send_message = bot.send_message(message.chat.id, '⚠️ Неверный пароль. Попробуй ещё раз.', reply_markup=markup.markup_cancel())

        bot.clear_step_handler_by_chat_id(message.chat.id)
        bot.register_next_step_handler(send_message, get_password_message)


def get_agent_id_message(message):
    agent_id = message.text

    if agent_id == None:
        take_agent_id_message = bot.send_message(message.chat.id, '⚠️ Вы отправляете не текст. Попробуйте еще раз.', reply_markup=markup.markup_cancel())

        bot.clear_step_handler_by_chat_id(message.chat.id)
        bot.register_next_step_handler(take_agent_id_message, get_agent_id_message)

    elif agent_id.lower() == 'отмена':
        bot.send_message(message.chat.id, 'Отменено.', reply_markup=markup.markup_main())
        return

    else:
        core.add_agent(agent_id)
        bot.send_message(message.chat.id, '✅ Агент успешно добавлен.', reply_markup=markup.markup_main())
        button_mgr.send(message.chat.id, 'Выберите раздел админ панели:', reply_markup=markup.markup_admin())


def get_new_request(message):
    request = message.text
    user_id = message.from_user.id
    check_file = core.get_file(message)

    #Если пользователь отправляет файл
    if check_file != None:
        file_id = check_file['file_id']
        file_name = check_file['file_name']
        type = check_file['type']
        request = check_file['text']

        if str(request) == 'None':
            take_new_request = bot.send_message(message.chat.id, '⚠️ Вы не ввели ваш запрос. Попробуйте ещё раз, отправив текст вместе с файлом.', reply_markup=markup.markup_cancel())

            bot.clear_step_handler_by_chat_id(message.chat.id)
            bot.register_next_step_handler(take_new_request, get_new_request)

        else:
            req_id = core.new_req(user_id, request)
            core.add_file(req_id, file_id, file_name, type)

            bot.send_message(message.chat.id, f'✅ Ваш запрос под ID {req_id} создан. Посмотреть или продолжить диалог на текущих запросов можно нажав кнопку <b>Мои текущие запросы</b>', parse_mode='html', reply_markup=markup.markup_main())        
    
    #Если пользователь отправляет только текст
    else:
        if request == None:
            take_new_request = bot.send_message(message.chat.id, '⚠️ Отправляемый вами тип данных не поддерживается в боте. Попробуйте еще раз отправить ваш запрос, использовав один из доступных типов данных (текст, файлы, фото, видео, аудио, голосовые сообщения)', reply_markup=markup.markup_cancel())

            bot.clear_step_handler_by_chat_id(message.chat.id)
            bot.register_next_step_handler(take_new_request, get_new_request)

        elif request.lower() == 'отмена':
            bot.send_message(message.chat.id, 'Отменено.', reply_markup=markup.markup_main())
            return

        else:
            req_id = core.new_req(user_id, request)
            bot.send_message(message.chat.id, f'✅ Ваш запрос под ID {req_id} создан. Посмотреть текущие запросы можно нажав кнопку <b>Мои текущие запросы</b>', parse_mode='html', reply_markup=markup.markup_main())


def get_additional_message(message, req_id, status):
    additional_message = message.text
    check_file = core.get_file(message)
    
    #Если пользователь отправляет файл
    if check_file != None:
        file_id = check_file['file_id']
        file_name = check_file['file_name']
        type = check_file['type']
        additional_message = check_file['text']

        core.add_file(req_id, file_id, file_name, type)

    if additional_message == None:
        take_additional_message = bot.send_message(chat_id=message.chat.id, text='⚠️ Отправляемый вами тип данных не поддерживается в боте. Попробуйте еще раз отправить ваше сообщение, использовав один из доступных типов данных (текст, файлы, фото, видео, аудио, голосовые сообщения).', reply_markup=markup.markup_cancel())

        bot.clear_step_handler_by_chat_id(message.chat.id)
        bot.register_next_step_handler(take_additional_message, get_additional_message, req_id, status)

    elif additional_message.lower() == 'отмена':
        bot.send_message(message.chat.id, 'Отменено.', reply_markup=markup.markup_main())
        return

    else:
        if additional_message != 'None':
            core.add_message(req_id, additional_message, status)

        if check_file != None:
            if additional_message != 'None':
                text = '✅ Ваш файл и сообщение успешно отправлены!'
            else:
                text = '✅ Ваш файл успешно отправлен!'
        else:
            text = '✅ Ваше сообщение успешно отправлено!'
        
        if status == 'agent':
            bot.send_message(message.chat.id, text)
            manage_agent_buttons(message.chat.id, markup.markup_agent())
        else:
            bot.send_message(message.chat.id, text, reply_markup=markup.markup_main())

        if status == 'agent':
            user_id = core.get_user_id_of_req(req_id)
            try:
                if additional_message == 'None':
                    additional_message = ''

                bot.send_message(user_id, f'⚠️ Получен новый ответ на ваш запрос ID {req_id}!\n\n🧑‍💻 Ответ агента поддержки:\n{additional_message}', reply_markup=markup.markup_main())

                if type == 'photo':
                    bot.send_photo(user_id, photo=file_id, reply_markup=markup.markup_main())
                elif type == 'document':
                    bot.send_document(user_id, document=file_id, reply_markup=markup.markup_main())
                elif type == 'video':
                    bot.send_video(user_id, data=file_id, reply_markup=markup.markup_main())
                elif type == 'audio':
                    bot.send_audio(user_id, audio=file_id, reply_markup=markup.markup_main())
                elif type == 'voice':
                    bot.send_voice(user_id, voice=file_id, reply_markup=markup.markup_main())
                else:
                    bot.send_message(user_id, additional_message, reply_markup=markup.markup_main())
            except:
                pass
        

@bot.callback_query_handler(func=lambda call: True)
def callback_inline(call):
    user_id = call.message.chat.id

    if call.message:

        # === Секция «Мои запросы» и других списков запросов ===
        if call.data.startswith(('my_reqs:', 'waiting_reqs:', 'answered_reqs:', 'confirm_reqs:')):
            parts = call.data.split(':')
            mode, number = parts[0], parts[1]

            markup_req, value = markup.markup_reqs(user_id, mode, number)

            if value == 0:
                bot.answer_callback_query(call.id)
                return bot.send_message(user_id, '⚠️ Запросы не обнаружены.', reply_markup=markup.markup_main())

            text = 'Нажмите на запрос, чтобы посмотреть историю переписки, либо добавить сообщение:'

            # === Отменяем старый таймер ===
            if user_id in user_req_timers:
                user_req_timers[user_id].cancel()  # останавливаем старый таймер

            # === Пытаемся отредактировать старое сообщение ===
            if user_id in user_req_messages:
                try:
                    bot.edit_message_text(
                        chat_id=user_id,
                        message_id=user_req_messages[user_id],
                        text=text,
                        reply_markup=markup_req
                    )
                    msg_id = user_req_messages[user_id]
                except Exception as e:
                    # не удалось редактировать — удаляем и создаём новое
                    try:
                        bot.delete_message(user_id, user_req_messages[user_id])
                    except Exception as e:
                        print(f"Error deleting old message: {e}")
                    sent = button_mgr.send(user_id, text, reply_markup=markup_req)
                    msg_id = sent.message_id
            else:
                # первого раза нет старого — просто отправляем новое
                sent = button_mgr.send(user_id, text, reply_markup=markup_req)
                msg_id = sent.message_id

            # сохраняем ID сообщения
            user_req_messages[user_id] = msg_id

            def _del():
                try:
                    bot.delete_message(user_id, msg_id)
                    user_req_messages.pop(user_id, None)  # Удаляем запись о сообщении
                except Exception as e:
                    print(f"Error deleting message after timeout: {e}")
                finally:
                    user_req_timers.pop(user_id, None)  # Убираем таймер из словаря

            t = Timer(1800, _del)
            t.start()
            user_req_timers[user_id] = t

            bot.answer_callback_query(call.id)
            return

        # === Остальные ветки кода без изменений ===

        # Открыть запрос
        elif call.data.startswith('open_req:'):
            parts = call.data.split(':')
            req_id, callback = parts[1], parts[2]
            req_status = core.get_req_status(req_id)
            request_data = core.get_request_data(req_id, callback)
            for i, data in enumerate(request_data, start=1):
                last = (i == len(request_data))
                keyboard = markup.markup_request_action(req_id, req_status, callback) if last else None
                bot.send_message(user_id, data, parse_mode='html', reply_markup=keyboard)
            bot.answer_callback_query(call.id)

        # Добавить сообщение
        elif call.data.startswith('add_message:'):
            parts = call.data.split(':')
            req_id, status_user = parts[1], parts[2]
            msg = bot.send_message(user_id,
                                   'Отправьте ваше сообщение, использовав один из доступных типов данных (текст, файлы, фото, видео, аудио, голосовые сообщения)',
                                   reply_markup=markup.markup_cancel())
            bot.register_next_step_handler(msg, get_additional_message, req_id, status_user)
            bot.answer_callback_query(call.id)

        # Завершить запрос
        elif call.data.startswith('confirm_req:'):
            parts = call.data.split(':')
            confirm_status, req_id = parts[1], parts[2]
            if core.get_req_status(req_id) == 'confirm':
                bot.send_message(user_id, "⚠️ Этот запрос уже завершен.", reply_markup=markup.markup_main())
                return bot.answer_callback_query(call.id)
            if confirm_status == 'wait':
                button_mgr.send(user_id, "Для завершения запроса - нажмите кнопку <b>Подтвердить</b>",
                                 parse_mode='html', reply_markup=markup.markup_confirm_req(req_id))
            else:  # 'true'
                core.confirm_req(req_id)
                try:
                    bot.edit_message_text(user_id, call.message.message_id, "✅ Запрос успешно завершён.",
                                          reply_markup=markup.markup_main())
                except:
                    bot.send_message(user_id, "✅ Запрос успешно завершён.", reply_markup=markup.markup_main())
            bot.answer_callback_query(call.id)


        #Файлы запроса
        elif 'req_files:' in call.data:
            parts = call.data.split(':')
            req_id = parts[1]
            callback = parts[2]
            number = parts[3]

            markup_and_value = markup.markup_files(number, req_id, callback)
            markup_files = markup_and_value[0]
            value = markup_and_value[1]

            if value == 0:
                bot.send_message(chat_id=call.message.chat.id, text='⚠️ Файлы не обнаружены.', reply_markup=markup.markup_main())
                bot.answer_callback_query(call.id)
                return

            try:
                bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text='Нажмите на файл, чтобы получить его.', reply_markup=markup_files)
            except:
                button_mgr.send(chat_id=call.message.chat.id, text='Нажмите на файл, чтобы получить его.', reply_markup=markup_files)

            bot.answer_callback_query(call.id)

        #Отправить файл
        elif 'send_file:' in call.data:
            parts = call.data.split(':')
            id = parts[1]
            type = parts[2]

            file_id = core.get_file_id(id)

            if type == 'photo':
                bot.send_photo(call.message.chat.id, photo=file_id, reply_markup=markup.markup_main())
            elif type == 'document':
                bot.send_document(call.message.chat.id, document=file_id, reply_markup=markup.markup_main())
            elif type == 'video':
                bot.send_video(call.message.chat.id, data=file_id, reply_markup=markup.markup_main())
            elif type == 'audio':
                bot.send_audio(call.message.chat.id, audio=file_id, reply_markup=markup.markup_main())
            elif type == 'voice':
                bot.send_voice(call.message.chat.id, voice=file_id, reply_markup=markup.markup_main())
            
            bot.answer_callback_query(call.id)

        #Вернуться назад в панель агента
        elif call.data == 'back_agent':
            try:
                bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text='🔑 Вы авторизованы как Агент поддержки', parse_mode='html', reply_markup=markup.markup_agent())
            except:
                button_mgr.send(call.message.chat.id, '🔑 Вы авторизованы как Агент поддержки', parse_mode='html', reply_markup=markup.markup_agent())

            bot.answer_callback_query(call.id)

        #Вернуться назад в панель админа
        elif call.data == 'back_admin':
            try:
                bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text='🔑 Вы авторизованы как Админ', parse_mode='html', reply_markup=markup.markup_admin())
            except:
                button_mgr.send(call.message.chat.id, '🔑 Вы авторизованы как Админ', parse_mode='html', reply_markup=markup.markup_admin())

            bot.answer_callback_query(call.id)

        #Добавить агента
        elif call.data == 'add_agent':
            take_agent_id_message = bot.send_message(chat_id=call.message.chat.id, text='Чтобы добавить агента поддержки - введите его ID Telegram.', reply_markup=markup.markup_cancel())
            bot.register_next_step_handler(take_agent_id_message, get_agent_id_message)

        #Все агенты
        elif 'all_agents:' in call.data:
            number = call.data.split(':')[1]
            markup_and_value = markup.markup_agents(number)
            markup_agents = markup_and_value[0]
            len_agents = markup_and_value[1]

            if len_agents == 0:
                bot.send_message(chat_id=call.message.chat.id, text='⚠️ Агенты не обнаружены.', reply_markup=markup.markup_main())
                bot.answer_callback_query(call.id)
                return

            try:
                bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text='Нажмите на агента поддержки, чтобы удалить его', parse_mode='html', reply_markup=markup_agents)
            except:
                button_mgr.send(call.message.chat.id, 'Нажмите на агента поддержки, чтобы удалить его', parse_mode='html', reply_markup=markup_agents)

            bot.answer_callback_query(call.id)

        #Удалить агента
        elif 'delete_agent:' in call.data:
            agent_id = call.data.split(':')[1]
            core.delete_agent(agent_id)

            try:
                bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text='Нажмите на агента поддержки, чтобы удалить его', parse_mode='html', reply_markup=markup.markup_agents('1')[0])
            except:
                button_mgr.send(call.message.chat.id, 'Нажмите на агента поддержки, чтобы удалить его', parse_mode='html', reply_markup=markup.markup_agents('1')[0])

            bot.answer_callback_query(call.id)

        #Все пароли
        elif 'all_passwords:' in call.data:
            number = call.data.split(':')[1]
            markup_and_value = markup.markup_passwords(number)
            markup_passwords = markup_and_value[0]
            len_passwords = markup_and_value[1]

            if len_passwords == 0:
                bot.send_message(chat_id=call.message.chat.id, text='⚠️ Пароли не обнаружены.', reply_markup=markup.markup_main())
                bot.answer_callback_query(call.id)
                return

            try:
                bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text='Нажмите на пароль, чтобы удалить его', parse_mode='html', reply_markup=markup_passwords)
            except:
                button_mgr.send(call.message.chat.id, 'Нажмите на пароль, чтобы удалить его', parse_mode='html', reply_markup=markup_passwords)

            bot.answer_callback_query(call.id)

        #Удалить пароль
        elif 'delete_password:' in call.data:
            password = call.data.split(':')[1]
            core.delete_password(password)

            try:
                bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text='Нажмите на пароль, чтобы удалить его', parse_mode='html', reply_markup=markup.markup_passwords('1')[0])
            except:
                button_mgr.send(call.message.chat.id, 'Нажмите на пароль, чтобы удалить его', parse_mode='html', reply_markup=markup.markup_passwords('1')[0])

            bot.answer_callback_query(call.id)

        #Сгенерировать пароли
        
        elif call.data == 'generate_passwords':
            #10 - количество паролей, 16 - длина пароля
            passwords = core.generate_passwords(10, 16) 
            core.add_passwords(passwords)

            text_passwords = ''
            i = 1
            for password in passwords:
                text_passwords += f'{i}. {password}\n'
                i += 1
            
            bot.send_message(call.message.chat.id, f"✅ Сгенерировано {i-1} паролей:\n\n{text_passwords}", parse_mode='html', reply_markup=markup.markup_main())
            button_mgr.send(call.message.chat.id, 'Нажмите на пароль, чтобы удалить его', parse_mode='html', reply_markup=markup.markup_passwords('1')[0])

            bot.answer_callback_query(call.id)
        
        #Остановить бота
        elif 'stop_bot:' in call.data:
            status = call.data.split(':')[1]

            #Запросить подтверждение на отключение
            if status == 'wait':
                try:
                    bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=f"Вы точно хотите отключить бота?", parse_mode='html', reply_markup=markup.markup_confirm_stop())
                except:
                    button_mgr.send(call.message.chat.id, f"Вы точно хотите отключить бота?", parse_mode='html', reply_markup=markup.markup_confirm_stop())

            #Подтверждение получено
            elif status == 'confirm':
                try:
                    bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text='✅ Бот оключен.')
                except:
                    bot.send_message(chat_id=call.message.chat.id, text='✅ Бот оключен.')

                bot.answer_callback_query(call.id)
                bot.stop_polling()
                sys.exit()


if __name__ == "__main__":
    bot.polling(none_stop=True)