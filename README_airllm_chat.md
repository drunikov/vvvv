# AirLLM CustomTkinter Chat App

Desktop chat UI using `customtkinter` with two backends:
- `airllm` (4-bit loading for Hugging Face/local transformer folders)
- `ollama` (local Ollama models)

## Features
- ChatGPT/Ollama-like desktop layout.
- Conversation sidebar (new, switch, rename, delete).
- Saved chat history (`airllm_chat_history.json`).
- Settings panel:
  - backend selector (`airllm` / `ollama`),
  - auto detect + refresh models,
  - model preset/model id,
  - max new tokens,
  - temperature,
  - top_p,
  - system prompt,
  - optional layer shard path,
  - profiling mode toggle.
- Manual model load button.
- Auto-detection for local Ollama and local model folders.
- Big-download confirmation for remote Hugging Face model IDs.
- Async inference worker so UI stays responsive.
- Incremental assistant text rendering.

## Requirements
- Python 3.10+
- Linux with CUDA-capable GPU (recommended for large AirLLM models)
- For `airllm` + gated Meta models: Hugging Face access + token
- For `ollama`: local Ollama install and pulled models

Install dependencies:

```bash
python install_airllm_requirements.py
```

Installer modes:

```bash
# Auto (recommended)
python install_airllm_requirements.py

# Force AirLLM stack
python install_airllm_requirements.py --backend airllm

# Force Ollama-friendly deps
python install_airllm_requirements.py --backend ollama
```

On Debian/Linux, installer automatically uses `--break-system-packages`.

## Platform Quick Start

### Debian / Linux
1. `python install_airllm_requirements.py`
2. (Optional local Ollama) install Ollama, then `ollama pull llama3.1:8b`
3. `python airllm_chat_app.py`

### Windows
1. `py install_airllm_requirements.py` (auto mode is Ollama-friendly)
2. Install Ollama from `https://ollama.com/download`
3. `ollama pull llama3.1:8b`
4. Start app: `py airllm_chat_app.py`

## Hugging Face Access
You need model access approved on Hugging Face and an auth token.

Set token in shell:

```bash
export HF_TOKEN=your_token_here
```

You can also paste a token in the app UI (not persisted).

## Local AI Modes

### 1) Ollama local models
- Install Ollama.
- Pull model(s), for example:

```bash
ollama pull llama3.1:8b
```

- In app settings, set backend to `ollama`, then `Auto Detect` or `Refresh Models`.

### 2) AirLLM local folder
- Put a Hugging Face-format model folder on disk (must contain `config.json` and tokenizer files).
- Set backend to `airllm` and set `Model ID` to the local folder path.
- Optional: click `Auto Detect` to scan common `models` folders.

## Run
From this directory:

```bash
python airllm_chat_app.py
```

Tip: In settings, click `Auto Detect` first. It will pick the easiest local backend/model available.

## Notes
- First model load can be very slow due to download/sharding/cache setup.
- 4-bit helps memory usage, but 70B is still heavy on hardware.
- If generation fails, check:
  - `HF_TOKEN` validity and model approval,
  - backend selection (`airllm` vs `ollama`),
  - `ollama serve` is running for Ollama backend,
  - CUDA/driver compatibility,
  - `bitsandbytes` installation,
  - available VRAM and system RAM.
