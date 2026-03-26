## Jarvis + Kling (prompt workflow)

This repo helps you **plan multi-shot video scenes** with a local **Jarvis** assistant (Google **Gemini**). It writes a **`multishot_prompts.json`** file you can use as a reference when building prompts in the **Kling** website.

**This app does not call the Kling API.** Video generation stays in Kling’s UI.

### What you need (API keys)

| Variable | Required? | Purpose |
|----------|------------|---------|
| **`GEMINI_API_KEY`** | **Yes** | Powers Jarvis (chat + `/render` JSON generation). Get a key from [Google AI Studio](https://aistudio.google.com/apikey). |
| `KLING_ACCESS_KEY` / `KLING_SECRET_KEY` | **No** | Only if you use `kling.py` yourself for API experiments. **Not used** by `main.py`. |
| `JARVIS_MODEL` | No | Defaults to `gemini-2.0-flash`. Override in `.env` if you want another Gemini model id. |

Minimum `.env`:

```env
GEMINI_API_KEY=your_key_here
```

Copy from `.env.example` and remove or ignore Kling lines if you only use the prompt workflow.

### Install

```bash
cd /path/to/this/folder
pip install -r requirements.txt
```

### Run

```bash
python main.py
```

Everything below happens **in the terminal** (not in the editor).

1. **Session folder** — The app creates `projects/YYYYMMDD_HHMMSS/` for this run.

2. **Elements** — One per line, then a blank line to finish:
   - Format: `name | short description`
   - Example: `lisa | professor, red blazer` → Jarvis uses **`@lisa`** in prompts.

3. **Reference images (optional)** — Tags for images **you upload in Kling** (not URLs here):
   - Format: `@image1 | what this still shows` or `image1 | ...` (the `@` is added if missing)
   - Blank line when done.

4. **Chat** — Describe the scene, beats, tone, duration, etc.

5. **Commands** (at the `You:` prompt):
   - **`/render`** — Builds **`multishot_prompts.json`** in the current session folder (uses chat + session context). You can add notes: `/render make it 15 seconds, more handheld`.
   - **`@image2 | description`** — Register another reference tag for this session (same pattern as startup).
   - **`exit`** or **`quit`** — Stop the app.

Ask Jarvis “what commands can I use?” if you forget; he’s instructed to list them.

### Files written per session

Inside `projects/YYYYMMDD_HHMMSS/`:

| File | What it is |
|------|------------|
| `session.json` | Elements + reference-image tags you entered at startup |
| `chat.jsonl` | Append-only log of user + Jarvis messages |
| `multishot_prompts.json` | **Main output**: multi-shot–style JSON (shots, durations, Kling-oriented fields) after **`/render`** |
| `multishot_response_raw.txt` | Raw Gemini text (debug) |
| `multishot_response_stripped.txt` | Same after stripping ` ``` ` fences (debug) |

### Troubleshooting

- **`429 RESOURCE_EXHAUSTED`** — Gemini quota / rate limit; wait, check AI Studio usage, or billing/limits on your Google project.
- **JSON errors** — Fences and broken multiline strings are stripped/repaired when possible; check the `multishot_response_*.txt` files if `/render` still fails.

### Repo layout (short)

- **`main.py`** — CLI: session setup, chat loop, `/render` → save JSON  
- **`jarvis_agent.py`** — Gemini client + multishot JSON generation  
- **`kling.py`** — Optional Kling HTTP client (unused by `main.py` today)
