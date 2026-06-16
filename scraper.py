import os
import json
import requests
from bs4 import BeautifulSoup
import urllib.parse
import time

def scrape_internshala(keyword=None):
    """
    Scrapes the first page of Internshala internships for a given keyword.
    Returns a list of dictionaries representing the internships.
    """
    if keyword:
        # URL encode keyword
        encoded_keyword = urllib.parse.quote(keyword)
        url = f"https://internshala.com/internships/keywords-{encoded_keyword}"
    else:
        url = "https://internshala.com/internships"
        
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code != 200:
            print(f"Failed to scrape {url}. Status code: {response.status_code}")
            return []
            
        soup = BeautifulSoup(response.content, 'html.parser')
        cards = soup.find_all(class_='individual_internship')
        
        results = []
        for card in cards:
            try:
                # 1. Title and Link
                title_elem = card.find('a', class_='job-title-href')
                if not title_elem:
                    continue
                title = title_elem.text.strip()
                link = "https://internshala.com" + title_elem['href']
                
                # Extract an ID from link or card attribute
                job_id = card.get('internshipid') or link.split('/')[-1]
                
                # 2. Company
                company_elem = card.find(class_='company-name')
                company = company_elem.text.strip() if company_elem else "Unknown Company"
                
                # 3. Location
                location_elem = card.find(class_='locations')
                location = location_elem.text.strip() if location_elem else "Remote / Not Specified"
                
                # 4. Stipend
                stipend_elem = card.find(class_='stipend')
                stipend = stipend_elem.text.strip() if stipend_elem else "Not Specified"
                
                # 5. Duration
                duration = "Not Specified"
                # Find the parent row item that contains the calendar icon
                calendar_icon = card.find('i', class_='ic-16-calendar')
                if calendar_icon and calendar_icon.parent:
                    duration = calendar_icon.parent.text.strip()
                else:
                    # Alternative duration search
                    for item in card.find_all(class_='row-1-item'):
                        if 'month' in item.text.lower() or 'week' in item.text.lower() or 'duration' in item.text.lower():
                            duration = item.text.strip()
                            break
                            
                # 6. Skills
                skills = []
                skills_elems = card.find_all(class_='job_skill')
                for skill_elem in skills_elems:
                    skills.append(skill_elem.text.strip())
                    
                # 7. Description / Summary
                desc_container = card.find(class_='about_job')
                description = ""
                if desc_container:
                    desc_text = desc_container.find(class_='text')
                    if desc_text:
                        description = desc_text.text.strip()
                        
                # 8. Meta / Posted time
                posted_time = "Recently"
                posted_elem = card.find(class_='status-success')
                if posted_elem:
                    posted_time = posted_elem.text.strip()
                else:
                    # Try looking for other labels
                    label_containers = card.find_all(class_='detail-row-2')
                    for label in label_containers:
                        if label:
                            posted_time = label.text.strip()
                            break
                
                results.append({
                    "id": job_id,
                    "title": title,
                    "company": company,
                    "location": location,
                    "stipend": stipend,
                    "duration": duration,
                    "skills": skills,
                    "description": description,
                    "link": link,
                    "posted_time": posted_time,
                    "source": "Internshala"
                })
            except Exception as inner_e:
                print(f"Error parsing card: {inner_e}")
                continue
                
        return results
    except Exception as e:
        print(f"Error scraping Internshala for {keyword}: {e}")
        return []

def get_aggregated_opportunities(keyword=None, platforms=None):
    """
    Aggregates opportunities from multiple platforms.
    For Internshala, scrapes live.
    For Unstop, LinkedIn, and Naukri, fetches from the curated local database.
    """
    if not platforms:
        platforms = ["Internshala", "Unstop", "LinkedIn", "Naukri"]
        
    all_opportunities = []
    
    # 1. Fetch from live Internshala scraper if requested
    if "Internshala" in platforms:
        print(f"Scraping live Internshala for: {keyword}")
        internshala_jobs = scrape_internshala(keyword)
        all_opportunities.extend(internshala_jobs)
        
    # 2. Fetch from curated local database for Unstop, LinkedIn, and Naukri
    db_path = os.path.join(os.getcwd(), "data", "platforms_db.json")
    if os.path.exists(db_path):
        try:
            with open(db_path, "r", encoding="utf-8") as f:
                db_jobs = json.load(f)
                
            filtered_db_jobs = []
            for job in db_jobs:
                # Filter by source platform
                if job.get("source") not in platforms:
                    continue
                    
                # If keyword is provided, filter by keyword (case-insensitive)
                if keyword:
                    k_lower = keyword.lower()
                    title_match = k_lower in job.get("title", "").lower()
                    company_match = k_lower in job.get("company", "").lower()
                    desc_match = k_lower in job.get("description", "").lower()
                    loc_match = k_lower in job.get("location", "").lower()
                    skill_match = any(k_lower in s.lower() for s in job.get("skills", []))
                    
                    if not (title_match or company_match or desc_match or loc_match or skill_match):
                        continue
                        
                filtered_db_jobs.append(job)
                
            all_opportunities.extend(filtered_db_jobs)
        except Exception as e:
            print(f"Error reading platforms database: {e}")
            
    return all_opportunities

if __name__ == "__main__":
    print("Testing aggregator...")
    res = get_aggregated_opportunities("python", ["Internshala", "Unstop", "LinkedIn"])
    print(f"Total opportunities aggregated: {len(res)}")
    for j in res[:3]:
        print(f"- [{j['source']}] {j['title']} at {j['company']} ({j['location']})")
