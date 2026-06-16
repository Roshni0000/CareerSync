import os
import json
import uuid
import shutil
import re
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from pydantic import BaseModel
from typing import List, Optional, Dict, Any


# Import local modules
from scraper import get_aggregated_opportunities
from ai_engine import (
    extract_text_from_pdf, 
    parse_resume_with_ai, 
    match_opportunity_with_ai, 
    tailor_documents_with_ai
)

app = FastAPI(title="CareerSync - The Anti-Exhaustion Job Engine")

# Path to local database storage
DATA_DIR = os.path.join(os.getcwd(), "data")
PROFILE_PATH = os.path.join(DATA_DIR, "profile.json")
OPPORTUNITIES_CACHE_PATH = os.path.join(DATA_DIR, "opportunities.json")
TAILORED_CACHE_PATH = os.path.join(DATA_DIR, "tailored_cache.json")

# Ensure directories exist
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(os.path.join(os.getcwd(), "uploads"), exist_ok=True)

MATCH_CACHE_PATH = os.path.join(DATA_DIR, "match_cache.json")

def load_match_cache() -> Dict[str, Any]:
    if os.path.exists(MATCH_CACHE_PATH):
        try:
            with open(MATCH_CACHE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_match_cache(cache: Dict[str, Any]):
    with open(MATCH_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)

# Helper functions to load/save profile
def load_profile() -> Dict[str, Any]:
    defaults = {
        "name": "", "email": "", "phone": "",
        "links": {"linkedin": "", "github": "", "portfolio": ""},
        "summary": "",
        "education": [], "experience": [], "projects": [], "skills": [],
        "user_location": "",
        "preferred_locations": [],
        "preferred_job_types": [],
        "preferred_domains": [],
        "expected_salary": ""
    }
    if os.path.exists(PROFILE_PATH):
        try:
            with open(PROFILE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                # merge with defaults to ensure all keys exist
                for k, v in defaults.items():
                    if k not in data:
                        data[k] = v
                return data
        except Exception:
            pass
    return defaults

def save_profile_data(profile: Dict[str, Any]):
    with open(PROFILE_PATH, "w", encoding="utf-8") as f:
        json.dump(profile, f, indent=2, ensure_ascii=False)

# API Endpoints

@app.get("/api/get-profile")
def get_profile():
    return load_profile()

@app.post("/api/save-profile")
def save_profile(profile: Dict[str, Any]):
    save_profile_data(profile)
    return {"status": "success", "profile": profile}

@app.post("/api/parse-resume")
async def parse_resume(file: UploadFile = File(...)):
    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Only PDF files are supported currently.")
        
    temp_path = os.path.join("uploads", f"temp_{uuid.uuid4()}.pdf")
    try:
        # Save uploaded file
        with open(temp_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        # Extract text from PDF
        text = extract_text_from_pdf(temp_path)
        if not text:
            raise HTTPException(status_code=400, detail="Failed to extract text from the resume PDF.")
            
        # Parse resume text with Gemini
        profile_json = parse_resume_with_ai(text)
        
        # Merge with existing profile to preserve preferences
        existing_profile = load_profile()
        
        # Overwrite content fields with parsed details
        for key in ["name", "email", "phone", "links", "summary", "education", "experience", "projects", "skills"]:
            if key in profile_json:
                existing_profile[key] = profile_json[key]
                
        # Parse user location if found, but don't overwrite if empty
        parsed_loc = profile_json.get("user_location", "").strip()
        if parsed_loc:
            existing_profile["user_location"] = parsed_loc
            
        # Save merged profile
        save_profile_data(existing_profile)
        
        return existing_profile
    except Exception as e:
        print(f"Error in parse-resume route: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # Cleanup temp file
        if os.path.exists(temp_path):
            os.remove(temp_path)

@app.get("/api/opportunities")
def get_opportunities(keyword: Optional[str] = None, platforms: Optional[str] = None):
    """
    Aggregates opportunities from requested platforms, applies location constraints,
    and runs Gemini match analyzer on the top opportunities to calculate match percentages and reasons.
    """
    profile = load_profile()
    
    # 1. Parse platforms parameter
    selected_platforms = None
    if platforms:
        selected_platforms = [p.strip() for p in platforms.split(",") if p.strip()]
        
    # 2. Determine scraping keyword
    search_keyword = keyword
    if not search_keyword:
        # Try to use user's preferred domains first
        if profile.get("preferred_domains") and len(profile["preferred_domains"]) > 0:
            search_keyword = profile["preferred_domains"][0]
        # Try to use user's first skill as fallback
        elif profile.get("skills") and len(profile["skills"]) > 0:
            search_keyword = profile["skills"][0]
        else:
            search_keyword = "python"  # Default fallback
            
    print(f"Aggregating opportunities for '{search_keyword}' on platforms: {selected_platforms or 'All'}")
    raw_jobs = get_aggregated_opportunities(search_keyword, selected_platforms)
    
    if not raw_jobs:
        return []
        
    # 3. Local Keyword / Skill Matching & Location Filtering
    user_skills = [s.lower() for s in profile.get("skills", [])]
    user_loc = profile.get("user_location", "").strip().lower()
    pref_locs = [l.strip().lower() for l in profile.get("preferred_locations", []) if l.strip()]
    
    # If no preferred locations are set but home location exists, set defaults
    if not pref_locs and user_loc:
        pref_locs = [user_loc, "remote", "work from home"]
        
    matched_results = []
    
    for job in raw_jobs:
        # Check Location Compatibility
        location_mismatch = False
        mismatch_reason = ""
        
        job_loc_lower = job["location"].lower()
        is_job_remote = "remote" in job_loc_lower or "work from home" in job_loc_lower or "wfh" in job_loc_lower
        
        if pref_locs:
            # Check if any preferred location is in the job location string
            has_overlap = False
            for pl in pref_locs:
                pl_lower = pl.strip().lower()
                if pl_lower in job_loc_lower:
                    has_overlap = True
                    break
                # Handle remote synonyms
                if is_job_remote and pl_lower in ["remote", "work from home", "wfh"]:
                    has_overlap = True
                    break
            
            # If no match, mark mismatch
            if not has_overlap:
                location_mismatch = True
                mismatch_reason = f"Location mismatch: Job is in {job['location']}, but your preferred locations are: {', '.join(profile.get('preferred_locations', []))}."
                
        # Calculate a basic text-overlap match score
        job_text = (job["title"] + " " + job["description"] + " " + " ".join(job["skills"])).lower()
        
        matched_skills = []
        for skill in user_skills:
            if re.search(r'\b' + re.escape(skill) + r'\b', job_text):
                matched_skills.append(skill)
                
        # Basic overlap ratio
        if user_skills:
            local_score = int((len(matched_skills) / max(len(job["skills"]), 1)) * 50) + int((len(matched_skills) / len(user_skills)) * 50)
            local_score = min(max(local_score, 10), 100)  # Clamp between 10 and 100
        else:
            local_score = 40  # Default score if no user skills
            
        job_copy = job.copy()
        job_copy["local_score"] = local_score
        job_copy["matched_skills_local"] = matched_skills
        job_copy["location_mismatch"] = location_mismatch
        job_copy["mismatch_reason"] = mismatch_reason
        matched_results.append(job_copy)
        
    # Sort by local match score descending
    matched_results.sort(key=lambda x: x["local_score"], reverse=True)
    
    # Keep top 12 opportunities to evaluate
    top_jobs = matched_results[:12]
    
    # 4. Apply Gemini AI Matching or Penalty fallbacks
    final_opportunities = []
    
    # Load match cache
    match_cache = load_match_cache()
    # Create profile key based on skills and location to invalidate cache if profile changes
    profile_key = f"{','.join(sorted(profile.get('skills', [])))}_{profile.get('user_location', '')}"
    
    # Count how many AI matches we've called to stay in limits
    ai_calls = 0
    
    for idx, job in enumerate(top_jobs):
        if job["location_mismatch"]:
            # If location mismatch, force a low score and explain why without calling Gemini
            job["score"] = 15
            job["reasons"] = [
                job["mismatch_reason"],
                "Job location is incompatible with your profile preferences."
            ]
            job["gaps"] = ["Compatible Location"]
        else:
            # Check cache first
            job_id = job["id"]
            cache_entry = match_cache.get(job_id)
            if cache_entry and cache_entry.get("profile_key") == profile_key:
                job["score"] = cache_entry["score"]
                job["reasons"] = cache_entry["reasons"]
                job["gaps"] = cache_entry["gaps"]
            elif ai_calls < 3 and len(profile.get("skills", [])) > 0:
                try:
                    ai_calls += 1
                    ai_match = match_opportunity_with_ai(profile, job)
                    job["score"] = ai_match.get("score", job["local_score"])
                    job["reasons"] = ai_match.get("reasons", ["Matches your core skill set."])
                    job["gaps"] = ai_match.get("gaps", [])
                    
                    # Update cache
                    match_cache[job_id] = {
                        "profile_key": profile_key,
                        "score": job["score"],
                        "reasons": job["reasons"],
                        "gaps": job["gaps"]
                    }
                except Exception:
                    job["score"] = job["local_score"]
                    job["reasons"] = ["Matches your skills: " + ", ".join(job["matched_skills_local"])]
                    job["gaps"] = []
            else:
                # Fallback to local matching details
                job["score"] = job["local_score"]
                job["reasons"] = [
                    f"Matches {len(job['matched_skills_local'])} of your skills: {', '.join(job['matched_skills_local'])}",
                    "Job location matches" if job["location"] != "Remote / Not Specified" else "Remote opportunity"
                ]
                job["gaps"] = [s for s in job["skills"] if s.lower() not in user_skills][:3]
            
        final_opportunities.append(job)
        
    # Re-sort final list by score descending (so mismatches fall to the bottom)
    final_opportunities.sort(key=lambda x: x["score"], reverse=True)
    
    # Save cache files
    save_match_cache(match_cache)
        
    # Re-sort final list by score descending (so mismatches fall to the bottom)
    final_opportunities.sort(key=lambda x: x["score"], reverse=True)
    
    # Save cache
    with open(OPPORTUNITIES_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(final_opportunities, f, indent=2, ensure_ascii=False)
        
    return final_opportunities

@app.post("/api/tailor")
def tailor_document(payload: Dict[str, Any]):
    """
    Accepts target job details and user profile, and returns tailored resume, cover letter, and SOP.
    """
    profile = payload.get("profile") or load_profile()
    job_details = payload.get("job_details")
    
    if not job_details:
        raise HTTPException(status_code=400, detail="Missing job_details in request body.")
        
    try:
        tailored_data = tailor_documents_with_ai(profile, job_details)
        
        # Save to cache
        with open(TAILORED_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(tailored_data, f, indent=2, ensure_ascii=False)
            
        return tailored_data
    except Exception as e:
        print(f"Error in tailor route: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Serve index.html as fallback or root
@app.get("/", response_class=HTMLResponse)
def get_home():
    index_path = os.path.join("static", "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>Welcome to CareerSync Server</h1><p>Static files not found yet.</p>"

# Serve sub-pages cleanly
@app.get("/{page_name}.html", response_class=HTMLResponse)
def get_page(page_name: str):
    page_path = os.path.join("static", f"{page_name}.html")
    if os.path.exists(page_path):
        with open(page_path, "r", encoding="utf-8") as f:
            return f.read()
    raise HTTPException(status_code=404, detail="Page not found")
