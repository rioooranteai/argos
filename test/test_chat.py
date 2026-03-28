import asyncio
import logging

# Nyalakan logger
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)

# IMPORT YANG BENAR: Bawa Factory dan Service-nya
from app.services.shared.factories.llm_factory import get_llm
from app.services.nl2sql.service import NL2SQLService

async def interactive_chat():
    print("="*60)
    print("🤖 ARGOS NL2SQL TERMINAL CHAT 🤖")
    print("Ketik 'exit' atau 'keluar' untuk berhenti.")
    print("="*60)

    # 1. MINTA MESIN DARI PABRIK (FACTORY)
    logger.info("Memesan mesin AI dari Factory...")
    my_llm_provider = get_llm(model_type="extraction", temperature=0.0)

    # 2. SUNTIKKAN MESIN KE DALAM SERVICE (Dependency Injection)
    logger.info("Menyuntikkan mesin ke dalam NL2SQL Service...")
    nl2sql_svc = NL2SQLService(llm_provider=my_llm_provider)

    print("Mesin siap! Silakan bertanya tentang data kompetitor Anda.\n")

    while True:
        # Minta input dari user
        user_input = input("\n🧑 Anda: ")
        
        if user_input.lower() in ['exit', 'keluar', 'quit']:
            print("👋 Sampai jumpa!")
            break
            
        if not user_input.strip():
            continue

        print("🤖 Asisten sedang berpikir (Menerjemahkan ke SQL & Mencari Data)...")
        
        # Proses pertanyaan
        result = await nl2sql_svc.process_query(user_input)
        
        # Tampilkan Hasil
        print("-" * 60)
        if result.get("status") == "success":
            # Tampilkan SQL yang digenerate (untuk debugging)
            if result.get("sql_query"):
                print(f"🔍 [DEBUG] Generated SQL : {result.get('sql_query')}")
                print(f"📊 [DEBUG] Baris Data   : {result.get('row_count')} baris ditemukan")
            
            # Tampilkan Jawaban Final
            print(f"\n💡 Jawaban AI:\n{result.get('answer')}")
            
        else:
            # Tampilkan pesan error (biasanya karena ditolak oleh security filter)
            print(f"⛔ DITOLAK: {result.get('message')}")
        print("-" * 60)

if __name__ == "__main__":
    # Jalankan loop asinkron
    asyncio.run(interactive_chat())