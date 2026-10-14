# MK Balance Automation — Agent Instructions

## Project Purpose

This project monitors the MK balance from the retailer portal and sends operational updates through WhatsApp.

The project currently uses browser automation to:

1. Connect to an existing browser session.
2. Open/find the retailer dashboard.
3. Refresh and extract the current balance on a portal interval.
4. Apply decision logic.
5. Send WhatsApp only for an MK/LIMIT request or a new 50 L / 30 L / 10 L alert.
6. Poll the WhatsApp group for incoming MK or LIMIT messages more often than the portal refresh.

## Important Files

* `app/main.py` — main application flow and scheduling.
* `app/browser.py` — browser automation, portal interaction, and WhatsApp interaction.
* `startup.md` — terminal commands required to start and operate the project.
* `.env` — environment variables and secrets.
* `requirements.txt` — Python dependencies.

Additional decision-engine and LLM files may be added as the project evolves.

## Development Branch

Development and testing should currently be performed on:

```text
test-balance-logic
```

Do not merge or push changes to `main` unless explicitly requested.

Before making significant changes, check:

```powershell
git status
git branch
```

## Balance Rules

Hard operational rules must remain deterministic Python rules.

### Negative Balance Rule

If:

```text
balance < 0
```

then:

* Do not send the balance to WhatsApp.
* Do not send an alert.
* Log the negative balance for troubleshooting.
* Continue running the automation.
* Do not allow an LLM to override this rule.

### Message suppression

If:

```text
balance < 2000
```

then:

* Do not send a LIMIT reply.
* Do not send a threshold alert.
* Log the suppressed balance and continue.

### WhatsApp send rules

* Do not send a routine balance on the portal schedule.
* Send a normal balance only when a new group message contains `MK` or `LIMIT` as a whole word (case-insensitive). The group title itself does not count. Our own balance posts do not count even if they contain `MK`.
* First time the balance drops below 50 L, 30 L, or 10 L, send the balance then an `@all` alert once. Persist that threshold only if the alert send succeeds. Clear it if the balance recovers so a later drop can alert again.
* Do not put the word `LIMIT` in outbound WhatsApp copy.

## LLM Architecture

The project will use an LLM as an advisory decision layer.

The LLM may:

* Analyse the current balance.
* Compare current and previous balances.
* Identify unusual balance drops.
* Determine severity.
* Recommend whether an update or alert should be sent.
* Generate concise WhatsApp messages.
* Explain the reason for a recommendation.
* Analyse operational context where appropriate.

The LLM must not directly control browser actions without deterministic validation in Python.

Preferred flow:

```text
Portal
  ↓
Extract balance
  ↓
Hard Python rules
  ↓
LLM analysis
  ↓
Structured decision
  ↓
Python validation
  ↓
WhatsApp action
```

## LLM Output

Prefer structured responses instead of free-form decisions.

Example:

```json
{
  "action": "ALERT",
  "severity": "HIGH",
  "message": "MK balance has dropped significantly.",
  "reason": "Balance decreased substantially compared with the previous check."
}
```

Suggested actions:

* `SEND_BALANCE`
* `ALERT`
* `NO_ACTION`

Suggested severity:

* `NORMAL`
* `WARNING`
* `HIGH`
* `CRITICAL`

## Safety Rules

Never:

* Commit `.env`.
* Print API keys, passwords, tokens, or credentials into logs.
* Hard-code secrets.
* Send an alert solely because an LLM requested it without validating the result.
* Remove existing operational rules without explicit approval.
* Modify Git history or force-push unless explicitly requested.
* Merge into `main` automatically.

## Environment

This project uses a Python virtual environment:

```powershell
.\.venv\Scripts\Activate.ps1
```

Install dependencies using:

```powershell
pip install -r requirements.txt
```

Run the application using:

```powershell
python app\main.py
```

## Development Approach

When modifying the project:

1. Read the relevant existing code before proposing changes.
2. Preserve currently working browser automation unless modification is necessary.
3. Make small changes rather than large rewrites.
4. Explain significant architectural changes before implementing them.
5. Keep business rules separate from browser automation.
6. Prefer creating a dedicated decision engine for decision logic.
7. Prefer creating a dedicated LLM module for model interaction.
8. Add logging around important decisions.
9. Handle LLM/API failures gracefully.
10. The automation must continue working even when the LLM service is unavailable.

## Desired Architecture

The project should gradually move toward:

```text
app/
├── main.py
├── browser.py
├── decision_engine.py
├── llm.py
└── config.py
```

Responsibilities:

### `main.py`

Orchestration and scheduling.

### `browser.py`

Portal and WhatsApp browser interactions.

### `decision_engine.py`

Deterministic operational rules and validation of LLM recommendations.

### `llm.py`

LLM/API communication and structured responses.

### `config.py`

Configuration loading and validation.

## Reliability Principle

The balance monitoring system must not depend entirely on the LLM.

If the LLM fails, times out, returns invalid data, or is unavailable, deterministic Python logic should provide a safe fallback and the automation should continue running.
