import os
import asyncio
import openai
import json

with open('faq.json', 'r') as f:
    FAQ = json.load(f)


OPENAI_API_KEY = ''
openai.api_key = OPENAI_API_KEY

async def ai(prompt, prev_messages=None, temperature=0.2, max_tokens=200):
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
        logging.error(f"Error in ai function: {e}")
        return None


async def aquery(message, prev_messages=None):
    return await ai(message)

async def handle_request(event, context):
    response = {
        "version": event["version"],
        "session": event["session"],
        "response": {
            "end_session": False
        }
    }

    # Retrieve previous messages from the user state
    prev_messages = event["state"].get("user", {}).get("prev_messages", [])

    if event["session"]["new"]:
        welcome_message = "Здравствуйте, вас приветствует искусственный интеллект"
        prev_messages.append({"role": "assistant", "content": welcome_message})
        response["response"]["text"] = welcome_message
        return response

    original_utterance = event["request"]["original_utterance"].strip()

    # Проверяем, есть ли вопрос пользователя в списке часто задаваемых вопросов
    if original_utterance.lower() in FAQ:
        reply = FAQ[original_utterance.lower()]
    else:
        # Если вопрос не найден в списке, используем модель GPT-3.5-turbo для получения ответа
        reply = await ai(original_utterance, prev_messages)

    prev_messages.append({"role": "assistant", "content": reply})
    response["state"] = {
        "user": {
            "prev_messages": prev_messages
        }
    }

    response["response"]["text"] = reply
    return response

