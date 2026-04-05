# Indian PET Plastic Credit Framework — Portal

Interactive portal for calculating PET Collection Credits (PCC) and Processing Credits (PPC) based on the IIT Delhi framework (December 2025).

**Developed by Daksh Gandhi**  
IIT Delhi — Prof Sovik Das · Prof A K Nema · Prof Sudip K. Pattanayek · Dr Anil Dhanda

---

## Project Structure

```
pet-plastic-credit/
├── app.py              ← Flask backend
├── requirements.txt    ← Python dependencies
├── database.db         ← SQLite database (auto-created on first run)
├── templates/
│   ├── login.html      ← Login & Register page
│   ├── dashboard.html  ← Company dashboard
│   └── admin.html      ← Admin overview
└── README.md
```

---

## Setup & Run (VS Code / Local)

### 1. Install Python dependencies
```bash
pip install -r requirements.txt
```

### 2. Run the app
```bash
python app.py
```

### 3. Open in browser
```
http://localhost:5000
```

---

## Default Admin Login

```
Email:    gandhijidaksh@gmail.com
Password: admin123
```

> ⚠️ Change the admin password and `app.secret_key` in `app.py` before deploying publicly.

---

## How it works

### For Companies
1. Go to `http://localhost:5000`
2. Click **Create Account** — enter company name, email, password
3. After login, add PCC (collection) and PPC (processing) entries manually
4. All data is saved to the database and persists between sessions
5. Each company only sees their own data

### For Admin (IIT Delhi)
1. Login with `gandhijidaksh@gmail.com`
2. See all registered companies, their credit totals, and entry counts
3. View full access log — who logged in, when, from which IP

---

## Deploy to Render (free hosting)

1. Push to GitHub
2. Go to [render.com](https://render.com) → New Web Service
3. Connect your GitHub repo
4. Build command: `pip install -r requirements.txt`
5. Start command: `gunicorn app:app`
6. Add to requirements.txt: `gunicorn`

---

## Formulas Used

### PCC (Collection Credits)
```
PCC = Weight (t) × Location Factor (F) × Eco Factor (E) × ESG Multiplier (G)
```

### PPC (Processing Credits)
```
W   = 0.85 × log₁₀(min(15, max(1, service_life))) × Exposure Factor (P)
PPC = Weight (t) × W × ESG Multiplier (G)
```

### ESG Tiers
| Tier | Score | Multiplier |
|------|-------|------------|
| Tier I | > 80 | 1.10 |
| Tier II | 65–80 | 1.05 |
| Tier III | 50–65 | 1.00 |
| Ineligible | < 50 | 0 |
