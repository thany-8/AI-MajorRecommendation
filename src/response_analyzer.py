def analyze_response(question, answer, scores):
    prompt = f"""
    Analyze the following question and answer:
    Question: {question}
    Answer: {answer}
    
    Based on this, update the scores for the following categories:
    {', '.join(categories)}
    
    Current scores: {scores}
    
    Provide the updated scores as a Python dictionary.
    """

    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": prompt}]
    )
    
    return eval(response.choices[0].message.content.strip())