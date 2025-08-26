import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

import send_email


def test_standalone_speaker_line_inheritance():
    text = (
        "Mr John Doe -\n\n"
        "Apple is tasty.\n\n"
        "Banana is yellow."
    )
    keywords = ["Apple", "Banana"]
    matches = send_email.extract_matches(text, keywords)
    assert len(matches) == 2
    assert [m[2] for m in matches] == ["Mr John Doe -", "Mr John Doe -"]
