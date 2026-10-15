import httpx
from chromadb.errors import ChromaError
from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from app.config import GEMINI_API_KEY, LLM_MODEL
from app.prompts import SYSTEM_PROMPT
from app.rag import retrieve_relevant_chunks, get_unique_sources

NO_INFO_MESSAGE = "I don't have that information in our support documents. Please contact support@flowspace.example.com for further help."

# Quote characters the model sometimes wraps around the fallback sentence.
FALLBACK_QUOTES = "\"'“”‘’"

client = genai.Client(api_key=GEMINI_API_KEY)


class AnswerUnavailableError(Exception):
    """An upstream service (Gemini or Chroma) failed, so no answer could be produced."""


def is_service_error(error):
    """
    True for failures of the external services, not for bugs in our own code.
    Chroma raises a bare `Exception(response_text)` for HTTP errors it has no specific
    class for, so that exact type counts too — but none of its subclasses (TypeError, ...).
    """
    if isinstance(error, (genai_errors.APIError, ChromaError, httpx.TransportError)):
        return True
    return type(error) is Exception


def log_service_error(stage, error):
    """Logs which stage failed and why, without the user's question or any response body."""
    status = getattr(error, "code", None)
    status_text = f" (status {status})" if isinstance(status, int) else ""
    print(f"Upstream service error: {stage} failed with {type(error).__name__}{status_text}.")


def is_fallback(text):
    return text.strip().strip(FALLBACK_QUOTES).strip() == NO_INFO_MESSAGE


def build_context(chunks):
    context_list = []
    for chunk in chunks:
        piece = f"<context>\nSource: {chunk['source']}\n{chunk['text']}\n</context>"
        context_list.append(piece)
    context_string = "\n\n".join(context_list)
    return context_string

def build_prompt(question, context_string):
    final_prompt = f"{context_string}\nQuestion: {question}"
    return final_prompt

def generate_answer(question):
    try:
        chunks = retrieve_relevant_chunks(question=question)
    except Exception as error:
        if not is_service_error(error):
            raise
        log_service_error("retrieval", error)
        raise AnswerUnavailableError() from error

    if not chunks:
        return {"answer": NO_INFO_MESSAGE, "sources": []}

    context_string = build_context(chunks=chunks)
    final_prompt = build_prompt(question=question,context_string=context_string)

    try:
        llm_response = client.models.generate_content(
        model=LLM_MODEL,
        contents=final_prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=0.2)
        )
    except Exception as error:
        if not is_service_error(error):
            raise
        log_service_error("generation", error)
        raise AnswerUnavailableError() from error

    # .text is None when the response was blocked or has no text parts.
    llm_text = llm_response.text or ""
    if not llm_text.strip() or is_fallback(llm_text):
        return {"answer": NO_INFO_MESSAGE, "sources": []}

    unique_sources = get_unique_sources(chunks)
    final_output = {"answer": llm_text, "sources": unique_sources}

    return final_output
