import sys
import os
from langchain_pymupdf4llm import PyMuPDF4LLMLoader
from .settings import settings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_chroma import Chroma
from .config import embeddings
import chromadb

root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.append(root_dir)
api_key = settings.PROXY_API_KEY
CHROMA_PERSIST_DIR = "C:/Projects/LLM_AGENTS_COURSE/src/SPWS/src/DB/chroma_db"


def _col(uid): return f"user_collection_{uid}"


def user_has_pdf(user_id: str) -> bool:
    try:
        return chromadb.PersistentClient(
            path=CHROMA_PERSIST_DIR
            ).get_collection(
                _col(user_id)
                ).count() > 0
    except Exception:
        return False


def delete_user_pdf(user_id: str) -> None:
    try:
        chromadb.PersistentClient(
            path=CHROMA_PERSIST_DIR
            ).delete_collection(
                _col(user_id)
                )
    except Exception:
        pass


def create_vectore_db_for_user(file_path: str, user_id: str):
    loader = PyMuPDF4LLMLoader(
        file_path=file_path,
        mode="single",
        pages_delimiter="\n\f"
    )
    docs = loader.load()
    # print(docs)
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=800, chunk_overlap=100
        )

    all_chunks = text_splitter.split_documents(docs)
    print(f"Number of chunks: {len(all_chunks)}")

    collection_name = f"user_collection_{user_id}"

    Chroma.from_documents(
        documents=all_chunks,
        embedding=embeddings,
        persist_directory=CHROMA_PERSIST_DIR,
        collection_name=collection_name
    )

    # if os.path.exists(file_path):
    #     os.remove(file_path)

    print(f" DB for user {user_id} was created at {CHROMA_PERSIST_DIR}")
