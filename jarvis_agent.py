"""
Jarvis: Gemini conversational agent that generates Hollywood multi-shot prompts JSON for Kling.
No Kling API calls are made.

Kling UI: characters use @name (e.g. @lisa). Uploaded reference images use @image, @image1, etc.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional


def _strip_markdown_code_fences(text: str) -> str:
    """Remove ``` / ```json wrappers Gemini sometimes adds."""
    t = (text or "").strip()
    t = re.sub(r"^\s*```(?:json)?\s*", "", t, count=1, flags=re.IGNORECASE | re.MULTILINE)
    t = re.sub(r"\s*```\s*$", "", t, count=1, flags=re.MULTILINE)
    return t.strip()


def _extract_balanced_json_object(text: str) -> Optional[str]:
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_str = False
    esc = False
    quote_ch = ""
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == quote_ch:
                in_str = False
                quote_ch = ""
        else:
            if ch in ('"', "'"):
                in_str = True
                quote_ch = ch
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
    return None


def _parse_json_blob(text: str) -> dict[str, Any]:
    """Strip fences, then parse; repair multiline-in-string JSON if needed."""
    cleaned = _strip_markdown_code_fences(text)
    candidates = [cleaned]
    inner = _extract_balanced_json_object(cleaned)
    if inner and inner not in candidates:
        candidates.append(inner)
    inner2 = _extract_balanced_json_object(text)
    if inner2 and inner2 not in candidates:
        candidates.append(inner2)

    last_err: Optional[BaseException] = None
    for cand in candidates:
        if not cand:
            continue
        try:
            obj = json.loads(cand)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError as e:
            last_err = e
        try:
            import json_repair

            obj = json_repair.loads(cand)
            if isinstance(obj, dict):
                return obj
        except Exception as e:
            last_err = e

    preview = (text[:1000] + "...") if len(text) > 1000 else text
    raise RuntimeError("Could not parse JSON after stripping ``` fences. Preview:\n" + preview) from last_err


def _collapse_multiline_strings_in_scene(scene: dict[str, Any]) -> None:
    np = scene.get("negative_prompt")
    if isinstance(np, str):
        scene["negative_prompt"] = " ".join(np.split())
    refs = scene.get("reference_images")
    if isinstance(refs, list):
        for item in refs:
            if isinstance(item, dict) and isinstance(item.get("description"), str):
                item["description"] = " ".join(item["description"].split())
    mp = scene.get("multi_prompt")
    if isinstance(mp, list):
        for shot in mp:
            if isinstance(shot, dict) and isinstance(shot.get("prompt"), str):
                shot["prompt"] = " ".join(shot["prompt"].split())


def _kling_at_tag(raw: str) -> str:
    """Normalize 'lisa' or '@lisa' -> '@lisa'."""
    s = (raw or "").strip()
    if not s:
        return s
    return s if s.startswith("@") else f"@{s}"


@dataclass
class SceneElement:
    id: Optional[str]
    name: str
    description: str

    @property
    def kling_tag(self) -> str:
        return _kling_at_tag(self.name)


@dataclass
class ReferenceImage:
    """Reference you upload in Kling; prompts use this exact tag (e.g. @image1)."""

    tag: str
    description: str

    def __post_init__(self) -> None:
        self.tag = _kling_at_tag(self.tag.strip().replace(" ", ""))


def _require_non_empty(val: str, name: str) -> str:
    v = (val or "").strip()
    if not v:
        raise RuntimeError(f"Missing required value: {name}")
    return v


class JarvisAgent:
    def __init__(
        self,
        gemini_api_key: str,
        project_dir: Path,
        elements: list[SceneElement],
        reference_images: Optional[list[ReferenceImage]] = None,
        model: Optional[str] = None,
    ):
        self._gemini_api_key = _require_non_empty(gemini_api_key, "GEMINI_API_KEY")
        self.project_dir = Path(project_dir).resolve()
        self.project_dir.mkdir(parents=True, exist_ok=True)
        self.elements = list(elements)
        self.reference_images = list(reference_images or [])
        self.model = (model or os.getenv("JARVIS_MODEL", "gemini-2.0-flash") or "gemini-2.0-flash").strip()
        self._chat_log_path = self.project_dir / "chat.jsonl"
        self._history: list[dict[str, Any]] = []

    def _gemini_client(self):
        from google import genai  # type: ignore

        return genai.Client(api_key=self._gemini_api_key)

    def _format_elements_brief(self) -> str:
        if not self.elements:
            return "No Elements configured for this session."
        lines = [
            "Kling character Elements (in shot prompts you MUST use these exact @tags, not plain names):"
        ]
        for el in self.elements:
            lines.append(f"- {el.kling_tag}: {el.description}")
        return "\n".join(lines)

    def _format_reference_images_brief(self) -> str:
        if not self.reference_images:
            return "No reference images configured for this session (user can add more in chat)."
        lines = [
            "Kling reference images the user uploads in the Kling UI. In shot prompts, reference them ONLY by these exact tags:"
        ]
        for ref in self.reference_images:
            lines.append(f"- {ref.tag}: {ref.description}")
        return "\n".join(lines)

    def _reference_images_from_chat(self) -> list[dict[str, str]]:
        """Pick up user lines like: @image2 | night skyline for dubai."""
        out: list[dict[str, str]] = []
        for turn in self._history:
            if turn.get("role") != "user":
                continue
            text = (turn.get("text") or "").strip()
            m = re.match(r"^(@\S+)\s*\|\s*(.+)$", text)
            if not m:
                continue
            tag = _kling_at_tag(m.group(1).strip())
            if tag.lower().startswith("@image") or tag == "@image":
                out.append({"tag": tag, "description": m.group(2).strip()})
        return out

    def _append_log(self, role: str, text: str) -> None:
        from datetime import datetime

        line = json.dumps({"ts": datetime.now().isoformat(), "role": role, "text": text}, ensure_ascii=False)
        with self._chat_log_path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    def _conversation_text_for_summary(self, max_turns: int = 20) -> str:
        parts = []
        for turn in self._history[-max_turns:]:
            role = turn.get("role", "user")
            text = turn.get("text", "")
            parts.append(f"{role.upper()}: {text}")
        return "\n".join(parts)

    def chat(self, user_message: str) -> str:
        """Free-form Jarvis reply; updates in-memory history and chat.jsonl."""
        user_message = user_message.strip()
        self._append_log("user", user_message)

        system = f"""You are Jarvis, Tony Stark's AI assistant: concise, capable, slightly dry wit.
You help the user plan cinematic multi-shot video scenes for Kling (website).

Kling tagging rules:
- Characters are bound by @tags matching the user's Elements (e.g. @lisa, @tauhid). Always use those exact tags in any example shot line you write.
- Reference images the user uploads in Kling are invoked by tags like @image, @image1, @image2. If the user defines a new reference in chat as "@tag | description", treat that tag as real for the rest of the session.

Context for this session:
{self._format_elements_brief()}

{self._format_reference_images_brief()}

Terminal commands (user types these at the "You:" prompt):
- /render — Writes multishot_prompts.json into the current session folder under projects/. Use after you have discussed the scene. Optional: /render followed by extra instructions on the same line.
- exit or quit — Stops the program.
- @image1 | short description — Registers another Kling reference still tag for this session (user uploads the matching image in Kling). Same pattern for @image2, @image, etc.

If the user asks what to type, how to save the file, available commands, help, or "what is /render", explain the commands above clearly and briefly. You may add one sentence that normal messages are just scene discussion.

Do not output JSON in chat unless the user explicitly asks for raw JSON."""
        client = self._gemini_client()
        transcript_lines: list[str] = []
        for turn in self._history:
            label = "User" if turn.get("role") == "user" else "Jarvis"
            transcript_lines.append(f"{label}: {turn.get('text', '')}")
        transcript = "\n".join(transcript_lines)
        prompt = f"""{system}

Conversation so far:
{transcript if transcript else "(start)"}

User: {user_message}
Jarvis:"""
        resp = client.models.generate_content(model=self.model, contents=prompt)
        reply = (resp.text or "").strip()
        if not reply:
            reply = "(Jarvis had nothing to say.)"

        self._history.append({"role": "user", "text": user_message})
        self._history.append({"role": "model", "text": reply})
        self._append_log("jarvis", reply)
        return reply

    def build_multishot_prompts_json(
        self,
        user_goal: str,
        use_conversation_context: bool,
        *,
        default_total_duration_seconds: int = 15,
    ) -> dict[str, Any]:
        element_brief = self._format_elements_brief()
        ref_brief = self._format_reference_images_brief()
        chat_refs = self._reference_images_from_chat()
        chat_ref_note = ""
        if chat_refs:
            chat_ref_note = "\nReference images also defined in chat (use these exact @tags in prompts when relevant):\n"
            for r in chat_refs:
                chat_ref_note += f"- {r['tag']}: {r['description']}\n"

        convo = ""
        if use_conversation_context and self._history:
            convo = (
                "\nRecent conversation (use this if user_goal is empty or vague):\n"
                + self._conversation_text_for_summary()
            )

        instruction = f"""
You are Jarvis. Output ONE JSON object only (no markdown, no prose, no code fences).

Goal:
Create a CUSTOM MULTI-SHOT scene for Kling. The user pastes each shot prompt into Kling's custom multi-shot UI.

Kling tagging (critical):
- Every character appearance in a shot "prompt" string MUST use the session's Element @tags exactly (example: @lisa, @tauhid).
- If a shot should use a user-uploaded reference still, mention that reference by its exact tag in the prompt (example: match framing to @image1, or start from @image2 as style anchor). Do not invent @tags that were not listed.
- Do not use plain names without @ for Elements.

{element_brief}

{ref_brief}
{chat_ref_note}
{convo}

User scene description / extra instructions:
{user_goal or "(infer from conversation above)"}

If the user does not specify total length, default to {default_total_duration_seconds} seconds.

JSON requirements:
- multi_shot=true, shot_type="customize"
- multi_prompt: array of shots, each with index (1-based), duration (integer seconds), prompt (one string)
- top-level "duration" string must equal the sum of shot durations
- Include "reference_images" array documenting each @image tag used: [{{"tag":"@image1","description":"..."}}] merged from session + any from chat lines like "@tag | desc"
- Include model_name, mode, aspect_ratio, watermark, negative_prompt as before

Hollywood style:
- Camera, lens, movement, blocking, lighting, atmosphere.
- Dialogue: period-separated for TTS. No em-dashes. Attribute speech like: @lisa says ... or @tauhid says ... (use real session tags).

Rules:
- Shot prompts should be self-contained when possible.
- If the scene is romantic banter and the user wants a closing beat, you may end with a wide two-shot and camera pulling back. Otherwise match the user's genre.

Required JSON shape:
{{
  "model_name": "kling-v3-omni",
  "mode": "pro",
  "aspect_ratio": "16:9",
  "duration": "0",
  "watermark": {{"enabled": false}},
  "negative_prompt": "string",
  "multi_shot": true,
  "shot_type": "customize",
  "reference_images": [{{"tag": "@image1", "description": "string"}}],
  "multi_prompt": [
    {{"index": 1, "duration": 0, "prompt": "string with @tags"}}
  ]
}}
""".strip()

        client = self._gemini_client()
        resp = client.models.generate_content(model=self.model, contents=instruction)
        text = (resp.text or "").strip()
        if not text:
            raise RuntimeError("Jarvis returned empty response.")

        raw_path = self.project_dir / "multishot_response_raw.txt"
        raw_path.write_text(text, encoding="utf-8")

        stripped = _strip_markdown_code_fences(text)
        stripped_path = self.project_dir / "multishot_response_stripped.txt"
        stripped_path.write_text(stripped, encoding="utf-8")

        scene = _parse_json_blob(text)
        _collapse_multiline_strings_in_scene(scene)

        # Merge reference_images: model output + session + chat-defined
        by_tag: dict[str, str] = {}
        for r in self.reference_images:
            by_tag[r.tag] = r.description
        for r in chat_refs:
            by_tag[r["tag"]] = r["description"]
        existing = scene.get("reference_images")
        if isinstance(existing, list):
            for item in existing:
                if isinstance(item, dict) and item.get("tag"):
                    by_tag[_kling_at_tag(str(item["tag"]))] = str(item.get("description") or "").strip() or by_tag.get(
                        _kling_at_tag(str(item["tag"])), ""
                    )
        scene["reference_images"] = [{"tag": t, "description": d} for t, d in sorted(by_tag.items())]

        ids = [e.id for e in self.elements if e.id]
        if ids and not scene.get("element_list"):
            scene["element_list"] = ids

        multi_prompt = scene.get("multi_prompt")
        if isinstance(multi_prompt, list) and multi_prompt:
            # Kling custom multi-shot expects shot indices starting from 1.
            for i, shot in enumerate(multi_prompt, start=1):
                if isinstance(shot, dict):
                    shot["index"] = i

            total = 0
            for shot in multi_prompt:
                if isinstance(shot, dict):
                    d = shot.get("duration")
                    if isinstance(d, (int, float, str)):
                        try:
                            total += int(float(d))
                        except Exception:
                            pass
            if total > 0:
                scene["duration"] = str(total)

        return scene

    def save_multishot_json(self, scene_json: dict[str, Any], *, filename: str = "multishot_prompts.json") -> Path:
        out_path = self.project_dir / filename
        out_path.write_text(json.dumps(scene_json, indent=2, ensure_ascii=False), encoding="utf-8")
        return out_path
