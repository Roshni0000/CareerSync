import os
import json
import re
from google import genai
from google.genai import types
from pypdf import PdfReader
from dotenv import load_dotenv

# Load local environment variables if .env file exists
load_dotenv(dotenv_path=".env.local")

AVAILABLE_FLASH_MODEL = None

def get_genai_client():
    """Initializes and returns the Gemini API client."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        # Fallback to check default GEMINI_API_KEY or other env vars
        api_key = os.environ.get("GEMINI_API_KEY")
    return genai.Client(api_key=api_key)

def get_flash_model_name():
    """Dynamically resolves which Flash model is available in the current environment."""
    global AVAILABLE_FLASH_MODEL
    if AVAILABLE_FLASH_MODEL:
        return AVAILABLE_FLASH_MODEL
        
    priorities = [
        "gemini-2.5-flash",
        "gemini-2.0-flash",
        "gemini-3.5-flash",
        "gemini-1.5-flash",
        "gemini-flash-latest"
    ]
    
    try:
        client = get_genai_client()
        model_list = [m.name.replace("models/", "") for m in client.models.list()]
        for p in priorities:
            if p in model_list:
                AVAILABLE_FLASH_MODEL = p
                print(f"Auto-resolved flash model to: {p}")
                return p
    except Exception as e:
        print(f"Error listing models (API key might be missing/invalid): {e}")
        
    # Fallback default
    AVAILABLE_FLASH_MODEL = "gemini-2.5-flash"
    return AVAILABLE_FLASH_MODEL

def extract_text_from_pdf(pdf_path):
    """Extracts raw text from a PDF file using pypdf."""
    try:
        reader = PdfReader(pdf_path)
        text = ""
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
        return text.strip()
    except Exception as e:
        print(f"Error reading PDF {pdf_path}: {e}")
        return ""

def parse_resume_with_ai(resume_text):
    """
    Sends raw resume text to Gemini to parse into a structured JSON schema.
    """
    prompt = f"""
    You are an expert ATS (Applicant Tracking System) parser and resume engineer.
    Analyze the following raw resume text and extract it into a clean, structured JSON format.
    
    Raw Resume Text:
    ---
    {resume_text}
    ---
    
    Provide the output in JSON format matching the following schema. Make sure to extract dates, grades, and descriptions cleanly.
    
    JSON Schema:
    {{
        "name": "Full Name",
        "email": "Email Address",
        "phone": "Phone Number",
        "links": {{
            "linkedin": "LinkedIn URL or empty",
            "github": "GitHub URL or empty",
            "portfolio": "Portfolio/Website URL or empty"
        }},
        "summary": "A brief professional summary based on the resume, or empty",
        "user_location": "Current city/state/location of the candidate, e.g. Mumbai, or empty if not found",
        "education": [
            {{
                "institution": "School/University Name",
                "degree": "Degree (e.g. B.Tech, High School)",
                "field": "Field of Study (e.g. Computer Science) or empty",
                "duration": "Duration/Dates (e.g. 2020 - 2024)",
                "grade": "GPA/Percentage or empty"
            }}
        ],
        "experience": [
            {{
                "company": "Company Name",
                "role": "Job Title / Role",
                "location": "Location or empty",
                "duration": "Duration/Dates (e.g. June 2023 - Present)",
                "description": "Description of work done"
            }}
        ],
        "projects": [
            {{
                "title": "Project Title",
                "technologies": ["List of technologies used"],
                "description": "Description of the project and achievements",
                "link": "Project Link or empty"
            }}
        ],
        "skills": ["List of skills, programming languages, libraries, tools, and databases"]
    }}
    """
    
    try:
        client = get_genai_client()
        model_name = get_flash_model_name()
        # Use gemini flash model for fast parsing with structured output
        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.1
            ),
        )
        
        parsed_json = json.loads(response.text)
        return parsed_json
    except Exception as e:
        print(f"Error parsing resume with Gemini: {e}")
        # Return a shell schema as fallback
        return {
            "name": "", "email": "", "phone": "",
            "links": {"linkedin": "", "github": "", "portfolio": ""},
            "summary": "Failed to parse automatically. Please fill out details manually.",
            "user_location": "",
            "education": [], "experience": [], "projects": [], "skills": []
        }

def match_opportunity_with_ai(profile, job_details):
    """
    Compares user profile with job details and returns a match score (0-100),
    reasons for matching, and missing skills.
    """
    prompt = f"""
    You are an elite career advisor and job matching algorithm.
    Analyze the Candidate Profile and the Job Description, and calculate:
    1. A match percentage (0 to 100) representing how well the candidate's skills, projects, and experiences fit this opportunity.
    2. A list of 3-4 key reasons why the candidate is a strong match (specifically referencing their projects/experience).
    3. A list of missing skills or tools mentioned in the job details that the candidate does not have in their profile.
    
    CRITICAL EVALUATION GUIDELINES:
    - Assess how the opportunity's Job Type (e.g., Internship, Hackathon, Job) matches the candidate's preferred job types (in 'preferred_job_types').
    - Assess how the opportunity's domain/keywords match the candidate's preferred domains (in 'preferred_domains').
    - Assess if the stipend/salary matches or exceeds the candidate's expected pay (in 'expected_salary').
    - If there is a mismatch in expected job types, domains, or expected salary, adjust the match score down and explicitly explain the discrepancy in the reasons or gaps.
    
    Candidate Profile:
    {json.dumps(profile, indent=2)}
    
    Job Details:
    {json.dumps(job_details, indent=2)}
    
    Provide the output in JSON format matching this schema:
    {{
        "score": 85,
        "reasons": [
            "Reason 1 highlighting a project or experience matching the JD",
            "Reason 2...",
            "Reason 3..."
        ],
        "gaps": [
            "Missing tool/skill 1",
            "Missing tool/skill 2"
        ]
    }}
    """
    
    try:
        client = get_genai_client()
        model_name = get_flash_model_name()
        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.2
            ),
        )
        return json.loads(response.text)
    except Exception as e:
        print(f"Error matching opportunity with Gemini: {e}")
        return {
            "score": 50,
            "reasons": ["Error performing AI match calculation. Showing baseline match."],
            "gaps": []
        }

def tailor_documents_with_ai(profile, job_details):
    """
    Generates a tailored Resume (JSON format containing re-worded bullet points),
    a custom Cover Letter, and a Statement of Purpose (SOP).
    
    CRITICAL CONSTRAINT: Do not hallucinate or invent new achievements, skills, or roles.
    Only highlight, re-word, and re-order existing skills, experiences, and projects from the profile.
    """
    prompt = f"""
    You are an expert resume writer and career strategist.
    Your task is to tailor the candidate's application documents for a specific Job Description.
    
    CRITICAL INSTRUCTION (DO NOT VIOLATE):
    - You MUST restrict all claims, achievements, projects, companies, education, and skills strictly to what is present in the Candidate Profile.
    - Do NOT invent, hallucinate, or assume any new projects, technologies, job roles, or degrees that are not explicitly written in the Candidate Profile.
    - If the Job Description requires a skill the candidate doesn't have, DO NOT claim they have it. Instead, emphasize their transferable skills or adjacent technologies they actually possess.
    - You may re-phrase bullet points, prioritize specific achievements, and align the phrasing of actual accomplishments to match keywords in the Job Description.
    
    Candidate Profile:
    {json.dumps(profile, indent=2)}
    
    Job Description / Details:
    {json.dumps(job_details, indent=2)}
    
    Generate three tailored assets:
    1. A tailored JSON version of their resume (same schema, but with refined summaries and experience/project descriptions optimized for the target job).
    2. A professional, compelling Cover Letter.
    3. A tailored Statement of Purpose (SOP) or application statement explaining why they are applying and how their background fits.
    
    Provide the output in JSON format matching this schema:
    {{
        "tailored_resume": {{
            "name": "Same Name",
            "email": "Same Email",
            "phone": "Same Phone",
            "links": {{
                "linkedin": "Same LinkedIn",
                "github": "Same GitHub",
                "portfolio": "Same Portfolio"
            }},
            "summary": "A custom tailored professional summary (max 3 sentences) focusing on why this candidate is a fit.",
            "education": [
                {{
                    "institution": "Same Institution",
                    "degree": "Same Degree",
                    "field": "Same Field",
                    "duration": "Same Duration",
                    "grade": "Same Grade"
                }}
            ],
            "experience": [
                {{
                    "company": "Same Company",
                    "role": "Same Role",
                    "location": "Same Location",
                    "duration": "Same Duration",
                    "description": "Tailored description focusing on tasks relevant to the JD, while sticking to actual facts"
                }}
            ],
            "projects": [
                {{
                    "title": "Same Title",
                    "technologies": ["Same Technologies"],
                    "description": "Tailored project description highlighting JD-relevant aspects and tech stack",
                    "link": "Same Link"
                }}
            ],
            "skills": ["Same Skills or subset of skills, re-ordered to highlight relevant ones first"]
        }},
        "cover_letter": "Complete cover letter text, properly formatted with standard placeholders, referencing their actual experience.",
        "sop": "Complete SOP text, explaining motivation and technical alignment based strictly on their actual projects."
    }}
    """
    
    try:
        client = get_genai_client()
        model_name = get_flash_model_name()
        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.2
            ),
        )
        return json.loads(response.text)
    except Exception as e:
        print(f"Error tailoring documents with Gemini: {e}")
        return {
            "tailored_resume": profile,
            "cover_letter": "AI Cover Letter generation is temporarily unavailable due to Gemini API rate limits/quota exhaustion.",
            "sop": "AI Statement of Purpose generation is temporarily unavailable due to Gemini API rate limits/quota exhaustion.",
            "api_exhausted": True
        }
