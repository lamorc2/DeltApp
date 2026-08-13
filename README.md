# Delts App

Project Overview:
Delts App is a fraternity management web application designed to streamline the day-to-day operations of Delta Tau Delta - Upsilon Chapter at RPI.
Hosted on Railway, it utilizes an postgreSQL database and offers a central point to track points, budget and daily tasks. 

To test:
visit https://deltsapp-staging.up.railway.app/
Login:
user: test
password: test
This is a staging website available for anyone to view/test. Please send any bug finds to lamorc2@rpi.edu

## Run locally

Do **not** set `DATABASE_URL`. With it unset, the app uses a local SQLite file (`brotherhood_system.db`) and seeds `admin` / `admin123`.

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Then open http://localhost:5000 and sign in as `admin` / `admin123`.

`.venv/` is created by that first command — you do not edit anything inside it. Packages are installed with `pip install -r requirements.txt`. An optional `.env` (see `.env.example`) can set `SECRET_KEY`; it is not required for local SQLite.

### AI USE DISCLOSURE ###
This was created with the assistance of Anthropic's Claude AI (especially the UI). An original barebones application was created in C++, and using Claude, iterated to add a 
cleaner front end, as well as add extra features. 

Motivations:
I work as the Steward of the Upsilon chapter, which means I balance budgeting, cooking and management all at the same time. We had no centralized system for most of these things, 
especially our points system, which made it feel generally not real. To encourage enforcement of points + completion of chores, as well as reduce errors in our finance system, I decided to
create this project. 

Tech Stack:
-Flask
-Gunicorn
-PostgreSQL
-psycopg2

Key Features:
-Daily Task Tracking + Assignment
-Budget Requests + Tracking
-Point Leaderboard 
-Random Brother Wheel 

About the Author: 
	
	Connor LaMora

		- Electrical and Computer Systems Engineering student at Rensselaer Polytechnic Institute
		- Passionate about Game Design, Cybersecurity, and all things programming
		- For questions or collaboration inquiries, contact me at lamorc2@rpi.edu or connorlamora@gmail.com
