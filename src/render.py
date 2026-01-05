#functions for displaying and analysing the survey output

from __future__ import annotations
from typing import Dict, Any, List
import pandas as pd

#loops through all sections, questions and flattens everything into a table
def extract_codebook(survey: Dict[str, Any]) -> pd.DataFrame:
    rows: List[dict] = []
    for sec in survey.get("sections", []):
        for q in sec.get("questions", []):
            rows.append({
                "question_id": q.get("id"),
                "section": sec.get("title"),
                "text": q.get("text"),
                "type": q.get("type"),
                "options": " | ".join(q.get("options") or []),
                "topic": q.get("topic"),
                "analysis_tag": q.get("analysis_tag"),
                "required": q.get("required", True),
            })
    return pd.DataFrame(rows)

#count questions across sections
def count_questions(survey: Dict[str, Any]) -> int:
    n = 0
    for sec in survey.get("sections", []):
        n += len(sec.get("questions", []))
    return n
