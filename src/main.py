"""Command-line version of the Major Recommendation System.

Run from the project root with:

    python -m src.main

For the full visual web experience instead, run:

    python app.py
"""

from .question_generator import generate_question
from .response_analyzer import analyze_response
from .utils import (
    CATEGORIES,
    COMMON_MAJORS,
    RecommenderError,
    ask_question,
    get_client,
    get_model,
)


def main():
    print("Welcome to the Major Recommendation System!")
    print("Please answer the following questions to help us recommend the best major for you.\n")

    scores = {category: 0 for category in CATEGORIES}
    previous_questions = []

    for i in range(1, 11):
        question = generate_question(i, "\n".join(previous_questions))
        previous_questions.append(question)

        answer = ask_question(question)
        scores = analyze_response(question, answer, scores)

    print("\nAnalyzing your responses...")

    # Determine the most suitable major.
    prompt = f"""
    Based on the following trait scores (0-100):
    {scores}

    Recommend the single most suitable university major. You may choose from the
    list below or suggest a closely related major that fits the student better:
    {', '.join(COMMON_MAJORS)}

    Provide a brief explanation for the recommendation.
    Format the response as: "Major: [recommended major]\nExplanation: [explanation]"
    """

    client = get_client()
    response = client.chat.completions.create(
        model=get_model(),
        messages=[{"role": "user", "content": prompt}],
    )

    recommendation = response.choices[0].message.content.strip()
    print("\nRecommendation:")
    print(recommendation)


if __name__ == "__main__":
    try:
        main()
    except RecommenderError as exc:
        print(f"\nError: {exc}")