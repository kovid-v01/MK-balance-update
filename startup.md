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

## 6. Start a Chromium Browser Manually (Optional)

Normal operation should use `python app\main.py` (or `python app\main.py chrome`).
The app starts and supervises its dedicated Chrome profile, including automatic
recovery after repeated DevTools connection failures. Use the manual approach
below only for troubleshooting or when explicitly using `existing` mode.

Close all existing browser windows first if the chosen profile is already in use.

Set the browser executable path you want to use:

```powershell
$env:CHROME_BROWSER_PATH = "C:\Program Files\Google\Chrome\Application\chrome.exe"
```

Or use Brave:

```powershell
$env:BRAVE_BROWSER_PATH = "C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"
```

Then run:

```powershell
& $env:CHROME_BROWSER_PATH --remote-debugging-port=9222 --user-data-dir="C:\chrome-debug-profile"
```

Or, for Brave:

```powershell
& $env:BRAVE_BROWSER_PATH --remote-debugging-port=9222 --user-data-dir="C:\brave-debug-profile"
```

Keep this browser window open.

Open the required pages in this browser instance:

* Retailer Dashboard
* WhatsApp Web

Make sure both are logged in before starting the automation.

---

## 7. Run a Second Automation with Its Own Browser Profile

Use a separate browser profile and remote-debugging port for each automation.
This is the supported way to run two automations in parallel because each one
has independent browser tabs and WhatsApp state.

In a second browser terminal, start Chrome with port `9223` and a new profile:

```powershell
$env:CHROME_BROWSER_PATH = "C:\Program Files\Google\Chrome\Application\chrome.exe"
& $env:CHROME_BROWSER_PATH --remote-debugging-port=9223 --user-data-dir="C:\chrome-debug-profile-2"
```

Log in to the retailer portal and WhatsApp Web in that second browser. Then,
in a second automation terminal, point the application to port `9223` before
starting it:

```powershell
cd "C:\Users\Kovid Singh Parihar\Documents\My projects\MK balance\automation-platform-test"
.\.venv\Scripts\Activate.ps1

$env:REMOTE_DEBUGGING_PORT = "9223"
$env:WHATSAPP_GROUP_NAME = "Automations test 2"
python app\main.py
```

Use a separate WhatsApp group for the second automation unless duplicate
messages to the same group are intentional.

## 8. Two Automations Sharing One Browser Profile (Not Recommended)

Two application processes can attach to the same already-running browser
profile on port `9222`. Start the browser once, then run this command in each
of two separate automation terminals:

```powershell
python app\main.py
```

Both processes will control the same portal and WhatsApp tabs. They can race
to refresh pages, search chats, type messages, and send duplicate updates.
Use this only for short-lived troubleshooting; do not use it for normal
operations. Do not start the second process with `python app\main.py chrome`,
because Chrome cannot safely open the same profile in a second browser process.

---

## 9. Run the Automation

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
portal on 5-minute wall-clock boundaries and sends the balance to the WhatsApp
group `Automations test`.

To let the app launch a browser profile for you, pass a browser name:

```powershell
python app\main.py brave
python app\main.py chrome
```

Use `chrome` or `brave` to launch that browser with its own remote-debug profile.
If you omit the argument, the app launches and supervises its dedicated Chrome
profile. Use `python app\main.py existing` only when you intentionally want to
attach to a browser you started yourself; that mode cannot restart Chrome
automatically.

Optional environment variables:

```powershell
$env:WHATSAPP_GROUP_NAME = "Automations test"
$env:CHECK_INTERVAL_SECONDS = "300"
$env:PORTAL_URL = "https://example-portal-url/"
$env:WHATSAPP_URL = "https://web.whatsapp.com/"
$env:CHROME_BROWSER_PATH = "C:\Program Files\Google\Chrome\Application\chrome.exe"
$env:CHROME_USER_DATA_DIR = "C:\chrome-debug-profile"
$env:BRAVE_BROWSER_PATH = "C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"
$env:BRAVE_USER_DATA_DIR = "C:\brave-debug-profile"
$env:REMOTE_DEBUGGING_PORT = "9222"
```

If the portal or WhatsApp tab is missing, the app will open the URL in a new
tab inside the same remote-debug browser session.

---

# Quick Startup

For normal daily startup, use one automation terminal. It starts and monitors
the dedicated Chrome profile itself:

### Do not start Chrome separately

`main.py` launches Chrome automatically. Starting a second process against the
same profile prevents reliable self-healing.

### Automation

```powershell
cd "C:\Users\Kovid Singh Parihar\Documents\My projects\MK balance\automation-platform-test"

.\.venv\Scripts\Activate.ps1

git status

git branch

python app\main.py

# Or use Brave with its own dedicated profile:
# python app\main.py brave
```

On the first run, sign in to the retailer portal and WhatsApp Web in the
dedicated window. Later starts restore that same profile automatically.

The automation no longer brings Chrome to the front on each check. You can
leave the Chrome window behind other work, or minimize it.

---

# Run Without Cursor

Cursor is only the editor. The automation is a normal Python process and does
not need Cursor open after it has been started.

Keep this computer signed in. Chrome still needs a real desktop session, so
this cannot run as a hidden Windows service while nobody is logged in.

## Option 1: Independent PowerShell window

Close Cursor if you want. Open Windows PowerShell (not Cursor's terminal):

```powershell
cd "C:\Users\Kovid Singh Parihar\Documents\My projects\MK balance\automation-platform-test"
.\.venv\Scripts\Activate.ps1
python app\main.py
```

Minimize that PowerShell window. Leave it running. Logs still go to
`logs\app.log`.

Stop it by restoring that window and pressing `Ctrl + C`.

## Option 2: Start at Windows logon (Task Scheduler)

Create a task that runs only when you are logged on:

* Program: `C:\Users\Kovid Singh Parihar\Documents\My projects\MK balance\automation-platform-test\.venv\Scripts\python.exe`
* Arguments: `app\main.py`
* Start in: `C:\Users\Kovid Singh Parihar\Documents\My projects\MK balance\automation-platform-test`
* Trigger: At log on (your user account)
* Run only when the user is logged on

Do not choose "Run whether user is logged on or not". Chrome will not work
correctly in that mode.

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

If Chrome or Brave remote debugging is running correctly, port `9222` should appear.

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
