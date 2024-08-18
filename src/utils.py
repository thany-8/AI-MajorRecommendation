# src/utils.py

import openai
import os
from dotenv import load_dotenv

def initialize_openai():
    """
    Initialize the OpenAI API with the API key stored in the .env file.
    Raises:
        ValueError: If the OpenAI API key is not found in the .env file.
    """
    load_dotenv()

    # Set up OpenAI API key
    openai.api_key = os.getenv("OPENAI_API_KEY")

    if not openai.api_key:
        raise ValueError("OpenAI API key not found. Please check your .env file.")

# List of majors
majors = ["Computer Science", "Psychology", "Business Administration"]

# Categories which the questions should assess the student on
categories = ["Analytical", "Creative", "Social", "Technical", "Leadership"]


initialize_openai()