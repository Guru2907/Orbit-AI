from google import genai
from google.genai import types
from app.config import GEMINI_API_KEY, LLM_MODEL
from app.prompts import SYSTEM_PROMPT
from app.rag import retrieve_relevant_chunks, get_unique_sources

NO_INFO_MESSAGE = "I don't have that information in our support documents. Please contact support@flowspace.example.com for further help."

client = genai.Client(api_key=GEMINI_API_KEY)

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
    chunks = retrieve_relevant_chunks(question=question)
    if not chunks:
        return {"answer": NO_INFO_MESSAGE, "sources": []}
    
    context_string = build_context(chunks=chunks)
    final_prompt = build_prompt(question=question,context_string=context_string)

    llm_response = client.models.generate_content(
    model=LLM_MODEL,
    contents=final_prompt,
    config=types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        temperature=0.2)
    )

    llm_text = llm_response.text
    unique_sources = get_unique_sources(chunks)

    if llm_text.strip() == NO_INFO_MESSAGE:
        unique_sources = []
        
    final_output = {"answer": llm_text, "sources": unique_sources}

    return final_output