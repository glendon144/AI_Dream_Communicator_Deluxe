# AI Dream Communicator

AI Dream Communicator is the suite shell for three sibling products:

- `ai_navigator/` - Qt6/PySide6 browser and cognitive instrument.
- `PiKit/` - OPML and knowledge organization mode.
- `FunKit/` - AI query and LLM interaction mode.

The current shell lives in `ai_navigator/ai_navigator.py`. It launches AI Navigator as the default product mode and provides PiKit and FunKit launch tabs that start those sibling applications as separate processes.

Future work will add a Dream Capsule substrate for shared memory across the suite. That server/protocol layer is not implemented in this initial shell snapshot.

## Run

```bash
cd ai_navigator
source ~/.venvs/ai_navigator/bin/activate
python ai_navigator.py
```

The launch tabs prefer `~/.venvs/ai_communicator` when it exists. Until the products are fully refactored around one shared environment, they fall back to:

- PiKit: `~/.venvs/pikit`
- FunKit: `~/.venvs/funkit`
