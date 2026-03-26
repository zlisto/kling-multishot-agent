## Jarvis + Kling (prompt workflow)

This repo helps you **plan multi-shot video scenes** with a local **Jarvis** assistant (Google **Gemini**). It writes a **`multishot_prompts.json`** file you can use as a reference when building prompts in the **Kling** website.

**This app does not call the Kling API.** Video generation stays in Kling’s UI.

### Kling account (browser)

You use **Kling’s website** to upload Elements, reference images, and render video. Jarvis only helps you write prompts.

1. Open **[Kling](https://app.klingai.com/global/)** in a browser.
2. Use **Sign up** or **Log in** (options vary by region; often email or a third-party sign-in).
3. Complete any onboarding steps the site shows.
4. Add **credits / Spirit** or a **membership** if you plan to generate video (see links below). Pricing changes; always confirm in the app.

### Kling URLs (quick reference)

| What | Link |
|------|------|
| **Main app** | [https://app.klingai.com/global/](https://app.klingai.com/global/) |
| **Spirit / credit pricing** | [https://app.klingai.com/global/membership/spirit-unit](https://app.klingai.com/global/membership/spirit-unit) |
| **Membership plans** | [https://app.klingai.com/global/membership/membership-plan](https://app.klingai.com/global/membership/membership-plan) |
| **Element Library 3 user guide** | [https://app.klingai.com/global/quickstart/klingai-element-library-3-user-guide](https://app.klingai.com/global/quickstart/klingai-element-library-3-user-guide) |
| **Kling Video 3 Omni (model guide)** | [https://app.klingai.com/global/quickstart/klingai-video-3-omni-model-user-guide](https://app.klingai.com/global/quickstart/klingai-video-3-omni-model-user-guide) |
| **Omni Video API reference** (optional; not used by this repo’s `main.py`) | [https://app.klingai.com/global/dev/document-api/apiReference/model/OmniVideo](https://app.klingai.com/global/dev/document-api/apiReference/model/OmniVideo) |

Informal cost notes (from local testing; **verify in-app**):

- Example pack: **330 credits ≈ $5.00**
- Example run: **15s** Omni 3 multishot, **6 scenes** → **180 credits** (settings and pricing change over time)

### API key (only one required)

You need a **Google Gemini API key**:

| Variable | Required? | Purpose |
|----------|------------|---------|
| **`GEMINI_API_KEY`** | **Yes** | Powers Jarvis (chat + `/render`). Create a key in [Google AI Studio](https://aistudio.google.com/apikey). |

Put it in `.env`:

```env
GEMINI_API_KEY=your_key_here
```

Optional: set `JARVIS_MODEL` in `.env` if you want a different Gemini model id (default is `gemini-2.0-flash`). Nothing else is required for `python main.py`.

The repo includes **`kling.py`** for optional direct Kling API experiments; **`main.py` does not use it** and you do not need any Kling API keys for the Jarvis workflow.

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

### Example session (elements → refs → chat → storyboard)

```text
Session folder: projects/20260326_143000/

Element: lisa | Yale SOM professor, red blazer, guest lecture
Element: tauhid | colleague, orange shirt, supportive
Element:

Ref image: @image1 | empty Yale SOM classroom, wide establishing
Ref image:

You: Two-shot romantic comedy beat after my lecture. Tauhid tells Lisa the students were great, she deflects, he says she's amazing. Last shot wide in the classroom. 15 seconds total, cinematic.

You: /render
```

After **`/render`**, open `projects/<that_session>/multishot_prompts.json` and copy shot prompts into Kling’s custom multi-shot UI (bind your Elements and uploaded `@image` refs there).

### Files written per session

Inside `projects/YYYYMMDD_HHMMSS/`:

| File | What it is |
|------|------------|
| `session.json` | Elements + reference-image tags you entered at startup |
| `chat.jsonl` | Append-only log of user + Jarvis messages |
| `multishot_prompts.json` | **Main output**: multi-shot–style JSON after **`/render`** |
| `multishot_response_raw.txt` | Raw Gemini text (debug) |
| `multishot_response_stripped.txt` | Same after stripping code fences (debug) |

### Troubleshooting

- **`429 RESOURCE_EXHAUSTED`** — Gemini quota / rate limit; wait, check AI Studio usage, or billing/limits on your Google project.
- **JSON errors** — Fences and broken multiline strings are stripped/repaired when possible; check the `multishot_response_*.txt` files if `/render` still fails.

### Repo layout (short)

- **`main.py`** — CLI: session setup, chat loop, `/render` → save JSON  
- **`jarvis_agent.py`** — Gemini client + multishot JSON generation  
- **`kling.py`** — Optional Kling HTTP client (unused by `main.py`)
