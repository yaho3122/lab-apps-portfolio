import sqlite3
import json
import os
import shutil
from datetime import date, timedelta

# --- Configuration ---
DATABASE = 'database.db'
T0_INFO = 't0_info.json'
PROGENY_INFO = 'progeny_info.json'
FOLDERS_TO_CLEAR = ['edit_data', 'progeny_edit_data', 'backups']

T0_HEADER = [
    "Project Name", "Project Description", "Trait", "Plant ID", "Value", "DNA ID",
    "gDNA", "PCR", "Purification", "Conc", "Screening", "Edit",
    "Edit info", "Link", "Seed", "Trash"
]

PROGENY_HEADER = [
    "Project Name", "Project Description", "Trait", "Generation", "Plant ID", "Value", "DNA ID",
    "gDNA", "PCR", "Purification", "Conc", "Screening", "Edit",
    "Edit info", "Link", "Seed", "Trash"
]

SYNTHETIC_PROJECTS = [
    # Transformation Projects
    {"name": "GE-2025-07", "desc": "Heat Tolerance Study", "trait": "HSP70 (Heat Shock Protein)", "type": "transformation", "start_offset": -250},
    {"name": "GE-2025-09", "desc": "Drought Resistance Phase 1", "trait": "DREB1A (Transcription Factor)", "type": "transformation", "start_offset": -180},
    {"name": "GE-2025-11", "desc": "Nitrogen Use Efficiency", "trait": "NRT2.1 (Nitrate Transporter)", "type": "transformation", "start_offset": -120},
    {"name": "GE-2026-01", "desc": "Biofortification Study", "trait": "Ferritin-V1", "type": "transformation", "start_offset": -60},
    {"name": "GE-2026-03", "desc": "Photosynthesis Enhancement", "trait": "RuBisCO-Opt", "type": "transformation", "start_offset": -10},

    # Germplasm Optimization Projects
    {"name": "GO-2025-08", "desc": "Line A1 Media Optimization", "trait": "Callus Induction Rate", "type": "Germplasm Optimization", "start_offset": -220},
    {"name": "GO-2025-10", "desc": "Line B2 Regeneration Study", "trait": "Regeneration Frequency", "type": "Germplasm Optimization", "start_offset": -150},
    {"name": "GO-2026-02", "desc": "Elite Line C5 Validation", "trait": "Embryogenic Potential", "type": "Germplasm Optimization", "start_offset": -40},

    # Agrobateria mediate transformation (AMT)
    {"name": "AMT-2025-07", "desc": "Vector pCAMBIA Test", "trait": "GUS Reporter", "type": "Agrobateria mediate transformation", "start_offset": -240},
    {"name": "AMT-2025-12", "desc": "Binary Vector Efficiency", "trait": "eGFP (Green Fluorescence)", "type": "Agrobateria mediate transformation", "start_offset": -90},
    {"name": "AMT-2026-03", "desc": "New Strain Optimization", "trait": "Bar (Herbicide Resistance)", "type": "Agrobateria mediate transformation", "start_offset": -5}
]

def sanitize():
    print("🚀 Starting application sanitization...")

    # 1. Clear Database
    if os.path.exists(DATABASE):
        conn = sqlite3.connect(DATABASE)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM tasks")
        conn.commit()
        conn.close()
        print(f"✅ Cleared tasks from {DATABASE}")

    # 2. Reset JSON files
    with open(T0_INFO, 'w') as f:
        json.dump([T0_HEADER], f, indent=4)
    print(f"✅ Reset {T0_INFO}")

    with open(PROGENY_INFO, 'w') as f:
        json.dump([PROGENY_HEADER], f, indent=4)
    print(f"✅ Reset {PROGENY_INFO}")

    # 3. Clear Folders
    for folder in FOLDERS_TO_CLEAR:
        if os.path.exists(folder):
            for filename in os.listdir(folder):
                file_path = os.path.join(folder, filename)
                try:
                    if os.path.isfile(file_path) or os.path.islink(file_path):
                        os.unlink(file_path)
                    elif os.path.isdir(file_path):
                        shutil.rmtree(file_path)
                except Exception as e:
                    print(f'Failed to delete {file_path}. Reason: {e}')
            print(f"✅ Cleared folder: {folder}")

    # 4. Inject Synthetic Data
    print("🧪 Injecting synthetic data...")
    inject_synthetic_data()

def inject_synthetic_data():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Load Workflows to get task templates
    with open('workflows.json', 'r') as f:
        workflows = json.load(f)

    project_colors = ['#FFB3BA', '#BAFFC9', '#BAE1FF', '#FFFFBA']

    for i, p in enumerate(SYNTHETIC_PROJECTS):
        wf_type = p['type']
        if wf_type not in workflows:
            continue
        
        wf_config = workflows[wf_type]
        start_date = date.today() + timedelta(days=p['start_offset'])
        color = project_colors[i % len(project_colors)]
        workflow_id = i + 1

        last_task_date = start_date
        for j, task_template in enumerate(wf_config['tasks']):
            # Calculate date
            if j > 0:
                off = task_template['offset']
                if off['unit'] == 'days':
                    last_task_date += timedelta(days=off['value'])
                else:
                    last_task_date += timedelta(weeks=off['value'])
            
            # Synthetic description logic
            desc = task_template['description']
            if task_template['key'] == 'pre':
                desc = "450,120,12"
            elif task_template['key'] == 'start':
                desc = "Line-X\nLine-Y"
            elif task_template['key'] == 'B0':
                desc = "Media-A\nMedia-B\n12" # Multiplier 12
            elif wf_type == "Agrobateria mediate transformation":
                # For custom logic based on identifiers
                desc = "Strain-EHA105\nStrain-LBA4404"

            cursor.execute('''
                INSERT INTO tasks (name, projectName, projectDescription, date, description, color, workflowId, workflowType, workflowTaskKey, trait_description)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', [
                task_template['name'], p['name'], p['desc'], last_task_date.isoformat(),
                desc, color, workflow_id, wf_type, task_template['key'], p['trait']
            ])

    conn.commit()
    conn.close()
    print("✅ Synthetic data injection complete.")

if __name__ == "__main__":
    sanitize()
