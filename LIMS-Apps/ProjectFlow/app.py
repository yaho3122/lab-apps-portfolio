from flask import Flask, render_template, request, redirect, url_for, jsonify, send_file, g, flash, send_from_directory, session, render_template_string
import json
import os
import threading
from datetime import date, timedelta, datetime
import io

# Personnel Management
LAB_MEMBERS_FILE = 'lab_members.json'
file_lock = threading.Lock() # Global lock for JSON operations

def atomic_save_json(file_path, data):
    """Saves JSON data atomically using a temporary file and a thread lock."""
    with file_lock:
        temp_file = file_path + '.tmp'
        try:
            with open(temp_file, 'w') as f:
                json.dump(data, f, indent=4)
            # Atomic rename (overwrites destination)
            os.replace(temp_file, file_path)
            return True
        except Exception as e:
            print(f"[ERROR] Atomic save failed for {file_path}: {e}")
            if os.path.exists(temp_file):
                os.remove(temp_file)
            return False

def load_lab_members():
    if os.path.exists(LAB_MEMBERS_FILE):
        try:
            with open(LAB_MEMBERS_FILE, 'r') as f:
                return json.load(f)
        except:
            return ["manager", "user1"]
    return ["manager", "user1"]

def save_lab_members(members):
    return atomic_save_json(LAB_MEMBERS_FILE, members)

import csv
import sqlite3
import zipfile
import shutil
import os
import signal
import sys
import math
import threading
import atexit
from functools import wraps
from dotenv import load_dotenv
from werkzeug.security import check_password_hash, generate_password_hash

# Load environment variables from .env file if it exists
load_dotenv()

app = Flask(__name__)
# Security: Use environment variables for sensitive settings on GitHub
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'dev-key-for-github-change-this')
DATABASE = 'database.db'
EDIT_DATA_FOLDER = 'edit_data'
PROGENY_EDIT_DATA_FOLDER = 'progeny_edit_data'

# --- RBAC Decorator ---
def requires_role(*roles):
    def wrapper(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            if not session.get('logged_in'):
                return redirect(url_for('login'))
            if session.get('role') not in roles:
                return render_template_string('<h1 style="color:red;text-align:center;margin-top:100px;">Access Denied: Insufficient Privileges</h1>'), 403
            return f(*args, **kwargs)
        return wrapped
    return wrapper

if not os.path.exists(EDIT_DATA_FOLDER):
    os.makedirs(EDIT_DATA_FOLDER)
if not os.path.exists(PROGENY_EDIT_DATA_FOLDER):
    os.makedirs(PROGENY_EDIT_DATA_FOLDER)

@app.before_request
def require_login():
    # List of endpoints that don't require login
    public_endpoints = ['login', 'static']
    if request.endpoint and not any(pub in request.endpoint for pub in public_endpoints):
        if not session.get('logged_in'):
            return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        user = query_db('SELECT * FROM users WHERE username = ?', [username], one=True)
        
        if user and check_password_hash(user['password_hash'], password):
            session['logged_in'] = True
            session['username'] = user['username']
            session['role'] = user['role']
            return redirect(url_for('index'))
        else:
            return render_template_string('<h1 style="color:red;text-align:center;margin-top:100px;">Invalid credentials</h1>')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

def init_db():
    with app.app_context():
        db = get_db()
        with app.open_resource('schema.sql', mode='r') as f:
            db.cursor().executescript(f.read())
        
        # Create default admin user
        default_admin = os.environ.get('APP_USERNAME', 'admin')
        # Default pass is 'admin' for first-time login
        default_pass = 'admin'
        hashed_pass = generate_password_hash(default_pass, method='scrypt')
        
        db.execute('INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)',
                   [default_admin, hashed_pass, 'admin'])
        db.commit()

def query_db(query, args=(), one=False):
    cur = get_db().execute(query, args)
    rv = cur.fetchall()
    cur.close()
    return (rv[0] if rv else None) if one else rv

@app.cli.command('initdb')
def initdb_command():
    """Initializes the database."""
    init_db()
    print('Initialized the database with default admin user.')

WORKFLOWS_FILE = 'workflows.json'

def load_workflows():
    if os.path.exists(WORKFLOWS_FILE):
        try:
            with open(WORKFLOWS_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading workflows: {e}")
    
    # Default workflow if file doesn't exist
    default_workflows = {
        "transformation": {
            "name": "Transformation Project",
            "tasks": [
                { "key": "start", "name": "Transformation Task", "description": "Initial kick-off task for the transformation project.", "offset": { "value": 0, "unit": "days" } },
                { "key": "hyg", "name": "HYG", "description": "Hygiene and data quality task.", "offset": { "value": 1, "unit": "days" } },
                { "key": "pre", "name": "Pre", "description": "Pre-production readiness check. For CSV export, enter data as \"total,transformed,regen\" (e.g., \"500,250,50\").", "offset": { "value": 3, "unit": "weeks" } },
                { "key": "rs", "name": "RS", "description": "Release strategy and sign-off.", "offset": { "value": 1, "unit": "weeks" } },
                { "key": "end", "name": "End of Project", "description": "Final project wrap-up and closure.", "offset": { "value": 6, "unit": "weeks" } },
            ]
        }
    }
    save_workflows(default_workflows)
    return default_workflows

def save_workflows(workflows_data):
    return atomic_save_json(WORKFLOWS_FILE, workflows_data)

# Initialize workflows
workflows = load_workflows()

@app.route('/api/save_workflow', methods=['POST'])
@requires_role('admin')
def api_save_workflow():
    global workflows
    data = request.get_json()
    workflow_id = data.get('id')
    workflow_config = data.get('config')
    
    if not workflow_id or not workflow_config:
        return jsonify(success=False, error="Missing ID or Config"), 400
    
    workflows[workflow_id] = workflow_config
    if save_workflows(workflows):
        return jsonify(success=True)
    return jsonify(success=False, error="Failed to save to file"), 500

@app.route('/api/delete_workflow/<workflow_id>', methods=['POST'])
@requires_role('admin')
def api_delete_workflow(workflow_id):
    global workflows
    if workflow_id in workflows:
        del workflows[workflow_id]
        if save_workflows(workflows):
            return jsonify(success=True)
    return jsonify(success=False, error="Workflow not found or failed to save"), 404

@app.route('/api/search_projects')
def api_search_projects():
    q = request.args.get('q', '')
    if len(q) < 2:
        return jsonify([])
    
    # Find projects matching name or description
    # Join with start task to get the jump date
    query = """
        SELECT DISTINCT projectName, workflowType, 
               (SELECT date FROM tasks t2 WHERE t2.workflowId = tasks.workflowId 
                AND (t2.workflowTaskKey IN ('start', 'Streaking', 'Transformation')) 
                ORDER BY t2.date ASC LIMIT 1) as startDate
        FROM tasks 
        WHERE projectName LIKE ? OR projectDescription LIKE ? 
        ORDER BY startDate DESC LIMIT 10
    """
    rows = query_db(query, [f'%{q}%', f'%{q}%'])
    results = []
    for r in rows:
        results.append({
            'name': r['projectName'],
            'type': r['workflowType'],
            'date': r['startDate']
        })
    return jsonify(results)
@app.route('/api/add_lab_member', methods=['POST'])
@requires_role('admin')
def api_add_lab_member():
    data = request.get_json()
    name = data.get('name')
    if not name:
        return jsonify(success=False, error="Missing name"), 400
    
    members = load_lab_members()
    if name not in members:
        members.append(name)
        save_lab_members(members)
        return jsonify(success=True)
    return jsonify(success=False, error="Member already exists"), 400

@app.route('/api/delete_lab_member/<name>', methods=['POST'])
@requires_role('admin')
def api_delete_lab_member(name):
    members = load_lab_members()
    if name in members:
        members.remove(name)
        save_lab_members(members)
        return jsonify(success=True)
    return jsonify(success=False, error="Member not found"), 404

# Pastel Project Colors
project_colors = [
    '#FFB3BA', # Pastel Pink
    '#BAFFC9', # Pastel Green
    '#BAE1FF', # Pastel Blue
    '#FFFFBA', # Pastel Yellow
    '#FFDFBA', # Pastel Orange
    '#E0BBE4', # Pastel Purple
    '#D4F0F0'  # Pastel Teal
]

def add_offset_to_date(start_date, offset_value, offset_unit):
    if offset_unit == 'days':
        return start_date + timedelta(days=offset_value)
    elif offset_unit == 'weeks':
        return start_date + timedelta(weeks=offset_value)
    return start_date

def get_next_workflow_id():
    result = query_db('SELECT MAX(workflowId) FROM tasks', one=True)
    if result[0] is None:
        return 1
    return result[0] + 1

def get_task_csv_status(task):
    global workflows
    wf = workflows.get(task.get('workflowType'))
    if wf:
        task_template = next((t for t in wf['tasks'] if t['key'] == task.get('workflowTaskKey')), None)
        return task_template.get('csv_config') is not None if task_template else False
    return False

@app.route('/')
def index():
    global workflows
    view_mode = request.args.get('view', 'calendar')
    current_date_str = request.args.get('date')
    if current_date_str:
        current_date = datetime.strptime(current_date_str, '%Y-%m-%d').date()
    else:
        current_date = date.today()

    # Initialize all variables that might be passed to render_template
    calendar_data = []
    prev_month = None
    next_month = None
    projects = []
    timeline_start = None
    timeline_end = None
    total_days = None
    kpis = {}
    unique_traits = []
    filter_trait = request.args.get('filter_trait')
    filter_workflow_type = request.args.get('filter_workflow_type')
    unique_descriptions = []
    filter_descriptions = request.args.getlist('filter_description') # Changed to getlist
    filter_assigned_to = request.args.get('filter_assigned_to')
    project_v2_status = {}

    # Load lab members
    lab_members = load_lab_members()

    # tasks is used in all views, so it can be fetched once
    tasks_rows = query_db('SELECT * FROM tasks')
    tasks = []
    task_csv_status = {}
    
    workflows = load_workflows()

    for row in tasks_rows:
        t = dict(row)
        tasks.append(t)
        task_csv_status[t['id']] = get_task_csv_status(t)

    if view_mode == 'calendar':
        # Apply filters for calendar
        filtered_calendar_tasks = tasks
        if filter_assigned_to:
            filtered_calendar_tasks = [t for t in filtered_calendar_tasks if filter_assigned_to in (t.get('assigned_to') or '').split(',')]
        if filter_workflow_type:
            filtered_calendar_tasks = [t for t in filtered_calendar_tasks if t.get('workflowType') == filter_workflow_type]

        # Identify "Pre" tasks across all workflow types for V2 status indicator
        pre_tasks = [t for t in tasks if t.get('workflowTaskKey') in ['pre', 'Pre-H', 'Pre-S', 'Pre-Regeneration'] or (t.get('name') and t['name'].startswith('Pre'))]
        for pre_task in pre_tasks:
            if pre_task.get('workflowId'):
                parsed_data = parse_pre_description(pre_task['description'])
                if parsed_data and 'v2' in parsed_data and parsed_data['v2'] is not None:
                    project_v2_status[pre_task['workflowId']] = True
                else:
                    project_v2_status[pre_task['workflowId']] = False

        calendar_data = get_calendar_data(current_date, filtered_calendar_tasks)
        prev_month = (current_date.replace(day=1) - timedelta(days=1)).strftime('%Y-%m-%d')
        next_month = (current_date.replace(day=28) + timedelta(days=4)).strftime('%Y-%m-01')

    elif view_mode == 'weekly':
        # Apply assignment filter
        if filter_assigned_to:
            filtered_tasks = [t for t in tasks if filter_assigned_to in (t.get('assigned_to') or '').split(',')]
        else:
            filtered_tasks = tasks

        # Calculate week range (Sunday to Saturday)
        start_of_week = current_date - timedelta(days=current_date.isoweekday() % 7)
        calendar_data = []
        for i in range(7):
            day = start_of_week + timedelta(days=i)
            day_tasks = [t for t in filtered_tasks if t['date'] == day.isoformat()]
            calendar_data.append({'date': day, 'tasks': day_tasks, 'is_today': day == date.today()})
        
        prev_month = (current_date - timedelta(days=7)).strftime('%Y-%m-%d')
        next_month = (current_date + timedelta(days=7)).strftime('%Y-%m-%d')

    elif view_mode == 'daily':
        # Apply assignment filter
        if filter_assigned_to:
            filtered_tasks = [t for t in tasks if filter_assigned_to in (t.get('assigned_to') or '').split(',')]
        else:
            filtered_tasks = tasks

        day_tasks = [t for t in filtered_tasks if t['date'] == current_date.isoformat()]
        calendar_data = [{'date': current_date, 'tasks': day_tasks, 'is_today': current_date == date.today()}]
        
        prev_month = (current_date - timedelta(days=1)).strftime('%Y-%m-%d')
        next_month = (current_date + timedelta(days=1)).strftime('%Y-%m-%d')

    elif view_mode == 'gantt':
        # Get filter parameters
        filter_workflow_type = request.args.get('filter_workflow_type')
        filter_start_date = request.args.get('filter_start_date')
        filter_end_date = request.args.get('filter_end_date')

        # Determine the relevant workflowIds based on active filters
        if filter_workflow_type or filter_start_date or filter_end_date or filter_assigned_to:
            candidate_workflow_ids = None

            # Filter by workflow type and assignment
            if filter_workflow_type or filter_assigned_to:
                query = 'SELECT DISTINCT workflowId FROM tasks WHERE 1=1'
                params = []
                if filter_workflow_type:
                    query += ' AND workflowType = ?'
                    params.append(filter_workflow_type)
                if filter_assigned_to:
                    query += ' AND assigned_to LIKE ?'
                    params.append(f'%{filter_assigned_to}%')
                
                rows = query_db(query, params)
                candidate_workflow_ids = {row['workflowId'] for row in rows if row['workflowId'] is not None}

            # Filter by date range of 'start' task
            if filter_start_date or filter_end_date:
                # ... (keep date query logic)
                date_query = "SELECT DISTINCT workflowId FROM tasks WHERE workflowTaskKey = 'start'"
                date_params = []
                if filter_start_date:
                    date_query += " AND date >= ?"
                    date_params.append(filter_start_date)
                if filter_end_date:
                    date_query += " AND date <= ?"
                    date_params.append(filter_end_date)
                
                date_rows = query_db(date_query, date_params)
                date_workflow_ids = {row['workflowId'] for row in date_rows if row['workflowId'] is not None}

                if candidate_workflow_ids is None:
                    candidate_workflow_ids = date_workflow_ids
                else:
                    candidate_workflow_ids.intersection_update(date_workflow_ids)
            
            workflow_ids = list(candidate_workflow_ids) if candidate_workflow_ids is not None else []
            filtered_tasks = [task for task in tasks if task.get('workflowId') in workflow_ids]
        else:
            filtered_tasks = tasks
        
        projects = get_projects_for_gantt(filtered_tasks)
        timeline_start, timeline_end, total_days = get_gantt_timeline(projects)

    elif view_mode == 'dashboard':
        # Get filter parameters
        filter_trait = request.args.get('filter_trait')
        filter_workflow_type = request.args.get('filter_workflow_type')
        filter_descriptions = request.args.getlist('filter_description')
        filter_start_date = request.args.get('filter_start_date')
        filter_end_date = request.args.get('filter_end_date')

        # Start with all tasks
        all_tasks = [dict(row) for row in query_db('SELECT * FROM tasks')]

        # Determine the relevant workflowIds based on all active filters
        if filter_trait or filter_descriptions or filter_start_date or filter_end_date or filter_workflow_type or filter_assigned_to:
            
            candidate_workflow_ids = None

            # Filter by trait, description, workflow type, and assigned_to
            if filter_trait or filter_descriptions or filter_workflow_type or filter_assigned_to:
                query = 'SELECT DISTINCT workflowId FROM tasks WHERE 1=1'
                params = []
                if filter_trait:
                    query += ' AND trait_description = ?'
                    params.append(filter_trait)
                if filter_workflow_type:
                    query += ' AND workflowType = ?'
                    params.append(filter_workflow_type)
                if filter_assigned_to:
                    query += ' AND assigned_to LIKE ?'
                    params.append(f'%{filter_assigned_to}%')
                if filter_descriptions:
                    placeholders = ', '.join(['?' for _ in filter_descriptions])
                    query += f' AND projectDescription IN ({placeholders})'
                    params.extend(filter_descriptions)
                
                rows = query_db(query, params)
                candidate_workflow_ids = {row['workflowId'] for row in rows if row['workflowId'] is not None}

            # Filter by date range of 'start' task
            if filter_start_date or filter_end_date:
                # ... (keep date query logic)
                date_query = "SELECT DISTINCT workflowId FROM tasks WHERE workflowTaskKey = 'start'"
                date_params = []
                if filter_start_date:
                    date_query += " AND date >= ?"
                    date_params.append(filter_start_date)
                if filter_end_date:
                    date_query += " AND date <= ?"
                    date_params.append(filter_end_date)
                
                date_rows = query_db(date_query, date_params)
                date_workflow_ids = {row['workflowId'] for row in date_rows if row['workflowId'] is not None}

                if candidate_workflow_ids is None:
                    candidate_workflow_ids = date_workflow_ids
                else:
                    candidate_workflow_ids.intersection_update(date_workflow_ids)
            
            workflow_ids = list(candidate_workflow_ids) if candidate_workflow_ids is not None else []
            tasks_for_processing = [task for task in all_tasks if task.get('workflowId') in workflow_ids]
        else:
            tasks_for_processing = all_tasks

        processed_projects = get_processed_projects(tasks_for_processing)
        projects = processed_projects if processed_projects is not None else []

        if not (filter_trait or filter_descriptions or filter_start_date or filter_end_date or filter_workflow_type or filter_assigned_to):
            projects = sorted(projects, key=lambda p: p['startDate'], reverse=True)[:8]

        kpis = get_dashboard_kpis(projects)
        unique_traits = [row['trait_description'] for row in query_db('SELECT DISTINCT trait_description FROM tasks WHERE trait_description IS NOT NULL AND trait_description != ""')]
        unique_descriptions = [row['projectDescription'] for row in query_db('SELECT DISTINCT projectDescription FROM tasks WHERE projectDescription IS NOT NULL AND projectDescription != ""')]

    workflows = load_workflows()

    return render_template('index.html',
                           view_mode=view_mode,
                           calendar_data=calendar_data,
                           current_date=current_date,
                           prev_month=prev_month,
                           next_month=next_month,
                           workflows=workflows,
                           tasks=tasks,
                           projects=projects,
                           timeline_start=timeline_start,
                           timeline_end=timeline_end,
                           total_days=total_days,
                           kpis=kpis,
                           unique_traits=unique_traits,
                           filter_trait=filter_trait,
                           filter_workflow_type=filter_workflow_type,
                           unique_descriptions=unique_descriptions,
                           filter_descriptions=filter_descriptions,
                           filter_assigned_to=filter_assigned_to,
                           lab_members=lab_members,
                           project_v2_status=project_v2_status,
                           task_csv_status=task_csv_status,
                           timedelta=timedelta
                           )

def get_calendar_data(current_date, tasks):
    year = current_date.year
    month = current_date.month
    first_day_of_month = date(year, month, 1)
    last_day_of_month = (date(year, month + 1, 1) - timedelta(days=1)) if month < 12 else date(year, 12, 31)
    start_day_of_week = first_day_of_month.isoweekday() % 7

    days = []
    # Days from previous month
    for i in range(start_day_of_week):
        day = first_day_of_month - timedelta(days=start_day_of_week - i)
        days.append({'date': day, 'is_other_month': True, 'tasks': []})

    # Days of current month
    for i in range(last_day_of_month.day):
        day = first_day_of_month + timedelta(days=i)
        day_tasks = [task for task in tasks if task['date'] == day.isoformat()]
        days.append({'date': day, 'is_other_month': False, 'tasks': day_tasks, 'is_today': day == date.today()})

    # Days from next month
    grid_size = 42
    remaining = grid_size - len(days)
    for i in range(remaining):
        day = last_day_of_month + timedelta(days=i + 1)
        days.append({'date': day, 'is_other_month': True, 'tasks': []})

    return days

def get_projects_for_gantt(tasks):
    projects = {}
    for task in tasks:
        if 'workflowId' in task:
            if task['workflowId'] not in projects:
                projects[task['workflowId']] = {
                    'id': task['workflowId'],
                    'name': task['projectName'],
                    'color': task['color'],
                    'tasks': []
                }
            projects[task['workflowId']]['tasks'].append(task)

    project_list = []
    for project_id, project_data in projects.items():
        dates = [datetime.strptime(t['date'], '%Y-%m-%d').date() for t in project_data['tasks']]
        project_data['startDate'] = min(dates)
        project_data['endDate'] = max(dates)
        project_list.append(project_data)

    return sorted(project_list, key=lambda p: p['startDate'])

def get_gantt_timeline(projects):
    if not projects:
        today = date.today()
        timeline_start = today.replace(day=1)
        timeline_end = (today.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        total_days = (timeline_end - timeline_start).days
        if total_days == 0: # Ensure total_days is at least 1
            total_days = 1
        return timeline_start, timeline_end, total_days

    start_dates = [p['startDate'] for p in projects]
    end_dates = [p['endDate'] for p in projects]

    abs_min = min(start_dates)
    abs_max = max(end_dates)

    timeline_start = abs_min.replace(day=1)
    timeline_end = (abs_max.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    total_days = (timeline_end - timeline_start).days
    if total_days == 0: # Ensure total_days is at least 1
        total_days = 1

    return timeline_start, timeline_end, total_days

def parse_pre_description(description):
    if not description: return None
    # Support "ID V1,V2,V3" or "V1,V2,V3,ID" or "V1,V2,V3"
    desc = description.replace('(', ' ').replace(')', ' ').replace(',', ' ')
    parts = desc.split()
    
    numerics = []
    identifier = None
    
    for p in parts:
        if p.isdigit():
            numerics.append(int(p))
        else:
            if identifier is None:
                identifier = p
    
    if len(numerics) >= 2:
        return {
            'v1': numerics[0],
            'v2': numerics[1],
            'v3': numerics[2] if len(numerics) > 2 else None,
            'identifier': identifier
        }
    
    # Old format support fallback
    data = {}
    for part in parts:
        lower = part.lower()
        if 'v1' in lower: data['v1'] = int(''.join(filter(str.isdigit, part)) or 0)
        elif 'v2' in lower: data['v2'] = int(''.join(filter(str.isdigit, part)) or 0)
        elif 'v3' in lower: data['v3'] = int(''.join(filter(str.isdigit, part)) or 0)
    
    if 'v1' in data and 'v2' in data:
        return {'v1': data['v1'], 'v2': data['v2'], 'v3': data.get('v3'), 'identifier': identifier}
        
    return None

def get_processed_projects(tasks):
    grouped_by_workflow = {}
    for task in tasks:
        if 'workflowId' in task:
            if task['workflowId'] not in grouped_by_workflow:
                grouped_by_workflow[task['workflowId']] = []
            grouped_by_workflow[task['workflowId']].append(task)

    processed_projects = []
    for workflow_id, project_tasks in grouped_by_workflow.items():
        try:
            # Sort chronologically to find start/end
            project_tasks.sort(key=lambda t: (t['date'], t['id']))
            
            # Start Task Search: key=start, or Transformation, or Streaking, or the first task
            start_task = next((t for t in project_tasks if t['workflowTaskKey'] in ['start', 'Streaking', 'Transformation']), project_tasks[0])
            
            # Pre Task Search: key=pre, or Pre-H, or Pre-S, or Pre-Regeneration, or name starts with 'Pre'
            pre_task = next((t for t in project_tasks if t['workflowTaskKey'] in ['pre', 'Pre-H', 'Pre-S', 'Pre-Regeneration'] or t['name'].startswith('Pre')), None)

            if not start_task:
                continue # Skip if no start task found after fallback

            original_project_name = start_task['projectName']
            original_project_description = start_task['projectDescription']
            
            dates = [datetime.strptime(t['date'], '%Y-%m-%d').date() for t in project_tasks]
            start_date = min(dates)
            end_date = max(dates)

            start_description_lines = [line.strip() for line in start_task['description'].split('\n') if line.strip()]
            
            pre_description_lines = []
            if pre_task and pre_task['description']:
                pre_description_lines = [line.strip() for line in pre_task['description'].split('\n') if line.strip()]

            if len(start_description_lines) > 1 and len(start_description_lines) == len(pre_description_lines):
                # Process as sub-projects
                for i, start_line in enumerate(start_description_lines):
                    sub_project_name = f"{original_project_name}-{start_line}"
                    pre_line = pre_description_lines[i]
                    parsed_data = parse_pre_description(pre_line)

                    tf_percent = None
                    regen_percent = None

                    if parsed_data:
                        v1, v2, v3 = parsed_data.get('v1'), parsed_data.get('v2'), parsed_data.get('v3')
                        if v1 and v1 > 0: tf_percent = (v2 / v1) * 100
                        if v3 is not None and v2 and v2 > 0: regen_percent = (v3 / v2) * 100
                    
                    tf_percent = tf_percent if tf_percent is not None else 0
                    regen_percent = regen_percent if regen_percent is not None else 0

                    processed_projects.append({
                        'id': f'{workflow_id}-{i}', # Unique ID for sub-project
                        'name': sub_project_name,
                        'description': original_project_description,
                        'startDate': start_date,
                        'endDate': end_date,
                        'tfPercent': tf_percent,
                        'regenPercent': regen_percent,
                    })
            else:
                # Original logic for single line or mismatched lines
                parsed_data = parse_pre_description(pre_task['description']) if pre_task else None

                tf_percent = None
                regen_percent = None

                if parsed_data:
                    v1, v2, v3 = parsed_data.get('v1'), parsed_data.get('v2'), parsed_data.get('v3')
                    if v1 and v1 > 0: tf_percent = (v2 / v1) * 100
                    if v3 is not None and v2 and v2 > 0: regen_percent = (v3 / v2) * 100
                
                tf_percent = tf_percent if tf_percent is not None else 0
                regen_percent = regen_percent if regen_percent is not None else 0

                processed_projects.append({
                    'id': workflow_id,
                    'name': original_project_name,
                    'description': original_project_description,
                    'startDate': start_date,
                    'endDate': end_date,
                    'tfPercent': tf_percent,
                    'regenPercent': regen_percent,
                })
        except Exception as e:
            print(f"[ERROR] Error processing workflow {workflow_id}: {e}")
            # Optionally, you could append a placeholder project or skip this workflow entirely
            # For now, we'll just log and continue, which means this workflow won't appear.
            continue
    return sorted(processed_projects, key=lambda p: p['startDate'])

def get_dashboard_kpis(projects):
    projects_with_tf = [p for p in projects if p['tfPercent'] is not None]
    projects_with_regen = [p for p in projects if p['regenPercent'] is not None]
    avg_tf = sum(p['tfPercent'] for p in projects_with_tf) / len(projects_with_tf) if projects_with_tf else 0
    avg_regen = sum(p['regenPercent'] for p in projects_with_regen) / len(projects_with_regen) if projects_with_regen else 0
    return {'totalProjects': len(projects), 'avgTf': avg_tf, 'avgRegen': avg_regen}


@app.route('/add_workflow', methods=['POST'])
@requires_role('admin', 'editor')
def add_workflow():
    global workflows
    project_name = request.form['project_name']
    project_description = request.form['project_description']
    trait_description = request.form['trait_description']
    start_date_str = request.form['start_date']
    workflow_type = request.form.get('workflow_type', 'transformation')

    start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()

    # Dynamic workflow selection
    workflows = load_workflows() # Refresh to ensure latest
    selected_workflow = workflows.get(workflow_type, workflows.get('transformation'))

    if not selected_workflow:
        flash(f"Error: Workflow type '{workflow_type}' not found.")
        return redirect(url_for('index'))

    workflow_id = get_next_workflow_id()
    new_color = project_colors[workflow_id % len(project_colors)]

    last_task_date = start_date

    for i, task_template in enumerate(selected_workflow['tasks']):
        if i > 0:
            last_task_date = add_offset_to_date(last_task_date, task_template['offset']['value'], task_template['offset']['unit'])

        query_db('INSERT INTO tasks (name, projectName, projectDescription, date, description, color, workflowId, workflowType, workflowTaskKey, trait_description) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                 [task_template['name'], project_name, project_description, last_task_date.isoformat(), task_template['description'], new_color, workflow_id, workflow_type, task_template['key'], trait_description])
    get_db().commit()
    create_backup()
    return redirect(url_for('index'))

@app.route('/update_task', methods=['POST'])
@requires_role('admin', 'editor')
def update_task():
    global workflows
    task_id = int(request.form['task_id'])
    date = request.form['date']
    description = request.form['description']
    assigned_to = request.form.get('assigned_to', '') # Get lab member assignments

    query_db('UPDATE tasks SET date = ?, description = ?, assigned_to = ? WHERE id = ?', [date, description, assigned_to, task_id])

    updated_task = query_db('SELECT * FROM tasks WHERE id = ?', [task_id], one=True)

    if updated_task:
        # Auto-update V3 and T0 info if any Pre or RS-like task is updated
        is_rs_like = (updated_task['workflowTaskKey'] in ['rs', 'RS', 'Regeneration', 'RH'] or 
                     updated_task['name'] in ['RS', 'RS-H', 'RH', 'Regeneration'])
        is_pre_like = (updated_task['workflowTaskKey'] in ['pre', 'Pre-H', 'Pre-S'] or
                      updated_task['name'].startswith('Pre'))
        
        if is_rs_like or is_pre_like:
            project_name = updated_task['projectName']
            if project_name:
                update_pre_task_v3(project_name)

    if 'update_subsequent' in request.form:
        # Logic to update subsequent tasks (Robust against duplicate keys in AMT)
        if updated_task:
            workflows = load_workflows()
            wf_config = workflows.get(updated_task['workflowType'])
            if wf_config:
                workflow_template = wf_config['tasks']
                # Match both key AND name to find exact template step
                edited_template_index = next((i for i, t in enumerate(workflow_template) 
                                            if t['key'] == updated_task['workflowTaskKey'] 
                                            and t['name'] == updated_task['name']), -1)

                if edited_template_index != -1:
                    last_task_date = datetime.strptime(updated_task['date'], '%Y-%m-%d').date()
                    
                    # Fetch all tasks for this specific project instance to update correct IDs
                    project_tasks = query_db('SELECT * FROM tasks WHERE workflowId = ?', [updated_task['workflowId']])

                    for i in range(edited_template_index + 1, len(workflow_template)):
                        subsequent_template_task = workflow_template[i]
                        last_task_date = add_offset_to_date(last_task_date, subsequent_template_task['offset']['value'], subsequent_template_task['offset']['unit'])
                        
                        # Find the actual DB task that matches this template step
                        actual_sub_task = next((tk for tk in project_tasks 
                                              if tk['workflowTaskKey'] == subsequent_template_task['key']
                                              and tk['name'] == subsequent_template_task['name']), None)
                        
                        if actual_sub_task:
                            query_db('UPDATE tasks SET date = ? WHERE id = ?',
                                     [last_task_date.isoformat(), actual_sub_task['id']])

    get_db().commit()
    create_backup()
    return jsonify(success=True)

@app.route('/delete_task/<int:task_id>')
@requires_role('admin', 'editor')
def delete_task(task_id):
    task_to_delete = query_db('SELECT * FROM tasks WHERE id = ?', [task_id], one=True)
    if task_to_delete and 'workflowId' in task_to_delete:
        # Delete entire project
        query_db('DELETE FROM tasks WHERE workflowId = ?', [task_to_delete['workflowId']])
    else:
        query_db('DELETE FROM tasks WHERE id = ?', [task_id])
    get_db().commit()
    return redirect(url_for('index'))

@app.route('/delete_single_task/<int:task_id>', methods=['POST'])
@requires_role('admin', 'editor')
def delete_single_task(task_id):
    global workflows
    try:
        task_to_delete = query_db('SELECT * FROM tasks WHERE id = ?', [task_id], one=True)

        if not task_to_delete:
            return jsonify(success=False, error='Task not found'), 404

        workflow_id = task_to_delete['workflowId']
        workflow_type = task_to_delete['workflowType']
        deleted_task_key = task_to_delete['workflowTaskKey']
        project_name = task_to_delete['projectName']

        if not all([workflow_id, workflow_type, deleted_task_key]):
            # This is not a workflow task, just delete it
            query_db('DELETE FROM tasks WHERE id = ?', [task_id])
            get_db().commit()
            return jsonify(success=True)

        workflows = load_workflows()
        workflow_template = workflows.get(workflow_type)
        if not workflow_template:
            return jsonify(success=False, error=f'Workflow type {workflow_type} not found'), 400

        task_keys = [task['key'] for task in workflow_template['tasks']]
        try:
            deleted_task_index = task_keys.index(deleted_task_key)
        except ValueError:
            # The task key is not in the template, just delete the single task
            query_db('DELETE FROM tasks WHERE id = ?', [task_id])
            get_db().commit()
            return jsonify(success=True)

        keys_to_delete = task_keys[deleted_task_index:]

        # Create a string of placeholders for the IN clause
        placeholders = ', '.join('?' for _ in keys_to_delete)
        query = f'DELETE FROM tasks WHERE workflowId = ? AND workflowTaskKey IN ({placeholders})'
        
        # Prepare the arguments for the query
        args = [workflow_id] + keys_to_delete
        
        query_db(query, args)
        get_db().commit()

        if project_name:
            update_t0_info_json()
            update_pre_task_v3(project_name)

        return jsonify(success=True)

    except Exception as e:
        get_db().rollback()
        print(f"Error deleting task: {e}")
        return jsonify(success=False, error=str(e)), 500
@app.route('/delete_t0_info_row', methods=['POST'])
@requires_role('admin', 'editor')
def delete_t0_info_row():
    try:
        data = request.get_json()
        row_id_to_delete = data.get('id')
        project_name = data.get('project_name')

        if not row_id_to_delete or not project_name:
            return jsonify(success=False, error='Missing ID or Project Name'), 400

        # Find the RS task for the given project (support multiple keys)
        rs_task = query_db("SELECT * FROM tasks WHERE projectName = ? AND (workflowTaskKey IN ('rs', 'RS', 'Regeneration', 'RH') OR name IN ('RS', 'RS-H', 'RH'))", [project_name], one=True)

        if not rs_task:
            return jsonify(success=False, error=f'RS task not found for project: {project_name}'), 404

        current_description = rs_task['description'] if rs_task['description'] else ""
        updated_lines = []
        needs_db_update = False

        # Split description into lines and reconstruct, skipping the line to delete
        for line in current_description.split('\n'):
            trimmed_line = line.strip()
            if not trimmed_line: continue
            
            # Robust matching: 
            # 1. Matches exactly (for manual IDs like 1-1-1)
            # 2. Matches start with comma (for standard format DNAID,PlantID,Value)
            if trimmed_line == str(row_id_to_delete) or trimmed_line.startswith(f"{row_id_to_delete},"):
                needs_db_update = True 
                continue 
            updated_lines.append(line)

        new_description = '\n'.join(updated_lines).strip()

        if needs_db_update:
            # Only update the database if we actually removed a line
            query_db('UPDATE tasks SET description = ? WHERE id = ?', [new_description, rs_task['id']])
            get_db().commit()
            print(f"[DEBUG] Updated RS task description for project {project_name}, removed ID {row_id_to_delete}")
        else:
            print(f"[DEBUG] ID {row_id_to_delete} not found in RS task description for project {project_name}. No DB update needed for description.")

        # ALWAYS update t0_info.json and pre_task_v3 after attempting to modify RS description
        # This ensures consistency even if the ID was already missing from the description.
        update_t0_info_json()
        update_pre_task_v3(project_name)
        print(f"[DEBUG] Triggered update_t0_info_json() and update_pre_task_v3() for project {project_name}.")

        return jsonify(success=True)

    except Exception as e:
        get_db().rollback()
        print(f"Error deleting t0_info row: {e}")
        return jsonify(success=False, error=str(e)), 500


@app.route('/export_csv')
def export_csv():
    tasks = [dict(row) for row in query_db('SELECT * FROM tasks')]
    headers = ["Project Name", "Description", "Trait", "Transformation date", "HYG", "Pre", "total #", "transformed", "TF %", "RS", "# of Regen", "Regen %", "End_of_Project"]

    projects_data = {}
    for task in tasks:
        if 'workflowId' not in task: continue

        project_id = task['workflowId']
        if project_id not in projects_data:
            projects_data[project_id] = {
                "Project Name": task['projectName'],
                "Description": task['projectDescription'],
                "Trait": task['trait_description']
            }

        key_to_header = {
            'start': 'Transformation date', 'Streaking': 'Transformation date', 'Transformation': 'Transformation date',
            'hyg': 'HYG', 'Washing & Screening': 'HYG',
            'pre': 'Pre', 'Pre-Regeneration': 'Pre', 'Pre-H': 'Pre', 'Pre-S': 'Pre',
            'rs': 'RS', 'Regeneration': 'RS', 'RS-H': 'RS',
            'end': 'End_of_Project', 'End of Project': 'End_of_Project'
        }
        header_name = key_to_header.get(task['workflowTaskKey'])
        if not header_name:
            # Fallback by task name if key doesn't match
            if task['name'].startswith('Pre'): header_name = 'Pre'
            elif task['name'] in ['RS', 'RS-H', 'Regeneration']: header_name = 'RS'
        
        if header_name:
            projects_data[project_id][header_name] = task['date']

        # Logic for V1/V2/V3 counts based on Pre task description
        is_pre = task['workflowTaskKey'] in ['pre', 'Pre-Regeneration', 'Pre-H', 'Pre-S'] or task['name'].startswith('Pre')
        if is_pre:
            parsed_data = parse_pre_description(task['description'])
            if parsed_data:
                v1, v2, v3 = parsed_data.get('v1'), parsed_data.get('v2'), parsed_data.get('v3')
                projects_data[project_id]['total #'] = v1
                projects_data[project_id]['transformed'] = v2
                projects_data[project_id]['TF %'] = f"{(v2/v1)*100:.2f}%" if v1 and v1 > 0 else 'N/A'
                if v3 is not None:
                    projects_data[project_id]['# of Regen'] = v3
                    projects_data[project_id]['Regen %'] = f"{(v3/v2)*100:.2f}%" if v2 and v2 > 0 else 'N/A'

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=headers)
    writer.writeheader()
    writer.writerows(projects_data.values())

    return send_file(io.BytesIO(output.getvalue().encode()), mimetype='text/csv', as_attachment=True, download_name='project_export.csv')

@app.route('/export_rs_data_csv')
def export_rs_data_csv(as_string=False):
    # Load from t0_info.json to preserve custom columns
    data = []
    try:
        with open('t0_info.json', 'r') as f:
            data = json.load(f)
    except Exception as e:
        print(f"[ERROR] export_rs_data_csv failed: {e}")
        return "T0 info not found" if not as_string else ""

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerows(data)

    if as_string:
        return output.getvalue()

    return send_file(io.BytesIO(output.getvalue().encode()), mimetype='text/csv', as_attachment=True, download_name='rs_data_export.csv')


@app.route('/import_rs_data', methods=['POST'])
@requires_role('admin', 'editor')
def import_rs_data():
    if 'file' not in request.files:
        flash('No file part')
        return redirect(url_for('index'))
    file = request.files['file']
    if file.filename == '':
        flash('No selected file')
        return redirect(url_for('index'))
    if file and file.filename.endswith('.csv'):
        try:
            # Use utf-8-sig to handle possible BOM
            stream = io.StringIO(file.stream.read().decode("utf-8-sig"))
            reader = csv.DictReader(stream)
            updated_count = 0
            for row in reader:
                project_name = row.get('Project Name')
                if not project_name: continue # Skip empty rows

                # Field mapping with defaults
                rs_id = row.get('DNA ID') or "N/A"
                plant_id = row.get('Plant ID') or "N/A"
                value = row.get('Value') or ""
                
                # If Value is missing but DNA ID is present and looks significant, use it
                if not value and rs_id != "N/A":
                    value = rs_id

                # Clean Excel-style escaping
                if value.startswith('="') and value.endswith('"'):
                    value = value[2:-1]

                # Find the RS task for the project (flexible keys)
                task = query_db("SELECT * FROM tasks WHERE projectName = ? AND (workflowTaskKey IN ('rs', 'RS', 'Regeneration', 'RH') OR name IN ('RS', 'RS-H', 'RH', 'Regeneration'))", [project_name], one=True)

                if task:
                    current_description = task['description'] if task['description'] else ""
                    # Internal format: DNA ID, Plant ID, Value
                    new_entry = f"{rs_id},{plant_id},{value}"

                    # Append new entry if it's not already there
                    if new_entry not in current_description:
                        # Get trait from the database if available
                        trait = row.get('Trait') or ""
                        if not trait:
                            trait_task = query_db('SELECT trait_description FROM tasks WHERE projectName = ?', [project_name], one=True)
                            trait = trait_task['trait_description'] if trait_task else ''

                        if current_description and not current_description.endswith("\n"):
                            current_description += "\n"
                        updated_description = current_description + new_entry
                        query_db('UPDATE tasks SET description = ?, trait_description = ? WHERE id = ?', [updated_description, trait, task['id']])
                        updated_count += 1
                        # Trigger sync
                        update_pre_task_v3(project_name)
                else:
                    print(f"[DEBUG] No RS task found for project: {project_name}")
            
            get_db().commit()
            update_t0_info_json()
            flash(f'Successfully updated {updated_count} RS tasks and synced data.')
        except Exception as e:
            get_db().rollback()
            flash(f'Error importing RS data: {e}')
            print(f"[ERROR] Import failed: {e}")
    else:
        flash('Invalid file type. Please upload a .csv file.')
    return redirect(url_for('index'))



def update_pre_task_v3(project_name):
    # Find all tasks for this project to get workflow contexts
    all_project_tasks = query_db("SELECT * FROM tasks WHERE projectName = ?", [project_name])
    if not all_project_tasks: return

    # Group tasks by workflowId (a project might have multiple workflow instances)
    workflow_groups = {}
    for t in all_project_tasks:
        wid = t['workflowId']
        if wid not in workflow_groups: workflow_groups[wid] = []
        workflow_groups[wid].append(t)

    for wid, tasks in workflow_groups.items():
        # Identify the "Pre" equivalent task in this specific workflow
        pre_task = next((t for t in tasks if t['workflowTaskKey'] in ['pre', 'Pre-S', 'Pre-regeneration', 'Pre-Regeneration'] or t['name'].startswith('Pre')), None)
        
        # Identify the "Regeneration" equivalent task in this specific workflow
        rs_task = next((t for t in tasks if t['workflowTaskKey'] in ['rs', 'RS', 'Regeneration', 'RH'] or t['name'] in ['RS', 'RS-H', 'RH', 'Regeneration']), None)

        if pre_task and rs_task:
            print(f"[DEBUG] Syncing V3 for Project {project_name} (Workflow {wid})")
            pre_lines = [l.strip() for l in (pre_task['description'] or "").split('\n') if l.strip()]
            rs_lines = [l.strip() for l in (rs_task['description'] or "").split('\n') if l.strip()]
            
            new_pre_lines = []
            for pre_line in pre_lines:
                parsed = parse_pre_description(pre_line)
                if not parsed:
                    new_pre_lines.append(pre_line); continue
                
                v1, v2, v3, ident = parsed['v1'], parsed['v2'], parsed['v3'], parsed['identifier']
                
                # Count matching entries in RS
                v3_from_summary = 0
                individual_count = 0
                
                for rs_line in rs_lines:
                    if rs_line.lower().startswith('release'): continue
                    
                    # Split to check parts
                    rs_parts = [p.strip() for p in rs_line.split(',')]
                    
                    # If it has 3+ parts and the 3rd part has a dash or letter, it's definitely an entry
                    # e.g., "009,5610,10-1-2"
                    is_entry = len(rs_parts) >= 3 and ('-' in rs_parts[2] or any(c.isalpha() for c in rs_parts[2]))
                    
                    # Also check if it's a simple 1 or 2 part manual ID (e.g., "1-1-1")
                    if not is_entry and len(rs_parts) < 3 and ('-' in rs_line or any(c.isalpha() for c in rs_line)):
                        is_entry = True

                    if is_entry:
                        # Count if no identifier or identifier is in the line
                        if ident is None or ident in rs_line:
                            individual_count += 1
                    else:
                        # Might be a summary line in RS (synced from Pre)
                        rs_p = parse_pre_description(rs_line)
                        if rs_p and rs_p['identifier'] == ident:
                            v3_from_summary = rs_p['v3'] if rs_p['v3'] is not None else 0
                
                final_v3 = individual_count if individual_count > 0 else v3_from_summary
                line = f"{v1},{v2},{final_v3}"
                if ident: line = f"{ident} {line}"
                new_pre_lines.append(line)

            new_desc = '\n'.join(new_pre_lines)
            query_db('UPDATE tasks SET description = ? WHERE id = ?', [new_desc, pre_task['id']])
    
    get_db().commit()
    update_t0_info_json()



def add_project_from_csv(project_name, start_date, pre_description, project_description, trait_description, workflow_type="transformation"):
    global workflows
    workflows = load_workflows()
    
    # Map friendly names to internal keys if needed
    type_map = {
        "Transformation Project": "transformation",
        "Callus Induction": "Germplasm Optimization",
        "AMT": "Agrobateria mediate transformation"
    }
    internal_type = type_map.get(workflow_type, workflow_type)
    
    if internal_type not in workflows:
        print(f"[DEBUG] Unknown workflow type: {workflow_type}, defaulting to transformation")
        internal_type = "transformation"

    selected_workflow = workflows[internal_type]
    workflow_id = get_next_workflow_id()
    new_color = project_colors[workflow_id % len(project_colors)]
    last_task_date = start_date

    for i, task_template in enumerate(selected_workflow['tasks']):
        task_date = start_date
        if i > 0:
            last_task_date = add_offset_to_date(last_task_date, task_template['offset']['value'], task_template['offset']['unit'])
            task_date = last_task_date

        description = task_template['description']
        # Only inject v1,v2,v3 into the "Pre" equivalent task
        is_pre = task_template['key'] in ['pre', 'Pre-S', 'Pre-Regeneration'] or task_template['name'].startswith('Pre')
        if is_pre and pre_description:
            description = pre_description

        query_db('INSERT INTO tasks (name, projectName, projectDescription, date, description, color, workflowId, workflowType, workflowTaskKey, trait_description) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                 [task_template['name'], project_name, project_description, task_date.isoformat(), description, new_color, workflow_id, internal_type, task_template['key'], trait_description])
    get_db().commit()

@app.route('/import_old_projects', methods=['POST'])
@requires_role('admin', 'editor')
def import_old_projects():
    if 'file' not in request.files:
        flash('No file part')
        return redirect(url_for('index'))
    file = request.files['file']
    if file.filename == '':
        flash('No selected file')
        return redirect(url_for('index'))
    if file and file.filename.endswith('.csv'):
        try:
            stream = io.StringIO(file.stream.read().decode("utf-8-sig"))
            reader = csv.DictReader(stream)
            imported_count = 0
            for row in reader:
                project_name = row.get('Project Name')
                start_date_str = row.get('Start Date')
                if not project_name or not start_date_str:
                    continue

                project_type = row.get('Project Type', 'Transformation Project')
                project_description = row.get('Project Description', '')
                trait_description = row.get('Trait Description', '')
                
                v1 = row.get('V1', '')
                v2 = row.get('V2', '')
                v3 = row.get('V3', '')

                # Only create pre_description if at least v1 and v2 are present
                pre_description = ""
                if v1 and v2:
                    pre_description = f"{v1},{v2},{v3 or 0}"

                try:
                    start_date = datetime.strptime(start_date_str, '%m/%d/%Y').date()
                except ValueError:
                    # Try alternate format
                    try:
                        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
                    except:
                        flash(f"Invalid date format for project {project_name}: {start_date_str}")
                        continue

                add_project_from_csv(project_name, start_date, pre_description, project_description, trait_description, project_type)
                imported_count += 1

            flash(f'Successfully imported {imported_count} projects.')
        except Exception as e:
            flash(f'Error importing old projects: {e}')
            print(f"[ERROR] Import failed: {e}")
    else:
        flash('Invalid file type. Please upload a .csv file.')
    return redirect(url_for('index'))


@app.route('/api/move_task', methods=['POST'])
@requires_role('admin', 'editor')
def api_move_task():
    try:
        data = request.get_json()
        task_id = data['task_id']
        new_date_str = data['new_date']
        update_subsequent = data.get('update_subsequent', False)
        assigned_to = data.get('assigned_to')

        # Update the task's date in the database
        if assigned_to is not None:
            query_db('UPDATE tasks SET date = ?, assigned_to = ? WHERE id = ?', [new_date_str, assigned_to, task_id])
        else:
            query_db('UPDATE tasks SET date = ? WHERE id = ?', [new_date_str, task_id])

        if update_subsequent:
            # Logic to update subsequent tasks (adapted from update_task)
            updated_task = query_db('SELECT * FROM tasks WHERE id = ?', [task_id], one=True)
            if updated_task:
                workflow_template = workflows[updated_task['workflowType']]['tasks']
                # Robust lookup: Match both key AND name to handle duplicate keys in AMT
                edited_template_index = next((i for i, t in enumerate(workflow_template) 
                                            if t['key'] == updated_task['workflowTaskKey'] 
                                            and t['name'] == updated_task['name']), -1)

                if edited_template_index != -1:
                    last_task_date = datetime.strptime(new_date_str, '%Y-%m-%d').date()

                    # Fetch all subsequent tasks for this specific project instance
                    project_tasks = query_db('SELECT * FROM tasks WHERE workflowId = ?', [updated_task['workflowId']])
                    
                    for i in range(edited_template_index + 1, len(workflow_template)):
                        subsequent_template_task = workflow_template[i]
                        last_task_date = add_offset_to_date(last_task_date, subsequent_template_task['offset']['value'], subsequent_template_task['offset']['unit'])
                        
                        # Find the actual DB task that matches this template step
                        actual_sub_task = next((tk for tk in project_tasks 
                                              if tk['workflowTaskKey'] == subsequent_template_task['key']
                                              and tk['name'] == subsequent_template_task['name']), None)
                        
                        if actual_sub_task:
                            query_db('UPDATE tasks SET date = ? WHERE id = ?',
                                     [last_task_date.isoformat(), actual_sub_task['id']])
        get_db().commit()
        return jsonify(success=True)
    except Exception as e:
        get_db().rollback() # Rollback in case of error
        return jsonify(success=False, error=str(e))



import threading
import atexit

def create_backup(with_flash=True):
    """Creates a timestamped backup of the database file and associated data."""
    backup_folder = os.path.join(app.root_path, 'backups')
    if not os.path.exists(backup_folder):
        os.makedirs(backup_folder)

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_filename = f'backup_{timestamp}.zip'
    backup_path = os.path.join(backup_folder, backup_filename)

    temp_backup_dir = os.path.join(app.root_path, f'temp_backup_{timestamp}')
    os.makedirs(temp_backup_dir, exist_ok=True)

    try:
        # Copy database file
        db_path = os.path.join(app.root_path, DATABASE)
        if os.path.exists(db_path):
            shutil.copy2(db_path, temp_backup_dir)

        # Copy JSON data files
        t0_info_path = os.path.join(app.root_path, 't0_info.json')
        if os.path.exists(t0_info_path):
            shutil.copy2(t0_info_path, temp_backup_dir)
        
        progeny_info_path = os.path.join(app.root_path, PROGENY_INFO_FILE)
        if os.path.exists(progeny_info_path):
            shutil.copy2(progeny_info_path, temp_backup_dir)

        # Copy edit data folders
        if os.path.exists(EDIT_DATA_FOLDER):
            shutil.copytree(EDIT_DATA_FOLDER, os.path.join(temp_backup_dir, os.path.basename(EDIT_DATA_FOLDER)), dirs_exist_ok=True)
        if os.path.exists(PROGENY_EDIT_DATA_FOLDER):
            shutil.copytree(PROGENY_EDIT_DATA_FOLDER, os.path.join(temp_backup_dir, os.path.basename(PROGENY_EDIT_DATA_FOLDER)), dirs_exist_ok=True)

        # Create zip archive
        shutil.make_archive(os.path.join(backup_folder, f'backup_{timestamp}'), 'zip', temp_backup_dir)
        if with_flash:
            flash('Database and associated data backup created successfully!')
        return backup_path

    except Exception as e:
        if with_flash:
            flash(f'Error creating backup: {e}')
        print(f"Error creating backup: {e}")
        return None
    finally:
        # Clean up temporary directory
        if os.path.exists(temp_backup_dir):
            shutil.rmtree(temp_backup_dir)

def cleanup_old_backups(keep_count=10):
    """오래된 백업 파일 정리 (최신 keep_count개만 유지)"""
    try:
        backup_dir = 'backups'
        if not os.path.exists(backup_dir):
            return
        
        backup_files = [f for f in os.listdir(backup_dir) if f.startswith('backup_') and f.endswith('.zip')]
        backup_files.sort(reverse=True)  # 최신 순으로 정렬
        
        # 오래된 백업 삭제
        for old_backup in backup_files[keep_count:]:
            os.remove(os.path.join(backup_dir, old_backup))
            print(f"Removed old backup: {old_backup}")
    except Exception as e:
        print(f"Cleanup failed: {e}")

# 3. 자동 백업 스케줄러
backup_scheduler = None

def schedule_auto_backup(interval_hours=24):
    """자동 백업 스케줄링"""
    def backup_worker():
        while True:
            import time
            time.sleep(interval_hours * 3600)  # 시간을 초로 변환
            create_backup()
            cleanup_old_backups()
    
    global backup_scheduler
    backup_scheduler = threading.Thread(target=backup_worker, daemon=True)
    backup_scheduler.start()

# 앱 시작 시 자동 백업 스케줄링
def startup():
    # 시작 시 백업 생성
    create_backup()
    # 자동 백업 스케줄링 (24시간마다)
    schedule_auto_backup(24)

# 앱 종료 시 백업 생성
def shutdown_backup():
    create_backup(with_flash=False)
    print("Shutdown backup completed")

atexit.register(shutdown_backup)

@app.route('/backup')
@requires_role('admin', 'editor')
def manual_backup():
    """수동 백업 생성"""
    backup_path = create_backup()
    if backup_path:
        return jsonify({'success': True, 'backup_path': backup_path})
    else:
        return jsonify({'success': False, 'error': 'Backup failed'}), 500

@app.route('/restore', methods=['POST'])
@requires_role('admin')
def restore_backup():
    """백업에서 복원"""
    print("[DEBUG] Starting backup restore process")
    temp_restore_dir = None # Initialize to None
    if 'backup_file' not in request.files:
        print("[DEBUG] No backup file in request")
        return jsonify({'success': False, 'error': 'No backup file provided'}), 400
    
    file = request.files['backup_file']
    if file.filename == '':
        print("[DEBUG] No file selected")
        return jsonify({'success': False, 'error': 'No file selected'}), 400
    
    print(f"[DEBUG] Received backup file: {file.filename}")
    
    temp_restore_dir = os.path.join(app.root_path, f'temp_restore_{datetime.now().strftime("%Y%m%d_%H%M%S")}')
    os.makedirs(temp_restore_dir, exist_ok=True)

    try:
        # 현재 데이터베이스 백업
        print("[DEBUG] Creating backup of current database")
        create_backup()
        
        # 임시 파일로 저장
        temp_path = f'temp_restore_{datetime.now().strftime("%Y%m%d_%H%M%S")}.zip'
        print(f"[DEBUG] Saving uploaded backup to {temp_path}")
        file.save(temp_path)
        
        # ZIP 파일에서 데이터베이스 추출
        with zipfile.ZipFile(temp_path, 'r') as zipf:
            # ZIP 내의 .db 파일 찾기
            db_files = [f for f in zipf.namelist() if f.endswith('.db')]
            if not db_files:
                print("[DEBUG] No .db file found in backup")
                return jsonify({'success': False, 'error': 'No database file in backup'}), 400
            
            print(f"[DEBUG] Found db file in backup: {db_files[0]}")
            extracted_db_filename = os.path.basename(db_files[0])
            extracted_db_path_temp = os.path.join(temp_restore_dir, extracted_db_filename)
            zipf.extract(db_files[0], temp_restore_dir)
            print(f"[DEBUG] Extracted db file to: {extracted_db_path_temp}")
            
            # Check if the extracted database is empty
            db_size = os.path.getsize(extracted_db_path_temp)
            print(f"[DEBUG] Size of extracted db file: {db_size} bytes")
            if db_size == 0:
                os.remove(extracted_db_path_temp) # remove the empty file
                print("[DEBUG] Extracted db file is empty, aborting restore")
                return jsonify({'success': False, 'error': 'The database in the backup is empty.'}), 500

            # 현재 데이터베이스 교체
            print(f"[DEBUG] Replacing current database with {extracted_db_path_temp}")
            if os.path.exists(DATABASE):
                os.remove(DATABASE)
            
            # Rename the extracted file to the correct database name
            os.rename(extracted_db_path_temp, DATABASE)
            print("[DEBUG] Database replaced successfully")
        
        # 임시 파일 정리
        os.remove(temp_path)
        
        print("[DEBUG] Backup restore process completed successfully")
        return jsonify({'success': True, 'message': 'Database restored successfully'})
    
    except Exception as e:
        print(f"[ERROR] Restore failed: {str(e)}")
        return jsonify({'success': False, 'error': f'Restore failed: {str(e)}'}), 500
    finally:
        if os.path.exists(temp_restore_dir):
            shutil.rmtree(temp_restore_dir)

@app.route('/setup')
@requires_role('admin')
def setup():
    global workflows
    backup_dir = 'backups'
    backup_files_list = []
    if os.path.exists(backup_dir):
        backup_files = [f for f in os.listdir(backup_dir) if f.startswith('backup_') and f.endswith('.zip')]
        backup_files.sort(reverse=True)
        # Limit to 5 most recent backups
        for filename in backup_files[:5]:
            filepath = os.path.join(backup_dir, filename)
            file_size = os.path.getsize(filepath)
            created_time = datetime.fromtimestamp(os.path.getctime(filepath))
            backup_files_list.append({
                'filename': filename,
                'size': file_size,
                'created': created_time.strftime('%Y-%m-%d %H:%M:%S'),
                'download_link': url_for('download_backup', filename=filename)
            })
    
    # Get all users for admin management
    users = query_db('SELECT id, username, role FROM users')
    
    workflows = load_workflows()
    lab_members = load_lab_members()
    return render_template('setup.html', backups=backup_files_list, workflows=workflows, users=users, lab_members=lab_members)

@app.route('/add_user', methods=['POST'])
@requires_role('admin')
def add_user():
    username = request.form.get('username')
    password = request.form.get('password')
    role = request.form.get('role')
    
    if not username or not password or not role:
        flash('Missing required fields')
        return redirect(url_for('setup'))
    
    hashed_password = generate_password_hash(password, method='scrypt')
    try:
        db = get_db()
        db.execute('INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)',
                   [username, hashed_password, role])
        db.commit()
        flash(f'User {username} added successfully')
    except sqlite3.IntegrityError:
        flash('Username already exists')
    
    return redirect(url_for('setup'))

@app.route('/delete_user/<int:user_id>', methods=['POST'])
@requires_role('admin')
def delete_user(user_id):
    # Don't allow deleting yourself
    if query_db('SELECT username FROM users WHERE id = ?', [user_id], one=True)['username'] == session.get('username'):
        flash('Cannot delete your own account')
        return redirect(url_for('setup'))
        
    db = get_db()
    db.execute('DELETE FROM users WHERE id = ?', [user_id])
    db.commit()
    flash('User deleted successfully')
    return redirect(url_for('setup'))

@app.route('/api/change_password', methods=['POST'])
@requires_role('admin')
def api_change_password():
    data = request.get_json()
    user_id = data.get('user_id')
    new_password = data.get('password')

    if not user_id or not new_password:
        return jsonify(success=False, error="Missing required fields"), 400

    hashed_password = generate_password_hash(new_password)
    
    db = get_db()
    db.execute('UPDATE users SET password_hash = ? WHERE id = ?', [hashed_password, user_id])
    db.commit()
    
    return jsonify(success=True)

@app.route('/backups')
def backups():
    backup_dir = 'backups'
    if not os.path.exists(backup_dir):
        backups = []
    else:
        backup_files = [f for f in os.listdir(backup_dir) if f.startswith('backup_') and f.endswith('.zip')]
        backup_files.sort(reverse=True)
        backups = []
        for filename in backup_files:
            filepath = os.path.join(backup_dir, filename)
            file_size = os.path.getsize(filepath)
            created_time = datetime.fromtimestamp(os.path.getctime(filepath))
            backups.append({
                'filename': filename,
                'size': file_size,
                'created': created_time.strftime('%Y-%m-%d %H:%M:%S'),
                'download_link': url_for('download_backup', filename=filename)
            })
    return render_template('backups.html', backups=backups)

@app.route('/list_backups')
def list_backups():
    """백업 파일 목록 조회"""
    try:
        backup_dir = 'backups'
        if not os.path.exists(backup_dir):
            return jsonify({'backups': []})
        
        backup_files = []
        for filename in os.listdir(backup_dir):
            if filename.startswith('backup_') and filename.endswith('.zip'):
                filepath = os.path.join(backup_dir, filename)
                file_size = os.path.getsize(filepath)
                created_time = datetime.fromtimestamp(os.path.getctime(filepath))
                
                backup_files.append({
                    'filename': filename,
                    'size': file_size,
                    'created': created_time.strftime('%Y-%m-%d %H:%M:%S'),
                    'download_link': url_for('download_backup', filename=filename)
                })
        
        backup_files.sort(key=lambda x: x['created'], reverse=True)
        return jsonify({'backups': backup_files})
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/download_backup/<filename>')
def download_backup(filename):
    backup_dir = os.path.join(app.root_path, 'backups')
    return send_from_directory(directory=backup_dir, path=filename, as_attachment=True)




@app.route('/check_db_status')
def check_db_status():
    try:
        tasks = query_db('SELECT * FROM tasks')
        count = len(tasks)
        sample_tasks = tasks[:5] # Get first 5 tasks
        return jsonify(
            status='success',
            message=f'Database contains {count} tasks.',
            sample_tasks=[dict(task) for task in sample_tasks]
        )
    except Exception as e:
        return jsonify(status='error', message=f'Error checking database: {e}')

@app.route('/t0_info')
def t0_info():
    data = []
    try:
        with open('t0_info.json', 'r') as f:
            data = json.load(f)
        print(f"[DEBUG] Loaded data from t0_info.json. Data head: {data[:2]}")
    except (FileNotFoundError, json.JSONDecodeError):
        csv_data = export_rs_data_csv(as_string=True)
        if csv_data:
            reader = csv.reader(io.StringIO(csv_data))
            data = list(reader)
        print(f"[DEBUG] t0_info.json not found or invalid, generated from CSV. Data head: {data[:2]}")

    filter_project_name = request.args.get('filter_project_name')
    filter_trait = request.args.get('filter_trait')

    if data:
        header = data[0]
        body = data[1:]

        # Get unique project names and traits for dropdowns
        unique_project_names = sorted(list(set([row[header.index("Project Name")] for row in body]))) if "Project Name" in header else []
        unique_traits = sorted(list(set([row[header.index("Trait")] for row in body]))) if "Trait" in header else []

        # Apply filters
        if filter_project_name:
            project_name_col_index = header.index("Project Name")
            body = [row for row in body if filter_project_name.lower() == row[project_name_col_index].lower()]
        
        if filter_trait:
            trait_col_index = header.index("Trait")
            body = [row for row in body if filter_trait.lower() == row[trait_col_index].lower()]

        def sort_key(row):
            try:
                return (0, int(row[3])) # Sort by integer value
            except (ValueError, IndexError):
                try:
                    return (1, row[3]) # Sort by string value
                except IndexError:
                    return (2, None) # Handle empty rows
        body = sorted(body, key=sort_key)
        data = [header] + body

    return render_template('t0_info.html', data=data, unique_project_names=unique_project_names, unique_traits=unique_traits)

def update_t0_info_json():
    print("[DEBUG] Starting update_t0_info_json()")

    full_expected_header = [
        "Project Name", "Project Description", "Trait", "Plant ID", "Value", "DNA ID",
        "gDNA", "PCR", "Purification", "Conc", "Screening", "Edit",
        "Edit info", "Link", "Seed", "Trash"
    ]

    # 1. Read existing data and map it to headers
    existing_lookup = {}
    try:
        if os.path.exists('t0_info.json'):
            with open('t0_info.json', 'r') as f:
                existing_data = json.load(f)
            
            if existing_data and len(existing_data) > 1:
                header = existing_data[0]
                for row in existing_data[1:]:
                    row_map = {h: "" for h in full_expected_header}
                    for i, col_name in enumerate(header):
                        if i < len(row) and col_name in row_map:
                            row_map[col_name] = row[i]
                    
                    p_name = row_map.get("Project Name")
                    d_id = row_map.get("DNA ID")
                    if p_name and d_id:
                        existing_lookup[f"{p_name}-{d_id}"] = row_map
    except Exception as e:
        print(f"[DEBUG] Error reading existing t0_info.json: {e}")

    # 2. Get current RS entries from DB
    all_tasks = [dict(row) for row in query_db('SELECT * FROM tasks')]
    rs_entries_from_db = []

    for task in all_tasks:
        is_rs_like = (task.get('workflowTaskKey') in ['rs', 'RS', 'Regeneration', 'RH'] or 
                     task.get('name') in ['RS', 'RS-H', 'RH', 'Regeneration'])
        
        if is_rs_like:
            p_name = task.get('projectName', '')
            trait = task.get('trait_description', '')
            p_desc = task.get('projectDescription', '')
            lines = (task.get('description', '') or "").split("\n")

            for line in lines:
                trimmed = line.strip()
                # Skip summary lines: they typically have 3 parts and are synced from Pre (V1,V2,V3)
                # Real RS entries like "277,1,19-1-1" have IDs that aren't just simple digits or identifiers
                if not trimmed or trimmed.lower().startswith('release'):
                    continue
                
                parts = [p.strip() for p in trimmed.split(',')]
                
                if len(parts) >= 2:
                    rs_id = parts[0]
                    plant_id = parts[1]
                    val = parts[2] if len(parts) > 2 else rs_id
                    
                    # Refined heuristic: Distinguish between RS entry (DNAID, PlantID, Value) and Summary (V1, V2, V3)
                    # A line is a summary if it has 3 parts and BOTH the second and third are numeric (V2, V3)
                    # RS entries usually have a Value with dashes/letters (e.g. 19-1-1)
                    is_summary = False
                    if len(parts) == 3:
                        if plant_id.isdigit() and val.isdigit():
                            is_summary = True
                    
                    if is_summary:
                        continue

                    rs_entries_from_db.append({
                        "Project Name": p_name,
                        "Project Description": p_desc,
                        "Trait": trait,
                        "Plant ID": plant_id,
                        "DNA ID": rs_id,
                        "Value": val
                    })

    # 3. Merge
    final_rows = []
    seen_keys = set()

    for db_entry in rs_entries_from_db:
        key = f"{db_entry['Project Name']}-{db_entry['DNA ID']}"
        if key in seen_keys: continue
        seen_keys.add(key)

        # Start with fresh DB data
        row_map = {h: "" for h in full_expected_header}
        row_map.update(db_entry)

        # Overlay existing custom data
        if key in existing_lookup:
            old_map = existing_lookup[key]
            for h in full_expected_header:
                # Keep custom fields from JSON
                if h not in ["Project Name", "Project Description", "Trait", "Plant ID", "DNA ID", "Value"]:
                    row_map[h] = old_map.get(h, "")
                # If DB is missing something we had before (like Value), keep the old one
                elif not row_map[h] and old_map.get(h):
                    row_map[h] = old_map[h]

        final_rows.append([row_map[h] for h in full_expected_header])

    # Sort
    def sort_key(row):
        try:
            # Sort by Project Name, then DNA ID (as integer if possible)
            p_name = row[0]
            d_id_str = str(row[5])
            d_id_int = int(''.join(filter(str.isdigit, d_id_str)) or 0)
            return (p_name, d_id_int, d_id_str)
        except:
            return ("", 0, "")
    
    final_rows.sort(key=sort_key)

    # 4. Save
    atomic_save_json('t0_info.json', [full_expected_header] + final_rows)
    print(f"[DEBUG] update_t0_info_json complete. {len(final_rows)} rows saved.")

@app.route('/update_t0_info_manual', methods=['POST'])
def update_t0_info_manual():
    try:
        update_t0_info_json()
        flash('T0 info updated successfully!')
        return jsonify(success=True)
    except Exception as e:
        print(f"Error during manual update of t0_info.json: {e}")
        return jsonify(success=False, error=str(e)), 500


@app.route('/save_t0_info', methods=['POST'])
@requires_role('admin', 'editor')
def save_t0_info():
    data = request.get_json()
    if atomic_save_json('t0_info.json', data):
        return jsonify(success=True)
    return jsonify(success=False, error="Save failed"), 500

@app.route('/upload_edit_data', methods=['POST'])
@requires_role('admin', 'editor')
def upload_edit_data():
    if 'file' not in request.files:
        return jsonify(success=False, error='No file part'), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify(success=False, error='No selected file'), 400
    if file and file.filename.endswith('.html'):
        project_name = request.form.get('project_name')
        row_id = request.form.get('row_id') # This is DNA ID for t0_info
        if not project_name or not row_id:
            return jsonify(success=False, error='Missing project_name or row_id'), 400

        filename = f"{project_name.replace(' ', '_')}_{row_id}.html"
        file_path = os.path.join(EDIT_DATA_FOLDER, filename)
        file.save(file_path)

        # Update t0_info.json with the link
        try:
            with open('t0_info.json', 'r') as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return jsonify(success=False, error='t0_info.json not found or is invalid'), 500

        header = data[0]
        body = data[1:]
        
        try:
            dna_id_col_index = header.index('DNA ID')
            link_col_index = header.index('Link')
            project_name_col_index = header.index('Project Name')
        except ValueError as e:
            return jsonify(success=False, error=f'Missing required column in t0_info.json: {e}'), 500

        found = False
        for i, row in enumerate(body):
            if (len(row) > dna_id_col_index and str(row[dna_id_col_index]) == row_id and
                len(row) > project_name_col_index and str(row[project_name_col_index]) == project_name):
                if len(row) <= link_col_index: # Extend row if necessary
                    row.extend([''] * (link_col_index - len(row) + 1))
                row[link_col_index] = filename
                found = True
                break
        
        if found:
            with open('t0_info.json', 'w') as f:
                json.dump(data, f, indent=4)
            return jsonify(success=True, filename=filename)
        else:
            return jsonify(success=False, error='Matching row not found in t0_info.json'), 404
    return jsonify(success=False, error='Invalid file type'), 400

@app.route('/bulk_upload_edit_data', methods=['POST'])
@requires_role('admin', 'editor')
def bulk_upload_edit_data():
    files = request.files.getlist('files[]')
    if not files:
        return jsonify(success=False, error='No files selected'), 400

    try:
        with open('t0_info.json', 'r') as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return jsonify(success=False, error='t0_info.json not found or is invalid'), 500

    header = data[0]
    body = data[1:]
    
    try:
        dna_id_col_index = header.index('DNA ID')
        link_col_index = header.index('Link')
    except ValueError as e:
        return jsonify(success=False, error=f'Missing required column in t0_info.json: {e}'), 500

    # Create a lookup for existing rows by DNA ID
    id_to_row_map = {}
    for i, row in enumerate(body):
        if len(row) > dna_id_col_index:
            id_to_row_map[str(row[dna_id_col_index])] = i

    for file in files:
        if file and file.filename.endswith('.html'):
            filename = file.filename
            # Assuming filename format is PROJECTNAME_DNAID.html or just DNAID.html
            # We need to extract DNA ID from filename.
            # For simplicity, let's assume DNA ID is the part before .html
            file_id = os.path.splitext(filename)[0] 
            # If filename is like ProjectName_DNAID.html, we need to split by last underscore
            if '_' in file_id:
                parts = file_id.rsplit('_', 1)
                if len(parts) == 2:
                    file_id = parts[1] # Assume DNA ID is after the last underscore

            if file_id in id_to_row_map:
                file_path = os.path.join(EDIT_DATA_FOLDER, filename)
                file.save(file_path)
                
                row_index_in_body = id_to_row_map[file_id]
                # Adjust index for 'data' list (skip header)
                actual_row_index = row_index_in_body + 1 
                
                # Ensure row has enough columns for 'Link'
                current_row = data[actual_row_index]
                if len(current_row) <= link_col_index:
                    current_row.extend([''] * (link_col_index - len(current_row) + 1))
                
                data[actual_row_index][link_col_index] = filename

    with open('t0_info.json', 'w') as f:
        json.dump(data, f, indent=4)

    return jsonify(success=True)


@app.route('/view_edit_data/<filename>')
def view_edit_data(filename):
    return send_from_directory(EDIT_DATA_FOLDER, filename)

@app.route('/get_task_details/<int:task_id>')
def get_task_details(task_id):
    print(f"[DEBUG] Received request for task_id: {task_id}")
    task = query_db('SELECT * FROM tasks WHERE id = ?', [task_id], one=True)
    if task:
        print(f"[DEBUG] Found task: {dict(task)}")
        return jsonify(dict(task))
    print(f"[DEBUG] Task with id {task_id} not found.")
    return jsonify({'error': 'Task not found'}), 404


# Progeny Info Routes
PROGENY_INFO_FILE = 'progeny_info.json'
PROGENY_EXPECTED_HEADER = [
    "Project Name", "Project Description", "Trait", "Generation", "Plant ID", "Value", "DNA ID",
    "gDNA", "PCR", "Purification", "Conc", "Screening", "Edit",
    "Edit info", "Link", "Seed", "Trash"
]

@app.route('/progeny_info')
def progeny_info():
    data = []
    try:
        with open(PROGENY_INFO_FILE, 'r') as f:
            data = json.load(f)
        print(f"[DEBUG] Loaded data from {PROGENY_INFO_FILE}. Data head: {data[:2]}")
    except (FileNotFoundError, json.JSONDecodeError):
        print(f"[DEBUG] {PROGENY_INFO_FILE} not found or invalid, starting fresh.")
        data = [PROGENY_EXPECTED_HEADER] # Start with just the header

    filter_project_name = request.args.get('filter_project_name')
    filter_trait = request.args.get('filter_trait')
    filter_generation = request.args.get('filter_generation')

    unique_project_names = []
    unique_traits = []
    unique_generations = []

    if data and len(data) > 1: # Check if there's data beyond just the header
        header = data[0]
        body = data[1:]

        # Populate unique filter options from the full dataset
        if "Project Name" in header:
            unique_project_names = sorted(list(set([row[header.index("Project Name")] for row in body if len(row) > header.index("Project Name")])))
        if "Trait" in header:
            unique_traits = sorted(list(set([row[header.index("Trait")] for row in body if len(row) > header.index("Trait")])))
        if "Generation" in header:
            unique_generations = sorted(list(set([row[header.index("Generation")] for row in body if len(row) > header.index("Generation")])))

        # Apply filters
        filtered_body = body
        if filter_project_name:
            if "Project Name" in header:
                project_name_col_index = header.index("Project Name")
                filtered_body = [row for row in filtered_body if len(row) > project_name_col_index and filter_project_name.lower() == str(row[project_name_col_index]).lower()]
        
        if filter_trait:
            if "Trait" in header:
                trait_col_index = header.index("Trait")
                filtered_body = [row for row in filtered_body if len(row) > trait_col_index and filter_trait.lower() == str(row[trait_col_index]).lower()]

        if filter_generation:
            if "Generation" in header:
                generation_col_index = header.index("Generation")
                filtered_body = [row for row in filtered_body if len(row) > generation_col_index and filter_generation.lower() == str(row[generation_col_index]).lower()]

        # Sort the filtered data (example: by Project Name, then DNA ID)
        def sort_key_progeny(row):
            try:
                project_name = row[header.index("Project Name")] if "Project Name" in header and len(row) > header.index("Project Name") else ""
                dna_id = int(row[header.index("DNA ID")]) if "DNA ID" in header and len(row) > header.index("DNA ID") and str(row[header.index("DNA ID")]).isdigit() else 0
                return (project_name, dna_id)
            except (ValueError, IndexError):
                return (row[0] if len(row) > 0 else "", 0) # Fallback for malformed rows

        filtered_body = sorted(filtered_body, key=sort_key_progeny)
        data = [header] + filtered_body
    else:
        data = [PROGENY_EXPECTED_HEADER] # Ensure header is always present even if no data

    return render_template('progeny_info.html',
                           data=data,
                           unique_project_names=unique_project_names,
                           unique_traits=unique_traits,
                           unique_generations=unique_generations)

@app.route('/save_progeny_info', methods=['POST'])
@requires_role('admin', 'editor')
def save_progeny_info():
    data = request.get_json()
    if atomic_save_json(PROGENY_INFO_FILE, data):
        return jsonify(success=True)
    return jsonify(success=False, error="Save failed"), 500

@app.route('/import_progeny_template', methods=['POST'])
@requires_role('admin', 'editor')
def import_progeny_template():
    if 'file' not in request.files:
        flash('No file part')
        return redirect(url_for('progeny_info'))
    file = request.files['file']
    if file.filename == '':
        flash('No selected file')
        return redirect(url_for('progeny_info'))
    if file and file.filename.endswith('.csv'):
        try:
            stream = io.StringIO(file.stream.read().decode("utf-8-sig"))
            reader = csv.reader(stream)
            csv_data = list(reader)

            if not csv_data:
                flash('CSV file is empty.')
                return redirect(url_for('progeny_info'))

            # Assume first row is header
            header = csv_data[0]
            body = csv_data[1:]

            # Ensure the header matches PROGENY_EXPECTED_HEADER structure
            # For simplicity, we'll just use the CSV header as is, but ensure it has expected columns
            # and pad/truncate rows to match the expected header length for consistency.
            
            # Create a mapping from CSV header to expected header indices
            header_map = {col: i for i, col in enumerate(header)}
            
            processed_data = [PROGENY_EXPECTED_HEADER]
            for row_idx, row in enumerate(body):
                new_row = [''] * len(PROGENY_EXPECTED_HEADER)
                for col_idx, expected_col in enumerate(PROGENY_EXPECTED_HEADER):
                    if expected_col in header_map and header_map[expected_col] < len(row):
                        new_row[col_idx] = row[header_map[expected_col]]
                processed_data.append(new_row)

            with open(PROGENY_INFO_FILE, 'w') as f:
                json.dump(processed_data, f, indent=4)
            flash('Progeny template imported successfully!')
        except Exception as e:
            flash(f'Error importing progeny template: {e}')
    else:
        flash('Invalid file type. Please upload a .csv file.')
    return redirect(url_for('progeny_info'))

@app.route('/upload_progeny_edit_data', methods=['POST'])
@requires_role('admin', 'editor')
def upload_progeny_edit_data():
    if 'file' not in request.files:
        return jsonify(success=False, error='No file part'), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify(success=False, error='No selected file'), 400
    if file and file.filename.endswith('.html'):
        project_name = request.form.get('project_name')
        row_id = request.form.get('row_id') # This is DNA ID for progeny
        if not project_name or not row_id:
            return jsonify(success=False, error='Missing project_name or row_id'), 400

        filename = f"{project_name.replace(' ', '_')}_{row_id}.html"
        file_path = os.path.join(PROGENY_EDIT_DATA_FOLDER, filename)
        file.save(file_path)

        # Update progeny_info.json with the link
        try:
            with open(PROGENY_INFO_FILE, 'r') as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return jsonify(success=False, error=f'{PROGENY_INFO_FILE} not found or is invalid'), 500

        header = data[0]
        body = data[1:]
        
        try:
            dna_id_col_index = header.index('DNA ID')
            link_col_index = header.index('Link')
            project_name_col_index = header.index('Project Name')
        except ValueError as e:
            return jsonify(success=False, error=f'Missing required column in {PROGENY_INFO_FILE}: {e}'), 500

        found = False
        for i, row in enumerate(body):
            if (len(row) > dna_id_col_index and str(row[dna_id_col_index]) == row_id and
                len(row) > project_name_col_index and str(row[project_name_col_index]) == project_name):
                if len(row) <= link_col_index: # Extend row if necessary
                    row.extend([''] * (link_col_index - len(row) + 1))
                row[link_col_index] = filename
                found = True
                break
        
        if found:
            with open(PROGENY_INFO_FILE, 'w') as f:
                json.dump(data, f, indent=4)
            return jsonify(success=True, filename=filename)
        else:
            return jsonify(success=False, error='Matching row not found in progeny_info.json'), 404
    return jsonify(success=False, error='Invalid file type'), 400

@app.route('/bulk_upload_progeny_edit_data', methods=['POST'])
@requires_role('admin', 'editor')
def bulk_upload_progeny_edit_data():
    files = request.files.getlist('files[]')
    if not files:
        return jsonify(success=False, error='No files selected'), 400

    try:
        with open(PROGENY_INFO_FILE, 'r') as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return jsonify(success=False, error=f'{PROGENY_INFO_FILE} not found or is invalid'), 500

    header = data[0]
    body = data[1:]
    
    try:
        dna_id_col_index = header.index('DNA ID')
        link_col_index = header.index('Link')
    except ValueError as e:
        return jsonify(success=False, error=f'Missing required column in {PROGENY_INFO_FILE}: {e}'), 500

    # Create a lookup for existing rows by DNA ID
    id_to_row_map = {}
    for i, row in enumerate(body):
        if len(row) > dna_id_col_index:
            id_to_row_map[str(row[dna_id_col_index])] = i

    for file in files:
        if file and file.filename.endswith('.html'):
            filename = file.filename
            # Assuming filename format is PROJECTNAME_DNAID.html or just DNAID.html
            # We need to extract DNA ID from filename.
            # For simplicity, let's assume DNA ID is the part before .html
            file_id = os.path.splitext(filename)[0] 
            # If filename is like ProjectName_DNAID.html, we need to split by last underscore
            if '_' in file_id:
                parts = file_id.rsplit('_', 1)
                if len(parts) == 2:
                    file_id = parts[1] # Assume DNA ID is after the last underscore

            if file_id in id_to_row_map:
                file_path = os.path.join(PROGENY_EDIT_DATA_FOLDER, filename)
                file.save(file_path)
                
                row_index_in_body = id_to_row_map[file_id]
                # Adjust index for 'data' list (skip header)
                actual_row_index = row_index_in_body + 1 
                
                # Ensure row has enough columns for 'Link'
                current_row = data[actual_row_index]
                if len(current_row) <= link_col_index:
                    current_row.extend([''] * (link_col_index - len(current_row) + 1))
                
                data[actual_row_index][link_col_index] = filename

    with open(PROGENY_INFO_FILE, 'w') as f:
        json.dump(data, f, indent=4)

    return jsonify(success=True)

@app.route('/view_progeny_edit_data/<filename>')
def view_progeny_edit_data(filename):
    return send_from_directory(PROGENY_EDIT_DATA_FOLDER, filename)

@app.route('/delete_progeny_info_row', methods=['POST'])
@requires_role('admin', 'editor')
def delete_progeny_info_row():
    try:
        data = request.get_json()
        row_id_to_delete = data.get('id') # This is DNA ID
        project_name_to_match = data.get('project_name')

        if not row_id_to_delete or not project_name_to_match:
            return jsonify(success=False, error='Missing ID or Project Name'), 400

        try:
            with open(PROGENY_INFO_FILE, 'r') as f:
                current_data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return jsonify(success=False, error=f'{PROGENY_INFO_FILE} not found or is invalid'), 500

        header = current_data[0]
        body = current_data[1:]
        
        try:
            dna_id_col_index = header.index('DNA ID')
            project_name_col_index = header.index('Project Name')
        except ValueError as e:
            return jsonify(success=False, error=f'Missing required column in {PROGENY_INFO_FILE}: {e}'), 500

        new_body = []
        row_deleted = False
        for row in body:
            if (len(row) > dna_id_col_index and str(row[dna_id_col_index]) == row_id_to_delete and
                len(row) > project_name_col_index and str(row[project_name_col_index]) == project_name_to_match):
                row_deleted = True
            else:
                new_body.append(row)
        
        if row_deleted:
            final_data = [header] + new_body
            with open(PROGENY_INFO_FILE, 'w') as f:
                json.dump(final_data, f, indent=4)
            return jsonify(success=True)
        else:
            return jsonify(success=False, error='Row not found'), 404

    except Exception as e:
        print(f"Error deleting progeny info row: {e}")
        return jsonify(success=False, error=str(e)), 500




@app.route('/generate_csv/<int:task_id>')
def generate_csv(task_id):
    global workflows
    task = query_db('SELECT * FROM tasks WHERE id = ?', [task_id], one=True)
    if not task:
        print(f"[DEBUG] CSV Generation failed: Task ID {task_id} not found in DB.")
        return "Task not found", 404

    print(f"[DEBUG] Generating CSV for task: {task['id']} ({task['name']}), Workflow: {task['workflowId']}")

    workflows = load_workflows()
    wf_config = workflows.get(task['workflowType'])
    if not wf_config:
        print(f"[DEBUG] CSV Generation failed: Workflow type '{task['workflowType']}' not found in workflows.json.")
        return "Workflow config not found", 404

    # Find the task template to get the CSV logic
    task_template = next((t for t in wf_config['tasks'] if t['key'] == task['workflowTaskKey']), None)
    if not task_template or not task_template.get('csv_config'):
        return "CSV configuration not defined for this task", 400

    csv_config = task_template['csv_config']
    
    # Fetch all tasks for this workflow to find start and pre equivalents
    workflow_tasks = query_db('SELECT * FROM tasks WHERE workflowId = ?', [task['workflowId']])
    # Sort chronologically to find start equivalent if no key match
    workflow_tasks = [dict(t) for t in workflow_tasks]
    workflow_tasks.sort(key=lambda t: (t['date'], t['id']))
    
    # Get the start task for sub-project names
    start_task = next((t for t in workflow_tasks if t['workflowTaskKey'] in ['start', 'Streaking', 'Transformation']), workflow_tasks[0] if workflow_tasks else None)
    
    # Get the pre task for V2 counts
    pre_task = next((t for t in workflow_tasks if t['workflowTaskKey'] in ['pre', 'Pre-Regeneration', 'Pre-H', 'Pre-S'] or (t.get('name') and t['name'].startswith('Pre'))), None)

    if not start_task:
        print(f"[DEBUG] CSV Generation failed: No start task found for workflow {task['workflowId']}.")
        return "Start task not found", 404

    project_name = task['projectName']
    task_date = datetime.strptime(task['date'], '%Y-%m-%d')
    stage_label = csv_config.get('label', task['name'])

    output = io.StringIO()
    writer = csv.writer(output)
    # Add standardized headers
    writer.writerow(["Project Name", "Stage Label", "Task Date", "Count"])

    start_desc_lines = [line.strip() for line in (start_task['description'] or "").split('\n') if line.strip()]
    if not start_desc_lines: start_desc_lines = ['P1234']

    # Determine row count per sub-project
    if csv_config['type'] == 'fixed':
        for idx, start_entry in enumerate(start_desc_lines):
            # If identifier is not generic, include it in the project name
            display_name = project_name
            if start_entry and start_entry not in ["Initial kick-off task for the transformation project.", "Transformation day", "P1234"]:
                display_name = f"{project_name}-{start_entry}"
            
            rows_per_entry = int(csv_config.get('value', 12))
            for i in range(1, rows_per_entry + 1):
                # 4-column format: Name, Stage, Date, Count
                writer.writerow([display_name, stage_label, task_date.strftime('%m/%d/%Y'), f'#{i}'])

    elif csv_config['type'] == 'formula':
        try:
            val_parts = csv_config.get('value', '6,1.1').split(',')
            divisor = float(val_parts[0])
            multiplier = float(val_parts[1]) if len(val_parts) > 1 else 1.0
        except:
            divisor, multiplier = 6.0, 1.1

        pre_desc_lines = [line.strip() for line in (pre_task['description'] or "").split('\n') if line.strip()] if pre_task else []
        
        for idx, start_entry in enumerate(start_desc_lines):
            v2 = 0
            display_name = project_name
            if start_entry and start_entry not in ["Initial kick-off task for the transformation project.", "Transformation day", "P1234"]:
                display_name = f"{project_name}-{start_entry}"

            if idx < len(pre_desc_lines):
                parsed = parse_pre_description(pre_desc_lines[idx])
                if parsed:
                    v2 = parsed.get('v2', 0)
                    if parsed.get('identifier'):
                        display_name = f"{project_name}-{parsed['identifier']}"
            
            num_rows = math.ceil((v2 / divisor) * multiplier)
            for i in range(1, num_rows + 1):
                # 4-column format: Name, Stage, Date, Count
                writer.writerow([display_name, stage_label, task_date.strftime('%m/%d/%Y'), f'#{i}'])

    elif csv_config['type'] == 'rs_entries':
        lines = [line.strip() for line in (task['description'] or "").split('\n') if line.strip()]
        
        # Check if lines look like individual plant entries (ID,PlantID,Value)
        is_individual = False
        if lines:
            sample_line = next((l for l in lines if not l.lower().startswith('release')), lines[0])
            parts = [p.strip() for p in sample_line.split(',')]
            if len(parts) >= 2 and not (parts[0].isdigit() and parts[1].isdigit()):
                is_individual = True

        if not lines or not is_individual:
            # FALLBACK to formula logic (using data synced from Pre)
            try:
                divisor, multiplier = 6.0, 1.1
                formula_lines = lines if lines else ([l.strip() for l in (pre_task['description'] or "").split('\n') if l.strip()] if pre_task else [])
                
                for idx, start_entry in enumerate(start_desc_lines):
                    v2 = 0
                    display_name = project_name
                    if start_entry and start_entry not in ["Initial kick-off task for the transformation project.", "Transformation day", "P1234"]:
                        display_name = f"{project_name}-{start_entry}"

                    if idx < len(formula_lines):
                        parsed = parse_pre_description(formula_lines[idx])
                        if parsed:
                            v2 = parsed.get('v2', 0)
                            if parsed.get('identifier'):
                                display_name = f"{project_name}-{parsed['identifier']}"
                    
                    num_rows = math.ceil((v2 / divisor) * multiplier)
                    for i in range(1, num_rows + 1):
                        # 4-column format
                        writer.writerow([display_name, stage_label, task_date.strftime('%m/%d/%Y'), f'#{i}'])
            except Exception as e:
                print(f"Error in RS fallback: {e}")
        else:
            # Standard RS individual plant labels
            for line in lines:
                if line.lower().startswith('release strategy'): continue
                parts = [p.strip() for p in line.split(',')]
                if len(parts) >= 2:
                    # Individual plant labels keep Name-ID format for column 1?
                    # Or just keep the parts as they are?
                    # User likely wants consistency, so: PlantID, Stage, Date, ID
                    writer.writerow([parts[1], stage_label, task_date.strftime('%m/%d/%Y'), parts[0]])

    elif csv_config['type'] == 'germplasm_b0':
        # Logic from Germplasm app: B0, B1, B2 dates and multi-stage labels
        workflow_tasks = query_db('SELECT * FROM tasks WHERE workflowId = ?', [task['workflowId']])
        
        # Robust lookup: Check both workflowTaskKey and name
        b0_t = next((tk for tk in workflow_tasks if tk['workflowTaskKey'] == 'B0' or tk['name'] == 'B0'), task)
        b1_t = next((tk for tk in workflow_tasks if tk['workflowTaskKey'] == 'B1' or tk['name'] == 'B1'), None)
        b2_t = next((tk for tk in workflow_tasks if tk['workflowTaskKey'] == 'B2' or tk['name'] == 'B2'), None)
        
        b0_date_f = datetime.strptime(b0_t['date'], '%Y-%m-%d').strftime('%m/%d/%Y')
        b1_date_f = datetime.strptime(b1_t['date'], '%Y-%m-%d').strftime('%m/%d/%Y') if b1_t else ''
        b2_date_f = datetime.strptime(b2_t['date'], '%Y-%m-%d').strftime('%m/%d/%Y') if b2_t else ''
        
        # Default multiplier from Setup 'Value' field
        multiplier = 3
        if csv_config.get('value') and str(csv_config['value']).isdigit():
            multiplier = int(csv_config['value'])
            
        # Default media names from the start task description (the sub-projects)
        media_names = start_desc_lines
        
        # Override if B0 task has a specific description or Pre-style lines
        b0_desc = b0_t['description'] or ""
        b0_lines = [line.strip() for line in b0_desc.split('\n') if line.strip()]
        
        # Ignore default placeholder descriptions
        if b0_lines and ("Task 1" in b0_lines[0] or "B0" in b0_lines[0] and len(b0_lines) == 1):
            b0_lines = []

        if b0_lines:
            # Check if these are Pre-style summary lines
            first_parts = [p.strip() for p in b0_lines[0].split(',')]
            if len(first_parts) >= 2 and first_parts[0].isdigit() and first_parts[1].isdigit():
                # Extract identifiers from these lines
                media_names = []
                for l in b0_lines:
                    parsed = parse_pre_description(l)
                    if parsed and parsed.get('identifier'):
                        media_names.append(parsed['identifier'])
                if not media_names: media_names = start_desc_lines
            else:
                # Normal text lines
                if b0_lines[-1].isdigit():
                    multiplier = int(b0_lines[-1])
                    media_names = b0_lines[:-1] if len(b0_lines) > 1 else start_desc_lines
                else:
                    media_names = b0_lines
        
        if not media_names: media_names = ['P1234']
        
        # Block 1: B0, B1, B2
        for media in media_names:
            for _ in range(multiplier):
                writer.writerow([media, "", f"B0 {b0_date_f}", f"B1 {b1_date_f}", f"B2 {b2_date_f}"])
        # Block 2: B0, B1
        for media in media_names:
            for _ in range(multiplier):
                writer.writerow([media, "", f"B0 {b0_date_f}", f"B1 {b1_date_f}"])
        # Block 3: B0
        for media in media_names:
            for _ in range(multiplier):
                writer.writerow([media, "", f"B0 {b0_date_f}"])

    elif csv_config['type'] == 'germplasm_pre':
        # Logic from Germplasm app: Pre/RS dates and Annex/Conviron locations
        workflow_tasks = query_db('SELECT * FROM tasks WHERE workflowId = ?', [task['workflowId']])
        pre_t = next((tk for tk in workflow_tasks if tk['workflowTaskKey'].lower() == 'pre' or tk['name'].lower() == 'pre'), task)
        rs_t = next((tk for tk in workflow_tasks if tk['workflowTaskKey'].lower() == 'rs' or tk['name'].lower() == 'rs'), None)
        
        pre_date_f = datetime.strptime(pre_t['date'], '%Y-%m-%d').strftime('%m/%d/%Y')
        rs_date_f = datetime.strptime(rs_t['date'], '%Y-%m-%d').strftime('%m/%d/%Y') if rs_t else ''
        
        locations = ([("Annex", "#1")] * 5 + [("Annex", "#2")] * 5 + [("Conviron", "#1")] * 5)
        for loc, num in locations:
            writer.writerow([project_name, f"Pre {pre_date_f}", f"RS {rs_date_f}" if rs_date_f else "RS ", loc, num])

    elif csv_config['type'] == 'germplasm_rs':
        # Logic from Germplasm app: RS date and Annex/Conviron locations
        rs_date_f = task_date.strftime('%m/%d/%Y')
        locations = ([("Annex", "#1")] * 5 + [("Annex", "#2")] * 5 + [("Conviron", "#1")] * 5)
        for loc, num in locations:
            writer.writerow([project_name, f"RS {rs_date_f}", loc, num])

    elif csv_config['type'] == 'custom':
        # Logic from Design Engine: Map columns 1-4, Column 5 is Count
        rows_cfg = csv_config.get('rows', {'source': 'fixed', 'value': '12'})
        rowCountSource = rows_cfg.get('source', 'fixed')
        rowCountValue = rows_cfg.get('value', '12')
        
        pre_desc_lines = [l.strip() for l in (pre_task['description'] or "").split('\n') if l.strip()] if pre_task else []
        current_desc_lines = [l.strip() for l in (task['description'] or "").split('\n') if l.strip()]
        
        # Iterate through every sub-project defined in the start task
        for idx, start_entry in enumerate(start_desc_lines):
            num_rows = 12
            if rowCountSource == 'fixed':
                num_rows = int(rowCountValue) if str(rowCountValue).isdigit() else 12
            elif rowCountSource == 'formula':
                try:
                    p = rowCountValue.split(',')
                    div, mult = float(p[0]), float(p[1]) if len(p) > 1 else 1.0
                except: div, mult = 6.0, 1.1
                v2 = 0
                if idx < len(pre_desc_lines):
                    parsed = parse_pre_description(pre_desc_lines[idx])
                    if parsed: v2 = parsed.get('v2', 0)
                num_rows = math.ceil((v2 / div) * mult)

            # Build the static parts of the 4 columns for this specific sub-project
            row_template = []
            for col_cfg in csv_config.get('cols', []):
                src = col_cfg.get('source', 'none')
                if src == 'sub_project':
                    # Priority: Current Task Ident -> Pre Task Ident -> Start Task Line
                    val = start_entry
                    if idx < len(current_desc_lines):
                        parsed = parse_pre_description(current_desc_lines[idx])
                        if parsed and parsed.get('identifier'): val = parsed['identifier']
                    elif idx < len(pre_desc_lines):
                        parsed = parse_pre_description(pre_desc_lines[idx])
                        if parsed and parsed.get('identifier'): val = parsed['identifier']
                    row_template.append(val)
                elif src == 'task_name': row_template.append(task['name'])
                elif src == 'task_date': row_template.append(task_date.strftime('%m/%d/%Y'))
                elif src == 'manual': row_template.append(col_cfg.get('value', ''))
                else: row_template.append("")

            while len(row_template) < 4: row_template.append("")
            
            # Generate the full set of rows for this sub-project
            for i in range(1, num_rows + 1):
                writer.writerow(row_template + [f'#{i}'])

    csv_data = output.getvalue()
    filename = f"{project_name}_{stage_label}_{task_date.strftime('%m_%d_%Y')}.csv"

    return send_file(
        io.BytesIO(csv_data.encode('utf-8')),
        mimetype='text/csv',
        as_attachment=True,
        download_name=filename
    )





@app.route('/day_view/<date>')
def day_view(date):
    global workflows
    tasks_rows = query_db('SELECT * FROM tasks WHERE date = ?', [date])
    tasks = []
    task_csv_status = {}
    project_v2_status = {}
    
    workflows = load_workflows()

    all_tasks = [dict(row) for row in query_db('SELECT * FROM tasks')]
    # Identify "Pre" tasks for V2 status indicator in day view
    pre_tasks = [t for t in all_tasks if t.get('workflowTaskKey') in ['pre', 'Pre-H', 'Pre-S', 'Pre-Regeneration'] or (t.get('name') and t['name'].startswith('Pre'))]
    for pre_task in pre_tasks:
        if pre_task.get('workflowId'):
            parsed_data = parse_pre_description(pre_task['description'])
            if parsed_data and 'v2' in parsed_data and parsed_data['v2'] is not None:
                project_v2_status[pre_task['workflowId']] = True
            else:
                project_v2_status[pre_task['workflowId']] = False

    for row in tasks_rows:
        t = dict(row)
        tasks.append(t)
        task_csv_status[t['id']] = get_task_csv_status(t)

    return render_template('day_view.html', tasks=tasks, date=date, project_v2_status=project_v2_status, task_csv_status=task_csv_status)



if __name__ == '__main__':
    try:
        from waitress import serve
        print("ProjectFlow is initiating with Waitress on port 5003 (Production Mode)")
        serve(app, host='0.0.0.0', port=5003, threads=4)
    except ImportError:
        print("Waitress not found. Falling back to Flask development server...")
        app.run(host='0.0.0.0', port=5003, debug=True)

