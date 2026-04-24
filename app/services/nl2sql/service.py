import logging
from pathlib import Path

from app.core.interface.llm import BaseLLM
from app.services.nl2sql.executor import execute_readonly_sql
from app.services.nl2sql.security import sanitize_nl_input, validate_generated_sql
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

logger = logging.getLogger(__name__)

MAX_RAW_ROWS = 100

TABLE_SCHEMA = """
CREATE TABLE features (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id  TEXT NOT NULL,
    competitor_name TEXT NOT NULL,
    feature_name TEXT NOT NULL,
    price REAL, -- float atau NULL. Harga dalam USD.
    advantages TEXT, -- Kelebihan, metrik positif
    disadvantages TEXT -- Kelemahan, metrik menurun
);
"""

_PROMPT_DIR = Path(__file__).resolve().parent.parent.parent.parent / "prompts"


def _load_prompt(filename: str) -> str:
    path = _PROMPT_DIR / filename
    try:
        content = path.read_text(encoding="utf-8")
        return content
    except FileNotFoundError:
        raise FileNotFoundError



_SQL_PROMPT_TEXT = _load_prompt("nl2sql_generator.md")
_ANSWER_PROMPT_TEXT = _load_prompt("nl2sql_answer.md")


class NL2SQLService:
    def __init__(self, llm_provider: BaseLLM):
        """
        Inisialisasi service menggunakan Dependency Injection.
        llm_provider disuntikkan dari luar (Factory), service ini tidak peduli 
        apakah itu OpenAI, Anthropic, atau model lokal.
        """

        self.llm = llm_provider.get_client()

        self.sql_prompt = ChatPromptTemplate.from_messages([
            ("system", _SQL_PROMPT_TEXT),
            ("human", "{question}")
        ])

        self.answer_prompt = ChatPromptTemplate.from_messages([
            ("system", _ANSWER_PROMPT_TEXT),
            ("human", "Pertanyaan: {question}\nData SQL: {data}")
        ])

        self.sql_chain = self.sql_prompt | self.llm | StrOutputParser()
        self.answer_chain = self.answer_prompt | self.llm | StrOutputParser()

    async def process_query(self, user_question: str) -> dict:
        try:
            safe_question = sanitize_nl_input(user_question)

            raw_sql = await self.sql_chain.ainvoke({
                "schema": TABLE_SCHEMA,
                "question": safe_question
            })

            if raw_sql.strip().upper() == "INVALID_QUESTION":
                return {
                    "status": "success",
                    "answer": "Pertanyaan tidak relevan dengan database intelijen kompetitor atau tidak dapat dijawab "
                              "dengan data yang tersedia.",
                    "sql_query": None,
                    "raw_data": None
                }

            clean_sql = raw_sql.replace("```sql", "").replace("```", "").strip()

            validated_sql = validate_generated_sql(clean_sql)

            query_results = execute_readonly_sql(validated_sql)

            is_truncated = len(query_results) > MAX_RAW_ROWS
            limited_results = query_results[:MAX_RAW_ROWS]

            final_answer = await self.answer_chain.ainvoke({
                "question": safe_question,
                "data": str(limited_results)
            })

            return {
                "status": "success",
                "sql_query": validated_sql,
                "raw_data": limited_results,
                "row_count": len(query_results),
                "truncated": is_truncated,
                "answer": final_answer
            }

        except ValueError as ve:
            return {
                "status": "error",
                "message": str(ve)
            }

        except Exception:
            return {
                "status": "error",
                "message": "Terjadi kesalahan sistem saat memproses pertanyaan."
            }
