from langchain_tavily import TavilySearch
import sys
import os
from langchain_community.document_loaders import WikipediaLoader
from langchain_community.utilities import ArxivAPIWrapper
from langchain_chroma import Chroma
import requests
from bs4 import BeautifulSoup
root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.append(root_dir)
from src.settings import settings
from langchain_core.tools import tool
from config import embeddings
from typing import Annotated
from langgraph.prebuilt import InjectedState


if not os.environ.get("TAVILY_API_KEY"):
    os.environ["TAVILY_API_KEY"] = settings.TAVILY_API_KEY


@tool
def multiply(a: float, b: float) -> float:
    """Multiply of two numbers. Returns the multiplication"""
    return a * b


@tool
def sum_(a: float, b: float) -> float:
    """Sum or subtraction of two numbers. make the second unput number with minus '-' to get subtract. Returns the sum or subtraction if minus was set."""
    return a + b


@tool
def divide(a: float, b: float) -> float:
    """Divide two numbers. Returns the division"""
    if b == 0:
         return 'Not possible to divide by zero'
    return a/b


@tool
def web_search(query: str):
    """Make the web-search for the information for a given query and returns 5 relevant texts"""
    tavily_search = TavilySearch(max_results=5, tavily_api_key=settings.TAVILY_API_KEY)
    search_docs = tavily_search.invoke(query)
    docs = search_docs['results']
    formatted_search_docs = "\n\n---\n\n".join(
        [
            f'<Document href="{doc["url"]}">\n{doc["content"]}\n</Document>'
            for doc in docs
        ]
    )
    return formatted_search_docs


@tool
def search_wikipedia(query: str, lang: str):
    """Make the wikipedia_search for the information for a given query and returns 5 relevant texts"""

    search_docs = WikipediaLoader(query, load_max_docs=5, lang=lang).load()
    # Форматирование
    formatted_search_docs = "\n\n---\n\n".join(
        [
            f'<Document source="{doc.metadata["source"]}" page="{doc.metadata.get("title", "")}">\n{doc.page_content}\n</Document>'
            for doc in search_docs
        ]
    )
    return formatted_search_docs


@tool
def search_scientific_papers(query: str) -> str:
    """Search for scientific papers in Arxiv. Returns 5 documents per request"""
    arxiv = ArxivAPIWrapper(top_k_results=5, doc_content_chars_max=5000)
    return arxiv.run(query)


@tool
def fetch_web_page_content(url: str) -> str:
    """Extracts and strips all information from all text content on a specific web page (required correct URL)."""
    try:
        response = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        soup = BeautifulSoup(response.text, "html.parser")
        # Удаляем скрипты и стили
        for script in soup(["script", "style"]):
            script.extract()
        text = soup.get_text(separator="\n")
        return "\n".join([line.strip() for line in text.splitlines() if line.strip()])[:5000]
    except Exception as e:
        return f"failed to load a page: {str(e)}"


@tool
def search_through_users_pdf(
    question: str,
    user_id: Annotated[str, InjectedState("user_id")],
) -> str:
    """Retrieve information from the user's chunked pdf. Returns up to 10 chunks."""
    vectorstore = Chroma(
        persist_directory="./chroma_db",
        embedding_function=embeddings,
        collection_name=f"user_collection_{user_id}",
    )
    retriever = vectorstore.as_retriever(
        search_type="mmr",
        search_kwargs={"k": 10, "fetch_k": 20, "lambda_mult": 0.67},
    )
    relevant_chunks = retriever.invoke(question)
    return "\n\n".join(doc.page_content for doc in relevant_chunks)
