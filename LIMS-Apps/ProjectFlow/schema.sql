DROP TABLE IF EXISTS tasks;
CREATE TABLE tasks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  projectName TEXT NOT NULL,
  projectDescription TEXT,
  date TEXT NOT NULL,
  description TEXT,
  color TEXT,
  workflowId INTEGER,
  workflowType TEXT,
  workflowTaskKey TEXT,
  trait_description TEXT,
  assigned_to TEXT DEFAULT ''
);

DROP TABLE IF EXISTS users;
CREATE TABLE users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL -- 'admin', 'editor', 'viewer'
);
