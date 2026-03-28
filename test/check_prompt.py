import logging

# Nyalakan logger dulu
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
)

# Import variabel prompt dari service Anda
from app.services.extraction.service import _SYSTEM_PROMPT, _PROMPT_PATH

print("\n" + "="*50)
print(f"LOKASI FILE PROMPT: {_PROMPT_PATH}")
print("="*50)

print("\n=== ISI PROMPT YANG BENAR-BENAR MASUK KE AGEN ===")
print(_SYSTEM_PROMPT)
print("=================================================\n")