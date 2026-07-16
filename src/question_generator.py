"""Generate assessment questions for the command-line quiz.

Fixes the original skeleton, which referenced ``openai`` and ``categories``
without importing them and used the removed ``openai.ChatCompletion`` API.
"""

from .utils import CATEGORIES, get_client, get_model


def generate_question(question_number, previous_questions):
    """Generate the next distinct assessment question via the OpenAI API."""
    prompt = f"""
    Generate a question for a student to help determine their most suitable major.
    This is question number {question_number} out of 10.
    The question should assess the student's personality, likings, and inclinations.
    It should help score the student on these categories: {', '.join(CATEGORIES)}.

    Previous questions:
    {previous_questions}

    Generate a new, different question. Return only the question text:
    """
    client = get_client()
    response = client.chat.completions.create(
        model=get_model(),
        messages=[{"role": "user", "content": prompt}],
        temperature=0.8,
    )
    return response.choices[0].message.content.strip()