#!/usr/bin/env bash
set -euo pipefail

FILE="modules/ai_interface.py"

# backup
cp -f "$FILE" "$FILE.bak.$(date +%Y%m%d%H%M%S)"

# Insert the wrapper methods right before the last line of the class
# (assumes AIInterface is defined and ends with an indented 'def chat' or similar)
tmpfile=$(mktemp)

awk '
  /^class AIInterface/ { inclass=1 }
  inclass && /^}/ { inclass=0 }
  { print }
  /def chat/ { lastchat=NR }
  END {
    if (lastchat) {
      # after printing everything, append the patch at the end of the file
      print "    # ---- Back-compat convenience wrappers ----"
      print "    def query(self, prompt: str, *, system: str = \"You are a helpful assistant.\", max_tokens: int = 512, temperature: float = 0.7) -> str:"
      print "        \"\"\"Legacy FunKit/DemoKit style: ai.query(\"...\"). Routes to chat() under the hood.\"\"\""
      print "        messages = ["
      print "            {\"role\": \"system\", \"content\": system},"
      print "            {\"role\": \"user\", \"content\": prompt},"
      print "        ]"
      print "        return self.chat(messages, temperature=temperature, max_tokens=max_tokens)"
      print ""
      print "    def complete(self, prompt: str, *, max_tokens: int = 512, temperature: float = 0.7) -> str:"
      print "        \"\"\"Another common legacy alias some modules used. Equivalent to query() with a generic system prompt.\"\"\""
      print "        return self.query(prompt, system=\"You are a helpful assistant.\", max_tokens=max_tokens, temperature=temperature)"
    }
  }
' "$FILE" > "$tmpfile"

mv "$tmpfile" "$FILE"

echo "✅ Patch applied to $FILE"
echo "   Backup saved as $FILE.bak.<timestamp>"

