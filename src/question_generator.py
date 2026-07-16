def generate_question(question_number, previous_questions):
    prompt = f"""
    Generate a question for a student to help determine their most suitable major.
    This is question number {question_number} out of 10.
    The question should assess the student's personality, likings, and inclinations.
    It should help score the student on these categories: {', '.join(categories)}.
    
    Previous questions:
    {previous_questions}
    
    Generate a new, different question:
    """
    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": prompt}]
    )
    
    return response.choices[0].message.content.strip()