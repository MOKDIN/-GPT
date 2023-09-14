import os
import asyncio
import openai
import json
from threading import Thread
from threading import Lock
import sys
from pythonjsonlogger import jsonlogger
import logging
import queue

with open('faq.json', 'r') as f:
    FAQ = json.load(f)

OPENAI_API_KEY = ''
openai.api_key = OPENAI_API_KEY

# Создаем массив для хранения запросов пользователя и ответов чата GPT
chat_responses = {}
chat_responses_lock = Lock()
requests_queue = queue.Queue()
message_queue = queue.Queue()

class YcLoggingFormatter(jsonlogger.JsonFormatter):
    def add_fields(self, log_record, record, message_dict):
        super(YcLoggingFormatter, self).add_fields(log_record, record, message_dict)
        log_record['logger'] = record.name
        log_record['level'] = str.replace(str.replace(record.levelname, "WARNING", "WARN"), "CRITICAL", "FATAL")


logHandler = logging.StreamHandler()
logHandler.setFormatter(YcLoggingFormatter('%(message)s %(level)s %(logger)s'))

logger = logging.getLogger('MyLogger')
logger.propagate = False
logger.addHandler(logHandler)
logger.setLevel(logging.DEBUG)


async def ai(prompt, prev_messages=None, temperature=0.1, max_tokens=240):
    if prev_messages is None:
        prev_messages = []

    # Add the user's message to the list of previous messages
    prev_messages.append({"role": "user", "content": prompt})

    try:
        completion = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=prev_messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        return completion.choices[0].message.content
    except Exception as e:
        print(f"Error in ai function: {e}")
        logging.error(f"Error in ai function: {e}")
        return {"error": f"Error in ai function with prompt: {prompt}. Exception: {e}"}


async def aquery(message, prev_messages=None):
    return await ai(message, prev_messages)


def process_chat_response(session_id, original_utterance, prev_messages):
    logger.info("Starting generation process...",
                extra={"session_id": session_id, "original_utterance": original_utterance})
    is_generating = True
    try:
        reply = asyncio.run(aquery(original_utterance, prev_messages))
        logger.info(f"Generated reply: {reply}",
                    extra={"session_id": session_id, "original_utterance": original_utterance})
        with chat_responses_lock:
            chat_responses[session_id] = {"user_query": original_utterance, "assistant_message": reply,
                                          "is_generating": False}
        logger.info(f"Saved reply in chat_responses under session_id {session_id}",
                    extra={"session_id": session_id, "original_utterance": original_utterance})
    except Exception as e:
        logger.error(f"Exception during chat response processing: {e}",
                     extra={"session_id": session_id, "original_utterance": original_utterance})
        return


def handle_request(event, context):
    response = {
        "version": event["version"],
        "session": event["session"],
        "response": {
            "end_session": False
        }
    }

    session_id = event["session"]["session_id"]
    prev_messages = event.get("state", {}).get("user", {}).get(session_id, [])

    original_utterance = event["request"].get("original_utterance", "").strip()
    button_action = event["request"].get("payload", {}).get("button_action")

    # Если пользователь нажал кнопку "Получить ответ" или ввел команду "Получить ответ"
    if original_utterance.lower() == "получить ответ" or button_action == "получить ответ":
        with chat_responses_lock:
            last_chat_response = chat_responses.get(session_id)
        if last_chat_response and "assistant_message" in last_chat_response:
           response["response"]["text"] = last_chat_response["assistant_message"]
           try:
                with chat_responses_lock:
                    del chat_responses[session_id]  # remove the response after it's been sent
           except KeyError:
                logger.error(f"No chat response found for session ID {session_id}")
        else:
            response["response"]["text"] = "Ваш запрос в обработке ИИ подождите немного..потом скажите или напишите в чат получить ответ ."
        return response

    if event["session"]["new"]:
        welcome_message = "Здравствуйте, вас приветствует искусственный интеллект."
        prev_messages.append({"role": "assistant", "content": welcome_message})
        response["response"]["text"] = welcome_message
        return response

    if original_utterance.lower() in FAQ:
        reply = FAQ[original_utterance.lower()]
        prev_messages.append({"role": "assistant", "content": reply})
        response["state"] = {
            "user": {
                session_id: prev_messages
            }
        }
        response["response"]["text"] = reply
    else:
        # Проверяем наличие сгенерированного ответа
        with chat_responses_lock:
            last_chat_response = chat_responses.get(session_id)
        if last_chat_response and "assistant_message" in last_chat_response:
            # Проверяем, не является ли сгенерированный ответ повторным
            last_message = prev_messages[-1]["content"] if prev_messages else ""
            if last_message != last_chat_response["assistant_message"]:
                response["response"]["text"] = last_chat_response["assistant_message"]
        else:
        # Place the request in the queue for the background thread to process
            requests_queue.put((session_id, original_utterance, prev_messages))
            logger.info("Запущен процесс обработки запроса", extra={"session_id": session_id, "original_utterance": original_utterance})
            response["response"]["text"] = "Ваш запрос обрабатывается. Пожалуйста, подождите около 5 секунд, потом нажмите кнопку или произнесите фразу'Получить ответ'."



            # Создаем кнопку "Получить ответ"
            response["response"]["buttons"] = [
                {
                    "title": "получить ответ",
                    "payload": {
                        "button_action": "получить ответ"
                    },
                    "hide": True
                }
            ]

    return response








def process_requests():
    while True:
        session_id, original_utterance, prev_messages = requests_queue.get()
        process_chat_response(session_id, original_utterance, prev_messages)

        logger.info("Processed request from queue",
                    extra={"session_id": session_id, "original_utterance": original_utterance})

# Start the background thread that processes requests
thread = Thread(target=process_requests)
thread.start()





def handle_get_answer(event, context):
    session_id = event["session"]["session_id"]
    with chat_responses_lock:
        last_chat_response = chat_responses.get(session_id)

    response = {
        "version": event["version"],
        "session": event["session"],
        "response": {
            "end_session": False
        }
    }

    button_title = event["request"].get("payload", {}).get("button", {}).get("title")
    if button_title == "Получить ответ":
        if last_chat_response and "assistant_message" in last_chat_response:
            response["response"]["text"] = last_chat_response["assistant_message"]
        else:
            response["response"]["text"] = "Ответ не найден"
    else:
        response["response"]["text"] = "Неизвестная команда"

    return response


