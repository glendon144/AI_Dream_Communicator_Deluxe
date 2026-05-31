# tools/smoke_ai.py
import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from modules.ai_adapter import AIInterface

ai = AIInterface(provider="openai")
print("Provider:", ai.get_provider())
print("ASK:", ai.ask("Give me a seven-word greeting."))

