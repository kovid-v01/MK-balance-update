# Automation Platform — Terminal Startup Guide

Run the following commands from PowerShell when starting the project.

---

## 1. Go to the Project Folder

```powershell
cd "C:\Users\Kovid Singh Parihar\Documents\My projects\MK balance\automation-platform-test"
```

---

## 2. Activate the Virtual Environment

```powershell
.\.venv\Scripts\Activate.ps1
```

After activation, the terminal should start with:

```text
(.venv) PS
```

---

## 3. Install / Verify Dependencies

Usually this is only required after creating the environment or when `requirements.txt` changes.

```powershell
pip install -r requirements.txt
```

---

## 4. Check Git Status

```powershell
git status
```

---

## 5. Check Current Git Branch

```powershell
git branch
```

Development/testing should currently be performed on:

```text
test-balance-logic
```

If you are not on this branch:

```powershell
git switch test-balance-logic
```

---

## 6. Start Chrome in Remote Debugging Mode

Close all existing Chrome windows first if Chrome is already using the required profile.

Then run:

```powershell
& "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="C:\chrome-debug-profile"
```

Keep this Chrome window open.

Open the required pages in this Chrome instance:

* Retailer Dashboard
* WhatsApp Web

Make sure both are logged in before starting the automation.

---

## 7. Run the Automation

Open another PowerShell terminal in Cursor.

Activate the environment if necessary:

```powershell
.\.venv\Scripts\Activate.ps1
```

Then start the application:

```powershell
python app\main.py
```

The script now runs continuously in a scheduling loop. By default it checks the
portal every 300 seconds and sends the balance to the WhatsApp group
`Automations test`.

Optional environment variables:

```powershell
$env:WHATSAPP_GROUP_NAME = "Automations test"
$env:CHECK_INTERVAL_SECONDS = "300"
```

---

# Quick Startup

For normal daily startup, the main commands are:

### Terminal 1 — Chrome

```powershell
cd "C:\Users\Kovid Singh Parihar\Documents\My projects\MK balance\automation-platform-test"

.\.venv\Scripts\Activate.ps1

& "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="C:\chrome-debug-profile"
```

### Terminal 2 — Automation

```powershell
cd "C:\Users\Kovid Singh Parihar\Documents\My projects\MK balance\automation-platform-test"

.\.venv\Scripts\Activate.ps1

git status

git branch

python app\main.py
```

---

# Stop the Automation

In the terminal running `main.py`, press:

```text
Ctrl + C
```

---

# Git Commands

## See Current Changes

```powershell
git status
```

## See Exactly What Changed

```powershell
git diff
```

## See Branches

```powershell
git branch
```

## Switch to Test Branch

```powershell
git switch test-balance-logic
```

## Stage Changes

```powershell
git add .
```

## Commit Changes

```powershell
git commit -m "Describe the change here"
```

## Push the Current Branch

```powershell
git push
```

If the branch has never been pushed before:

```powershell
git push -u origin test-balance-logic
```

---

# Python / Environment Commands

## Check Python Version

```powershell
python --version
```

## Check Installed Packages

```powershell
pip list
```

## Install Dependencies

```powershell
pip install -r requirements.txt
```

## Update requirements.txt

If a new Python package is installed:

```powershell
pip freeze > requirements.txt
```

---

# Troubleshooting

## Check Whether Port 9222 Is Running

```powershell
netstat -ano | findstr :9222
```

If Chrome remote debugging is running correctly, port `9222` should appear.

## Check Git Remote

```powershell
git remote -v
```

## Check Recent Commits

```powershell
git log --oneline -10
```

## Exit Virtual Environment

```powershell
deactivate
```

---

# Current Development Branch

```text
test-balance-logic
```

Use this branch for testing the new balance decision logic.

Do not merge into `main` until the changes have been tested successfully.
