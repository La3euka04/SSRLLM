import sys
import os
root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.append(root_dir)
from langchain_pymupdf4llm import PyMuPDF4LLMLoader
from langchain_community.document_loaders.parsers import LLMImageBlobParser
from langchain_openai import ChatOpenAI
from src.settings import settings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_chroma import Chroma
from config import embeddings
from tools import multiply, sum_, divide, web_search, search_wikipedia, search_scientific_papers, fetch_web_page_content, search_through_users_pdf


api_key = settings.PROXY_API_KEY
CHROMA_PERSIST_DIR = "./chroma_db"

def create_vectore_db_for_user(file_path: str, user_id: str):

    loader = PyMuPDF4LLMLoader(
        file_path=r"C:\Projects\LLM_AGENTS_COURSE\src\RAG_task\russian_pdd.pdf", ???????
        mode="single",
        pages_delimiter="\n\f"
    )

    docs = loader.load()
    # print(docs)
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=100)

    all_chunks = text_splitter.split_documents(docs)
    print(f"Создано чанков: {len(all_chunks)}")

    collection_name = f"user_collection_{user_id}"

    vectorstore = Chroma.from_documents(
        documents=all_chunks,
        embedding=embeddings,  # Передаем напрямую, без всяких кэш-оберток
        persist_directory=CHROMA_PERSIST_DIR,
        collection_name=collection_name
    )
    
    # 6. Удаляем временный исходный PDF-файл, так как он больше не нужен
    if os.path.exists(file_path):
        os.remove(file_path)

    print(f"✅ База данных для пользователя {user_id} создана в папке {CHROMA_PERSIST_DIR}")