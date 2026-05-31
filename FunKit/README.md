# FunKit

FunKit is a **document-centered interactive environment** for exploring ideas with AI.

It is not just a thin API wrapper. FunKit combines:
- a **Tk GUI** for document browsing, ASK flows, OPML viewing, and provider switching
- a **command-driven interface** where you type `$ COMMAND` style actions
- a **voice-driven Piper TUI** for text-to-speech workflows
- support for both **local OpenAI-compatible models** and **remote providers** such as Baseten

FunKit is also historically **PiKit-derived**. Some OPML and AI plumbing is bridged through vendored PiKit-compatible modules.

## What FunKit does

- Stores documents in SQLite (`storage/documents.db`)
- Lets you select text and run **ASK** operations that create linked AI response documents
- Supports **OPML import/export/preview** and expandable outline views
- Supports provider switching for different AI backends
- Can talk to a **local LLM on port 8080** through an OpenAI-compatible API
- Includes a **Piper-based voice interface** for speaking text and storing generated WAV output back into the document system

## Main surfaces

### 1. GUI
Primary entrypoint:

```bash
python main.py
```

The GUI includes:
- document sidebar
- main document pane
- ASK actions
- provider dropdown
- URL / fetch entry
- OPML tools
- image rendering helpers
- memory dialog

### 2. Command-driven mode
FunKit also has a command-oriented interaction model. In practice this means typing commands like:

```text
$ HELP
$ LIST
$ ASK ...
```

There are command and text interfaces in the repo, including:
- `modules/cli.py`
- `modules/text_interface.py`
- `modules/commands.py`

This command substrate is part of FunKit's identity, not an afterthought.

### 3. Piper voice TUI
Voice entrypoint:

```bash
python modules/tktalk.py
```

TkTalk uses Piper TTS and can:
- synthesize spoken output
- play generated WAV audio
- save both text and audio documents into the FunKit document store

By default it looks for:
- `voices/en_US-amy-low.onnx`

You can override with environment variables:
- `PIPER_CMD`
- `PIPER_MODEL`
- `PIPER_BIN`

## Piper prerequisites

FunKit voice features need two non-Python pieces that `requirements.txt` does **not** install for you:

1. A Piper executable
   - either available on your `PATH`
   - or pointed to with `PIPER_BIN` / `PIPER_CMD`
2. A Piper voice model
   - default repo path: `voices/en_US-amy-low.onnx`
   - or override with `PIPER_MODEL`

If the GUI banner says the voice model is missing, first check whether your checkout actually contains:

```bash
ls voices/en_US-amy-low.onnx
```

If that file is missing in your checkout, either restore it from git or point FunKit at another voice model:

```bash
export PIPER_MODEL="/full/path/to/your/en_US-amy-low.onnx"
```

## AI backends

FunKit supports multiple AI paths.

### Local LLM
The local OpenAI-compatible path defaults to:

```text
http://localhost:8080/v1
```

Relevant environment variables in `modules/local_ai_interface.py`:
- `PIKIT_OPENAI_BASE_URL` (default `http://localhost:8080/v1`)
- `PIKIT_OPENAI_API_KEY` (default `sk-local`)
- `PIKIT_MODEL_NAME`
- `PIKIT_REQUEST_TIMEOUT`

### Baseten / OpenAI-compatible remote endpoints
FunKit also includes a Baseten-focused interface.

Common variables include:
- `BASETEN_API_KEY`
- `BASETEN_BASE_URL`
- `BASETEN_MODEL`

There is also an INI-style sample config:
- `funkit.conf.sample`

## Architecture, short version

Primary boot path:
- `main.py`
- `modules.document_store.DocumentStore`
- `modules.command_processor.CommandProcessor`
- `modules.gui_tkinter.DemoKitGUI`
- `modules.ai_adapter.AIInterface`
- `modules.opml_bridge`

Important historical note:
- `modules.ai_adapter.py` delegates through `modules.pikit_port.ai_interface`
- `modules.opml_bridge.py` delegates through PiKit-compatible OPML modules in `modules.pikit_port`

So FunKit is best understood as a **PiKit-derived hybrid environment** that has been evolving toward its own identity.

## Repo state

This repository contains both live code and historical experimentation.
That includes:
- core modules
- older backup variants
- sample documents
- OPML experiments
- images and generated artifacts
- vendored PiKit-compatible bridge code

So if you are reading the tree directly, expect some sediment from active development.

## Quick start

### Requirements
- Python 3.10+
- Tkinter
- Python packages from `requirements.txt`
- optionally `openai`
- Piper executable for voice features
- Piper voice model for voice features
- optionally Pillow (`PIL`)

### Basic setup
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Voice setup
If you want the Piper talk features, make sure both of these work:

```bash
which piper
ls voices/en_US-amy-low.onnx
```

If Piper is installed somewhere unusual, set one of these before launching FunKit:

```bash
export PIPER_BIN="/full/path/to/piper"
# or
export PIPER_CMD="/full/path/to/piper"
```

If the voice model lives somewhere else, set:

```bash
export PIPER_MODEL="/full/path/to/voice.onnx"
```

### Run GUI
```bash
python main.py
```

### Run voice TUI
```bash
python modules/tktalk.py
```

### Local LLM example
Make sure your local OpenAI-compatible server is running on port 8080, then set:

```bash
export PIKIT_OPENAI_BASE_URL="http://localhost:8080/v1"
export PIKIT_OPENAI_API_KEY="sk-local"
export PIKIT_MODEL_NAME="mistral-7b-instruct"
```

## Git hygiene

This repo has historically accumulated large and generated files. Going forward, keep these out of normal source control when possible:
- database files
- exported docs
- logs
- archives
- model weights / voice assets
- large generated media

Use `.gitignore`, GitHub Releases, or LFS where appropriate.

## License
TBD
