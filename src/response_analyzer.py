"""Analyze a student's answer and update their trait scores.

Fixes the original skeleton, which referenced ``openai``/``categories`` without
importing them, used the removed ``openai.ChatCompletion`` API, and ran the
model's raw output through ``eval`` (a security risk). We now request strict
JSON and parse it safely with ``json.loads``.
"""

import json

from .utils import CATEGORIES, get_client, get_model


def analyze_response(question, answer, scores):
    """Return an updated copy of ``scores`` based on a question/answer pair."""
    prompt = f"""
    Analyze the following question and answer:
    Question: {question}
    Answer: {answer}

    Based on this, update the scores for the following categories:
    {', '.join(CATEGORIES)}

    Current scores: {json.dumps(scores)}

    Return ONLY a JSON object mapping each category name to an integer from 0 to 100.
    """
    client = get_client()
    response = client.chat.completions.create(
        model=get_model(),
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0.4,
    )

    try:
        updated = json.loads(response.choices[0].message.content or "{}")
    except json.JSONDecodeError:
        # If the model returns something unparseable, keep the current scores.
        return dict(scores)

    result = dict(scores)
    for category in CATEGORIES:
        if category in updated:
            try:
                result[category] = max(0, min(100, int(updated[category])))
            except (TypeError, ValueError):
                pass
    return result