import logging
from pathlib import Path

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

from app.services.shared.base.llm import BaseLLM
from app.services.nl2sql.security import sanitize_nl_input, validate_generated_sql
from app.services.nl2sql.executor import execute_readonly_sql

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

def _load_prompt(filename: str, fallback_text: str) -> str:
    path = _PROMPT_DIR / filename
    try:
        content = path.read_text(encoding="utf-8")
        logger.info(f"✅ SUKSES memuat Prompt dari: {path.name}")
        return content
    except FileNotFoundError:
        logger.warning(f"⚠️ GAGAL menemukan {filename}. Menggunakan fallback.")
        return fallback_text

_SQL_PROMPT_TEXT = _load_prompt("nl2sql_generator.md", "Kamu adalah asisten pengubah Natural Language menjadi SQLite query. Gunakan schema:\n{schema}")
_ANSWER_PROMPT_TEXT = _load_prompt("nl2sql_answer.md", "Kamu analis data. Jawab berdasarkan data ini saja. Jangan mengarang.")

class NL2SQLService:
    def __init__(self, llm_provider: BaseLLM):
        """
        Inisialisasi service menggunakan Dependency Injection.
        llm_provider disuntikkan dari luar (Factory), service ini tidak peduli 
        apakah itu OpenAI, Anthropic, atau model lokal.
        """
        # Kita ambil objek LangChain asli (native client) dari provider
        # agar sintaks piping (|) LCEL tetap berfungsi
        self.llm = llm_provider.get_client()

        # Prompt 1: Natural Language → SQL
        self.sql_prompt = ChatPromptTemplate.from_messages([
            ("system", _SQL_PROMPT_TEXT),
            ("human", "{question}")
        ])

        # Prompt 2: Data SQL → Jawaban Natural Language
        self.answer_prompt = ChatPromptTemplate.from_messages([
            ("system", _ANSWER_PROMPT_TEXT),
            ("human", "Pertanyaan: {question}\nData SQL: {data}")
        ])

        # Merakit Chain LCEL LangChain
        self.sql_chain = self.sql_prompt | self.llm | StrOutputParser()
        self.answer_chain = self.answer_prompt | self.llm | StrOutputParser()

    async def process_query(self, user_question: str) -> dict:
        try:
            # LAPISAN 1: Sanitasi input (Mencegah Prompt Injection)
            safe_question = sanitize_nl_input(user_question)
            logger.info(f"Menerima pertanyaan NL2SQL (sanitized): '{safe_question}'")

            # TAHAP A: LLM generate SQL
            raw_sql = await self.sql_chain.ainvoke({
                "schema": TABLE_SCHEMA,
                "question": safe_question
            })

            # Tangani respons penolakan dari LLM (Out of Scope)
            if raw_sql.strip().upper() == "INVALID_QUESTION":
                logger.info("Pertanyaan ditolak sebagai INVALID_QUESTION oleh LLM.")
                return {
                    "status": "success",
                    "answer": "Pertanyaan tidak relevan dengan database intelijen kompetitor atau tidak dapat dijawab dengan data yang tersedia.",
                    "sql_query": None,
                    "raw_data": None
                }

            # Bersihkan markdown bawaan LLM (```sql ... ```)
            clean_sql = raw_sql.replace("```sql", "").replace("```", "").strip()

            # LAPISAN 2: Validasi SQL (Harus SELECT, tidak boleh DROP/DELETE)
            validated_sql = validate_generated_sql(clean_sql)

            # LAPISAN 3: Eksekusi SQL di database (Read-Only)
            query_results = execute_readonly_sql(validated_sql)

            # Batasi jumlah data mentah yang dikirim ke LLM dan UI agar tidak memakan token
            is_truncated = len(query_results) > MAX_RAW_ROWS
            limited_results = query_results[:MAX_RAW_ROWS]

            # TAHAP B: LLM merangkum hasil SQL menjadi jawaban bahasa manusia
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
            # Error yang sengaja dilempar oleh fungsi security
            logger.warning(f"Diblokir oleh sistem keamanan: {str(ve)}")
            return {
                "status": "error",
                "message": str(ve)
            }

        except Exception:
            # Error sistem yang tidak terduga, log disembunyikan untuk mencegah kebocoran data
            logger.error("Kegagalan sistem NL2SQL", exc_info=True)
            return {
                "status": "error",
                "message": "Terjadi kesalahan sistem saat memproses pertanyaan."
            }