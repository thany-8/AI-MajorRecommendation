def main():
    print("Welcome to the Major Recommendation System!")
    print("Please answer the following questions to help us recommend the best major for you.")
    
    scores = {category: 0 for category in categories}
    previous_questions = []
    
    for i in range(1, 11):
        question = generate_question(i, "\n".join(previous_questions))
        previous_questions.append(question)
        
        answer = ask_question(question)
        scores = analyze_response(question, answer, scores)
    
    print("\nAnalyzing your responses...")
    
    # Determine the most suitable major
    prompt = f"""
    Based on the following scores:
    {scores}
    
    Recommend the most suitable major from this list:
    {', '.join(majors)}
    
    Provide a brief explanation for the recommendation.
    Format the response as: "Major: [recommended major]\nExplanation: [explanation]"
    """

    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": prompt}]
    )
    
    recommendation = response.choices[0].message.content.strip()
    print("\nRecommendation:")
    print(recommendation)

if __name__ == "__main__":
    main()