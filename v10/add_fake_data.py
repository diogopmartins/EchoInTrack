#!/usr/bin/env python3
"""
Script to add realistic fake/sample data to the EchoInTrack database.
Generates data day-by-day with multiple requests per day from different pathways,
with the majority completed on time.
"""
import sqlite3
import random
from datetime import datetime, timedelta
import pytz

DB_PATH = 'echo.db'

# Sample data
PATHWAYS = ['PURPLE PATHWAY', 'RED PATHWAY', 'AMBER PATHWAY', 'GREEN PATHWAY', 'REJECTED']
# Pathway distribution (more realistic - fewer purple, more amber)
PATHWAY_WEIGHTS = {
    'PURPLE PATHWAY': 0.10,  # 10% - urgent cases
    'RED PATHWAY': 0.25,     # 25% - high priority
    'AMBER PATHWAY': 0.40,   # 40% - most common
    'GREEN PATHWAY': 0.10,   # 10% - declined
    'REJECTED': 0.15         # 15% - rejected
}

SAMPLE_NAMES = [
    'John Smith', 'Jane Doe', 'Robert Johnson', 'Emily Williams', 'Michael Brown',
    'Sarah Davis', 'David Miller', 'Jessica Wilson', 'Christopher Moore', 'Amanda Taylor',
    'Daniel Anderson', 'Lisa Thomas', 'Matthew Jackson', 'Michelle White', 'Andrew Harris',
    'Ashley Martin', 'James Thompson', 'Stephanie Garcia', 'Joseph Martinez', 'Nicole Robinson',
    'William Clark', 'Patricia Lewis', 'Richard Walker', 'Linda Hall', 'Thomas Allen',
    'Barbara Young', 'Charles King', 'Elizabeth Wright', 'Joseph Lopez', 'Jennifer Hill'
]
SAMPLE_WARDS = [
    'A&E', 'Critical Care', 'Heart Centre', 'Cedar', 'Hawthorn', 
    'Balmoral', 'Becket', 'Compton', 'Eleanor', 'Victoria',
    'Cedar', 'Rowan', 'Willow', 'Spencer', 'Talbot Butler'
]

def get_uk_time():
    """Get current time in UK timezone"""
    return datetime.now(pytz.timezone('Europe/London'))

def add_working_hours_uk(start_date, hours):
    """Add working hours, skipping weekends"""
    if not start_date.tzinfo:
        start_date = pytz.timezone('Europe/London').localize(start_date)
    
    current_date = start_date
    remaining_hours = hours
    
    while remaining_hours > 0:
        current_date += timedelta(hours=1)
        if current_date.weekday() < 5:  # Monday-Friday
            remaining_hours -= 1
    
    return current_date

def choose_pathway():
    """Choose pathway based on weighted distribution"""
    rand = random.random()
    cumulative = 0
    for pathway, weight in PATHWAY_WEIGHTS.items():
        cumulative += weight
        if rand <= cumulative:
            return pathway
    return 'AMBER PATHWAY'  # fallback

def generate_request_id(year_suffix, sequence):
    """Generate request ID in format YY.XXXX"""
    return f"{year_suffix}.{str(sequence).zfill(4)}"

def add_realistic_fake_data(days_back=30, requests_per_day_min=5, requests_per_day_max=15):
    """
    Add realistic fake data day by day.
    
    Args:
        days_back: Number of days to generate data for
        requests_per_day_min: Minimum requests per day
        requests_per_day_max: Maximum requests per day
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Get current year suffix
    current_year = datetime.now().year % 100
    
    # Get the highest existing request ID for this year
    c.execute("SELECT request_id FROM echo_requests WHERE request_id LIKE ? ORDER BY request_id DESC LIMIT 1", 
              (f"{current_year}.%",))
    result = c.fetchone()
    
    if result:
        last_id = result[0]
        last_seq = int(last_id.split('.')[1])
        start_seq = last_seq + 1
    else:
        start_seq = 1
    
    uk_now = get_uk_time()
    total_requests = 0
    sequence = start_seq
    
    print(f"Generating realistic data for the last {days_back} days...")
    print(f"Requests per day: {requests_per_day_min}-{requests_per_day_max}")
    print()
    
    # Generate data day by day
    for day_offset in range(days_back, -1, -1):  # From days_back days ago to today
        # Calculate date for this day
        if day_offset == 0:
            # Today - only morning hours
            day_start = uk_now.replace(hour=8, minute=0, second=0, microsecond=0)
            day_end = uk_now
        else:
            # Past days - full working day (8 AM to 6 PM)
            day_date = (uk_now - timedelta(days=day_offset)).date()
            day_start = pytz.timezone('Europe/London').localize(
                datetime.combine(day_date, datetime.min.time().replace(hour=8))
            )
            day_end = pytz.timezone('Europe/London').localize(
                datetime.combine(day_date, datetime.min.time().replace(hour=18))
            )
        
        # Skip weekends for request generation (but allow some weekend requests)
        if day_start.weekday() >= 5 and random.random() > 0.2:  # 20% chance on weekends
            continue
        
        # Number of requests for this day
        num_requests = random.randint(requests_per_day_min, requests_per_day_max)
        
        # Generate requests for this day
        for req_num in range(num_requests):
            # Random time during the day
            time_offset = random.uniform(0, (day_end - day_start).total_seconds())
            request_time = day_start + timedelta(seconds=time_offset)
            
            # Choose pathway (weighted)
            pathway = choose_pathway()
            
            # Calculate expected time based on pathway
            expected_time = request_time
            if pathway == 'PURPLE PATHWAY':
                expected_time = add_working_hours_uk(request_time, 1)
            elif pathway == 'RED PATHWAY':
                expected_time = add_working_hours_uk(request_time, 24)
            elif pathway == 'AMBER PATHWAY':
                expected_time = add_working_hours_uk(request_time, 72)
            
            # Determine status and completion
            # For older requests (more than 3 days ago), most should be completed
            # For recent requests, fewer pending - most already completed
            days_since_request = (uk_now - request_time).days
            hours_since_request = (uk_now - request_time).total_seconds() / 3600
            
            if days_since_request > 3:
                # Old requests: 98% completed
                status = 'completed' if random.random() < 0.98 else 'pending'
            elif days_since_request > 1:
                # 1-3 days ago: 90% completed
                status = 'completed' if random.random() < 0.90 else 'pending'
            elif days_since_request == 1:
                # Yesterday: 85% completed, 15% pending
                status = 'completed' if random.random() < 0.85 else 'pending'
            else:
                # Today: Most completed already, only a few pending
                # If request was made more than 4 hours ago, likely completed
                if hours_since_request > 4:
                    # Older today requests: 80% completed
                    status = 'completed' if random.random() < 0.80 else 'pending'
                else:
                    # Very recent requests (last 4 hours): 60% completed, 40% pending
                    status = 'completed' if random.random() < 0.60 else 'pending'
            
            # Completion time if completed
            completion_time = None
            if status == 'completed':
                # Most (85%) completed on time or slightly early
                # Some (10%) completed slightly late (within 25% of expected time)
                # Few (5%) completed significantly late
                rand = random.random()
                
                if rand < 0.85:
                    # Completed on time or early (between request_time and expected_time)
                    if expected_time > request_time:
                        completion_time = request_time + timedelta(
                            seconds=random.uniform(0, (expected_time - request_time).total_seconds())
                        )
                    else:
                        completion_time = request_time + timedelta(hours=random.uniform(0.5, 2))
                elif rand < 0.95:
                    # Completed slightly late (up to 25% over expected time)
                    if expected_time > request_time:
                        late_by = (expected_time - request_time).total_seconds() * 0.25
                        completion_time = expected_time + timedelta(seconds=random.uniform(0, late_by))
                    else:
                        completion_time = expected_time + timedelta(hours=random.uniform(0, 6))
                else:
                    # Completed significantly late
                    if expected_time > request_time:
                        late_by = (expected_time - request_time).total_seconds() * random.uniform(0.5, 2.0)
                        completion_time = expected_time + timedelta(seconds=late_by)
                    else:
                        completion_time = expected_time + timedelta(hours=random.uniform(6, 48))
                
                # Ensure completion_time is not in the future
                if completion_time > uk_now:
                    completion_time = uk_now - timedelta(hours=random.uniform(0, 12))
            
            # Random patient info
            name = random.choice(SAMPLE_NAMES)
            mrn = f"MRN{random.randint(100000, 999999)}"
            ward = random.choice(SAMPLE_WARDS)
            
            # Random notes (sometimes empty)
            notes = ""
            if random.random() > 0.6:
                note_options = [
                    "Patient stable",
                    "Follow-up required",
                    "No special notes",
                    "Monitor closely",
                    "Routine check",
                    "Urgent review needed",
                    "Post-operative",
                    "Pre-operative assessment"
                ]
                notes = random.choice(note_options)
            
            request_id = generate_request_id(current_year, sequence)
            triage_date = request_time.date()
            
            # Insert into database
            c.execute('''
                INSERT INTO echo_requests 
                (request_id, pathway, request_time, expected_time, status, triage_date, 
                 completion_time, notes, name, mrn, ward)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                request_id,
                pathway,
                request_time.isoformat(),
                expected_time.isoformat(),
                status,
                triage_date,
                completion_time.isoformat() if completion_time else None,
                notes,
                name,
                mrn,
                ward
            ))
            
            sequence += 1
            total_requests += 1
        
        if day_offset % 5 == 0 or day_offset == 0:
            print(f"  Day {day_offset} days ago: {num_requests} requests")
    
    conn.commit()
    conn.close()
    
    print()
    print(f"✓ Successfully added {total_requests} realistic echo requests!")
    print(f"\nYou can now view them at: http://localhost:8282")

if __name__ == '__main__':
    import sys
    
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    min_per_day = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    max_per_day = int(sys.argv[3]) if len(sys.argv) > 3 else 15
    
    add_realistic_fake_data(days_back=days, requests_per_day_min=min_per_day, requests_per_day_max=max_per_day)
