import sys
import os

root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(root_dir)
from langchain_openai import ChatOpenAI
# from langchain_anthropic import ChatAnthropic
from langchain.chat_models import init_chat_model
from .settings import settings
from langchain_openai import OpenAIEmbeddings
import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
# Получение API-ключа из настроек
api_key = settings.PROXY_API_KEY
embeddings =  OpenAIEmbeddings(
      base_url='https://api.proxyapi.ru/openai/v1',  # URL для доступа к OpenAI через Proxy API
      api_key=api_key,  # Ваш API-ключ
)

llm_for_start = ChatOpenAI(
    model="gpt-4o-mini",
    api_key=settings.PROXY_API_KEY,
    temperature=0.1,
    base_url="https://api.proxyapi.ru/openai/v1"
)

llm_topics_human_in_the_loop = ChatOpenAI(
    model='gpt-4o',  # Указываем модель
    base_url='https://api.proxyapi.ru/openai/v1',  # URL для доступа к OpenAI через Proxy API  # Параметр температуры для генерации текста
    api_key=api_key  # Ваш API-ключ
)

llm_reasonings = init_chat_model(
    model='qwen/qwen3.8-omni-flash',
    base_url='https://api.proxyapi.ru/openrouter/v1',
    api_key=api_key,
    model_provider='openai',
)


llm_answers_final_response = ChatOpenAI(
    model='gpt-4o',  # Указываем модель
    base_url='https://api.proxyapi.ru/openai/v1',  # URL для доступа к OpenAI через Proxy API
    temperature=0,  # Параметр температуры для генерации текста
    api_key=api_key  # Ваш API-ключ
)


# llm_local = init_chat_model(
#     model="qwen2.5:3b",
#     base_url="http://localhost:11434/v1",
#     api_key="OpenAI compatibility",
#     model_provider="openai",
# )

