"""
Run: python main.py

Creates projects/<YYYYMMDD_HHMMSS>/ for this session, then prompts for Elements and Kling reference-image @tags,
then chat with Jarvis. Use /render [optional extra instructions] to generate multishot_prompts.json.

In chat you can add more references anytime:  @image2 | description of what you uploaded in Kling
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console
from rich.prompt import Prompt

from jarvis_agent import JarvisAgent, ReferenceImage, SceneElement


console = Console()


def _require_env(name: str) -> str:
    val = os.getenv(name, "").strip()
    if not val:
        raise RuntimeError(f"Missing environment variable: {name}")
    return val


def _input_elements() -> list[SceneElement]:
    console.print(
        "\n[bold]Elements[/bold] (Kling @tags: use short names like [dim]lisa[/dim] -> @lisa). "
        "One per line: [dim]name | short description[/dim]. Empty line to finish."
    )
    out: list[SceneElement] = []
    while True:
        line = Prompt.ask("Element", default="").strip()
        if not line:
            break
        parts = [p.strip() for p in line.split("|", maxsplit=1)]
        if not parts[0]:
            console.print("[yellow]Use: name | description[/yellow]")
            continue
        name = parts[0]
        desc = parts[1] if len(parts) > 1 else name
        out.append(SceneElement(id=None, name=name, description=desc))
    return out


def _input_reference_images() -> list[ReferenceImage]:
    console.print(
        "\n[bold]Reference images[/bold] (optional). You upload these in Kling. "
        "Here you only register the [bold]@tag[/bold] and what it represents.\n"
        "One per line: [dim]@image1 | description[/dim] or [dim]image1 | description[/dim]. Empty line to finish."
    )
    out: list[ReferenceImage] = []
    while True:
        line = Prompt.ask("Ref image", default="").strip()
        if not line:
            break
        parts = [p.strip() for p in line.split("|", maxsplit=1)]
        if not parts[0]:
            console.print("[yellow]Use: @image1 | what this still shows[/yellow]")
            continue
        tag = parts[0]
        desc = parts[1] if len(parts) > 1 else "user reference still"
        out.append(ReferenceImage(tag=tag, description=desc))
    return out


def main() -> int:
    load_dotenv()

    repo_root = Path(__file__).resolve().parent
    projects_root = repo_root / "projects"
    projects_root.mkdir(exist_ok=True)

    session_name = datetime.now().strftime("%Y%m%d_%H%M%S")
    project_dir = projects_root / session_name
    project_dir.mkdir(parents=False)

    session_meta: dict = {
        "created_at": datetime.now().isoformat(),
        "elements": [],
        "reference_images": [],
    }

    console.print(f"\n[bold green]Session folder:[/bold green] {project_dir}\n")

    elements = _input_elements()
    reference_images = _input_reference_images()

    session_meta["elements"] = [{"id": e.id, "name": e.name, "kling_tag": e.kling_tag, "description": e.description} for e in elements]
    session_meta["reference_images"] = [{"tag": r.tag, "description": r.description} for r in reference_images]
    (project_dir / "session.json").write_text(
        json.dumps(session_meta, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    jarvis = JarvisAgent(
        gemini_api_key=_require_env("GEMINI_API_KEY"),
        project_dir=project_dir,
        elements=elements,
        reference_images=reference_images or None,
    )

    console.print("\n[bold]Jarvis online.[/bold] Chat about your scene.")
    console.print(
        "[dim]Add a ref in chat: @image2 | your description  |  /render [notes]  |  exit[/dim]\n"
    )

    while True:
        line = Prompt.ask("You").strip()
        if not line:
            continue
        low = line.lower()
        if low in {"exit", "quit"}:
            console.print("Goodbye.")
            return 0

        if low.startswith("/render"):
            extra = line[len("/render") :].strip()
            use_ctx = not extra
            console.print("\n[dim]Drafting Kling multi-shot prompts JSON...[/dim]")
            try:
                scene = jarvis.build_multishot_prompts_json(
                    user_goal=extra,
                    use_conversation_context=use_ctx,
                )
            except Exception as e:
                console.print(f"[red]{e}[/red]")
                continue

            console.print("\n[bold]JSON preview[/bold] (multi_prompt shots)")
            mp = scene.get("multi_prompt") or []
            if isinstance(mp, list) and mp:
                console.print(f"- shots: {len(mp)}")
                for s in mp:
                    if isinstance(s, dict):
                        console.print(f"  - index {s.get('index')}, duration {s.get('duration')}")

            out_path = jarvis.save_multishot_json(scene, filename="multishot_prompts.json")
            console.print(f"\n[green]Saved:[/green] {out_path}")
            continue

        try:
            reply = jarvis.chat(line)
        except Exception as e:
            console.print(f"[red]{e}[/red]")
            continue
        console.print(f"\n[bold]Jarvis:[/bold] {reply}\n")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print()
        raise SystemExit(0)
