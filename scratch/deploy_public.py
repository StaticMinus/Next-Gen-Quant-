import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path("c:/Users/David/Music/Trade/AgentQuant-main")
WEBAPP = ROOT / "webapp"
DEPLOY_DIR = ROOT / "scratch" / "agentquant_public_repo"

if DEPLOY_DIR.exists():
    shutil.rmtree(DEPLOY_DIR, ignore_errors=True)

DEPLOY_DIR.mkdir(parents=True, exist_ok=True)

# Copy webapp files
for item in WEBAPP.iterdir():
    if item.is_file():
        shutil.copy2(item, DEPLOY_DIR / item.name)

print("Files copied to", DEPLOY_DIR)

def run(cmd, cwd=DEPLOY_DIR):
    print("Running:", cmd)
    res = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True)
    print("STDOUT:", res.stdout.strip())
    if res.stderr:
        print("STDERR:", res.stderr.strip())
    return res

run("git init")
run("git config user.name StaticMinus")
run("git config user.email staticminus@gmail.com")
run("git branch -M main")
run("git add .")
run("git commit -m \"feat: Apple-style AgentQuant Pro Web App\"")

# Check if repo already exists on GitHub
check = subprocess.run("gh repo view StaticMinus/agentquant-pro --json name", shell=True, capture_output=True, text=True)
if "agentquant-pro" in check.stdout:
    print("Repo StaticMinus/agentquant-pro exists, pushing to main...")
    run("git remote add origin https://github.com/StaticMinus/agentquant-pro.git")
    run("git push -u origin main --force")
else:
    print("Creating public repo StaticMinus/agentquant-pro...")
    run("gh repo create StaticMinus/agentquant-pro --public --source=. --remote=origin --push")

# Enable GitHub Pages on the new public repository
print("Enabling GitHub Pages on StaticMinus/agentquant-pro...")
pages_res = subprocess.run(
    "gh api -X POST repos/StaticMinus/agentquant-pro/pages -f source[branch]=main -f source[path]=/",
    shell=True,
    capture_output=True,
    text=True
)
print("Pages API output:", pages_res.stdout.strip(), pages_res.stderr.strip())
