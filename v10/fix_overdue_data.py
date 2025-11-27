#!/usr/bin/env python3
"""
Script to fix overdue requests in the database by either:
1. Marking them as completed, or
2. Updating their expected_time to be in the future
"""
import sqlite3
from datetime import datetime, timedelta
import pytz

DB_PATH = 'echo.db'

def get_uk_time():
    """Get current time in UK timezone"""
    return datetime.now(pytz.timezone('Europe/London'))

def fix_overdue_requests(mark_completed=True, completion_rate=0.7):
    """
    Fix overdue requests.
    
    Args:
        mark_completed: If True, mark overdue requests as completed (default: True)
        completion_rate: Percentage of overdue requests to mark as completed (0.0-1.0)
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = get_uk_time()
    now_str = now.isoformat()
    
    # Find overdue requests
    c.execute('''
        SELECT id, request_id, pathway, expected_time, request_time
        FROM echo_requests
        WHERE status = 'pending'
          AND pathway NOT IN ('GREEN PATHWAY', 'REJECTED')
          AND datetime(expected_time) < datetime(?)
    ''', (now_str,))
    
    overdue_requests = c.fetchall()
    print(f"Found {len(overdue_requests)} overdue requests")
    
    if not overdue_requests:
        print("No overdue requests to fix!")
        conn.close()
        return
    
    if mark_completed:
        # Mark a percentage as completed
        num_to_complete = int(len(overdue_requests) * completion_rate)
        completed_count = 0
        
        for i, (req_id, req_id_str, pathway, expected_time, request_time) in enumerate(overdue_requests):
            if i < num_to_complete:
                # Mark as completed with completion time between expected_time and now
                expected_dt = datetime.fromisoformat(expected_time.replace('Z', '+00:00'))
                if expected_dt.tzinfo is None:
                    expected_dt = pytz.UTC.localize(expected_dt)
                
                # Completion time: expected_time + some hours (but not in future)
                hours_late = random.randint(1, min(48, int((now - expected_dt).total_seconds() / 3600)))
                completion_time = expected_dt + timedelta(hours=hours_late)
                
                if completion_time > now:
                    completion_time = now - timedelta(hours=random.randint(1, 24))
                
                c.execute('''
                    UPDATE echo_requests
                    SET status = 'completed', completion_time = ?
                    WHERE id = ?
                ''', (completion_time.isoformat(), req_id))
                completed_count += 1
            else:
                # Update expected_time to be in the future (extend deadline)
                expected_dt = datetime.fromisoformat(expected_time.replace('Z', '+00:00'))
                if expected_dt.tzinfo is None:
                    expected_dt = pytz.UTC.localize(expected_dt)
                
                # Extend by 1-3 days
                new_expected = now + timedelta(days=random.randint(1, 3), hours=random.randint(0, 8))
                
                c.execute('''
                    UPDATE echo_requests
                    SET expected_time = ?
                    WHERE id = ?
                ''', (new_expected.isoformat(), req_id))
        
        conn.commit()
        print(f"✓ Marked {completed_count} overdue requests as completed")
        print(f"✓ Extended deadline for {len(overdue_requests) - completed_count} overdue requests")
    else:
        # Just extend all deadlines
        for req_id, req_id_str, pathway, expected_time, request_time in overdue_requests:
            new_expected = now + timedelta(days=random.randint(1, 3), hours=random.randint(0, 8))
            c.execute('''
                UPDATE echo_requests
                SET expected_time = ?
                WHERE id = ?
            ''', (new_expected.isoformat(), req_id))
        
        conn.commit()
        print(f"✓ Extended deadlines for {len(overdue_requests)} overdue requests")
    
    conn.close()
    print("\nOverdue requests have been fixed!")

if __name__ == '__main__':
    import random
    import sys
    
    mark_completed = True
    if len(sys.argv) > 1 and sys.argv[1] == '--extend-only':
        mark_completed = False
    
    fix_overdue_requests(mark_completed=mark_completed)

