from __future__ import annotations

import shutil
from dataclasses import dataclass
from activities import TYPES, activity_options
from pathlib import Path

import deckgen
from deckgen.build import load_deck
from deckgen.project import Project, configure


@dataclass
class Deck:
    site: Path
    url: str
    title: str
    slides: list[dict]
    initial_slide: int

    def selection(self, body: dict, require_activity: bool = True) -> dict:
        index = body.get("slide_index", self.initial_slide)
        fragment = body.get("fragment_index", -1)
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(self.slides):
            raise ValueError("Choose a valid slide in the deck.")
        if isinstance(fragment, bool) or not isinstance(fragment, int) or not -1 <= fragment <= 100:
            raise ValueError("Invalid slide fragment index.")
        activity = self.slides[index]["activity"] or {}
        if require_activity and not activity:
            raise ValueError("This slide has no live activity.")
        options = activity_options(activity) if require_activity else {}
        return {
            **options,
            "slide_index": index,
            "fragment_index": fragment,
            "total_slides": len(self.slides),
        }



def render_deck(output: Path, project_path: Path | None = None, name: str | None = None) -> Deck:
    if project_path:
        project = configure(project_path)
        name = name or next(iter(project.decks), None)
        if not name or Path(name).name != name or name in {".", ".."}:
            raise ValueError("Pass --deck with a deck name from your deckgen project.")
        module = load_deck(project, name)
        definition = module.DECK
    else:
        from demo_deck import DECK
        project = configure(Project(root=Path(__file__).parent, code="POC", name="HTML presenter"))
        definition = DECK
        name = "demo"

    source = Path(deckgen.__file__).parent / "scaffold" / "site"
    shutil.copytree(source, output, dirs_exist_ok=True)
    if project_path and project.site_src.is_dir():
        shutil.copytree(project.site_src, output, dirs_exist_ok=True)
    deckgen.build_html(definition, output / name)
    slides = [
        {"title": slide.title, "activity": dict(slide.cp) if slide.cp else None}
        for slide in definition["slides"]
    ]
    if not slides:
        raise ValueError("The deck is empty.")
    initial = next((index for index, slide in enumerate(slides) if (slide["activity"] or {}).get("type") in TYPES), 0)
    return Deck(output, f"/deck/{name}/index.html", definition["title"], slides, initial)
