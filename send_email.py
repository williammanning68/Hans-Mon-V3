import os
import re
from pathlib import Path

def load_keywords():
    """
    Load keywords from KEYWORDS_FILE (default: keywords.txt).
    Falls back to KEYWORDS env var (comma or newline separated).
    Returns a list of (pattern, display_text) where pattern is a compiled regex.
    """
    # 1) Try file
    file_path = Path(os.environ.get("KEYWORDS_FILE", "keywords.txt"))
    raw_terms = []
    if file_path.exists():
        for line in file_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # strip wrapping quotes for phrases like "cashless gaming"
            if (line.startswith('"') and line.endswith('"')) or (line.startswith("'") and line.endswith("'")):
                line = line[1:-1]
            raw_terms.append(line)

    # 2) Fallback to env var
    if not raw_terms:
        env_val = os.environ.get("KEYWORDS", "")
        # accept comma or newline separated
        pieces = [p.strip() for p in re.split(r"[,\n]", env_val) if p.strip()]
        raw_terms.extend(pieces)

    # Compile to case-insensitive literal patterns
    patterns = []
    for term in raw_terms:
        # literal match (escape regex metacharacters)
        pat = re.compile(re.escape(term), re.IGNORECASE)
        patterns.append((pat, term))
    return patterns
