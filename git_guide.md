# Git Guide — MK Balance Automation

This guide covers the Git commands used for the MK Balance Automation project.

---

## 1. Check the current branch and file status

```powershell
git status
```

Useful output examples:

```text
On branch main
Your branch is up to date with 'origin/main'.
nothing to commit, working tree clean
```

Short version:

```powershell
git status --short
```

Common symbols:

```text
M  = modified
A  = added
?? = untracked
```

---

## 2. See available branches

```powershell
git branch
```

Show local and remote branches:

```powershell
git branch -a
```

The branch with `*` is the branch currently checked out.

Example:

```text
* main
  First-main
  num
```

---

## 3. Create a new branch

Create a branch and switch to it:

```powershell
git switch -c branch-name
```

Example:

```powershell
git switch -c dev
```

Switch to an existing branch:

```powershell
git switch main
```

---

## 4. Update remote branch information

```powershell
git fetch origin
```

This downloads the latest branch and commit information from GitHub without changing your working files.

After fetching:

```powershell
git branch -a
```

---

## 5. Stage files before committing

Stage one file:

```powershell
git add app\main.py
```

Stage selected files:

```powershell
git add app\main.py app\browser.py STARTUP.md
```

Stage everything:

```powershell
git add .
```

Only use `git add .` after checking what files are present.

---

## 6. Review exactly what will be committed

Check staged files:

```powershell
git status
```

Review the actual code changes:

```powershell
git diff --staged
```

Press:

```text
q
```

to exit the Git diff viewer.

---

## 7. Remove a file from the upcoming commit

Unstage a file:

```powershell
git restore --staged path\to\file
```

Example:

```powershell
git restore --staged decision\balance_decision.py
```

This does NOT delete the file.

---

## 8. Discard an uncommitted change

WARNING: this removes your local modification.

```powershell
git restore app\main.py
```

Only use this when you are certain you do not need the local change.

---

## 9. Commit changes

```powershell
git commit -m "Describe the change"
```

Example:

```powershell
git commit -m "Restore working balance automation"
```

Use clear commit messages describing what changed.

---

## 10. View recent commit history

```powershell
git log --oneline --decorate -10
```

Example:

```text
af348a6 Merge branch 'First-main'
f50a4ad Restore working balance automation and add decision engine
```

---

## 11. Push a branch to GitHub

First push for a new branch:

```powershell
git push -u origin branch-name
```

Example:

```powershell
git push -u origin First-main
```

After the tracking relationship is created, future pushes can usually use:

```powershell
git push
```

---

## 12. Push main to GitHub

When local `main` is ready:

```powershell
git push origin main
```

---

## 13. Pull the latest changes

```powershell
git pull
```

Or explicitly:

```powershell
git pull origin main
```

Do this carefully if you have local uncommitted changes.

Check first:

```powershell
git status
```

---

## 14. Clone the project into a new folder

Move to the parent directory:

```powershell
cd "C:\Users\Kovid Singh Parihar\Documents\My projects\MK balance"
```

Clone:

```powershell
git clone git@github.com:Kovid01/automation-platform.git automation-platform-test
```

Then enter the new folder:

```powershell
cd automation-platform-test
```

Verify:

```powershell
git status
git branch
```

---

## 15. GitHub SSH authentication

Test GitHub authentication:

```powershell
ssh -T git@github.com
```

Expected result:

```text
Hi Kovid01! You've successfully authenticated, but GitHub does not provide shell access.
```

---

## 16. Use the new GitHub SSH key

The current GitHub key is:

```text
C:\Users\Kovid Singh Parihar\.ssh\id_ed25519_github
```

Add it to the SSH agent:

```powershell
ssh-add "$HOME\.ssh\id_ed25519_github"
```

Check loaded keys:

```powershell
ssh-add -l
```

---

## 17. Start the Windows SSH Agent

Check:

```powershell
Get-Service ssh-agent
```

If stopped, Administrator PowerShell may be required.

Set startup mode:

```powershell
Set-Service -Name ssh-agent -StartupType Manual
```

Start:

```powershell
Start-Service ssh-agent
```

Verify:

```powershell
Get-Service ssh-agent
```

Expected:

```text
Running
```

---

## 18. Force Git to use Windows OpenSSH

For this repository:

```powershell
git config core.sshCommand "C:/Windows/System32/OpenSSH/ssh.exe"
```

This fixed the SSH issue where normal `ssh -T` worked but `git push` did not.

---

## 19. Clone using the specific GitHub SSH key

If a normal clone gives:

```text
Permission denied (publickey)
```

use:

```powershell
$env:GIT_SSH_COMMAND='C:/Windows/System32/OpenSSH/ssh.exe -i "C:/Users/Kovid Singh Parihar/.ssh/id_ed25519_github" -o IdentitiesOnly=yes'
```

Then:

```powershell
git clone git@github.com:Kovid01/automation-platform.git automation-platform-test
```

---

## 20. Merge one branch into another

Example:

```powershell
git switch main
```

Then:

```powershell
git merge First-main
```

If the histories are unrelated:

```powershell
git merge First-main --allow-unrelated-histories
```

Only use `--allow-unrelated-histories` when you understand why the histories are separate.

---

## 21. If Git opens Vim for a merge message

Git may display:

```text
Merge branch 'First-main'
```

To accept the message:

1. Press `Esc`
2. Type:

```text
:wq
```

3. Press Enter

This saves the message and closes Vim.

---

## 22. Important ignored files

The project `.gitignore` should prevent Git from tracking:

```text
.venv/
.env
.env.*
logs/
*.log
chrome-profile/
__pycache__/
.vscode/
.idea/
```

These should normally never be committed.

Especially important:

```text
.env
chrome-profile/
```

They may contain sensitive credentials or session information.

---

## 23. Safe workflow before every commit

Use this sequence:

```powershell
git status
```

Then:

```powershell
git diff
```

Stage selected files:

```powershell
git add <files>
```

Review:

```powershell
git status
git diff --staged
```

Commit:

```powershell
git commit -m "Clear description"
```

Push:

```powershell
git push
```

---

## 24. Recommended branch workflow

Keep:

```text
main
```

as the stable version.

Create development branches for new work:

```powershell
git switch main
git pull
git switch -c dev-feature-name
```

Make and test changes there.

When stable:

```powershell
git add ...
git commit -m "..."
git push -u origin dev-feature-name
```

Then merge into `main` only after the feature is tested.

---

## 25. Emergency rule

Before any risky Git operation, run:

```powershell
git status
```

If unsure, do NOT use:

```powershell
git reset --hard
git clean -fd
git push --force
```

until you understand exactly what they will remove or overwrite.