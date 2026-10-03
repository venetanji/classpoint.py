from deckgen.layouts import finalize, question


DECK = {
    "title": "ClassPoint without PowerPoint",
    "console": False,
    "slides": finalize([
        question(
            "multiple_choice",
            "Where is this slide running?",
            choices=["PowerPoint", "An HTML page", "A PDF", "A screenshot viewer"],
        ),
    ], "AIT4X / DECKGEN / CLASSPOINT HTML PROOF OF CONCEPT"),
}
