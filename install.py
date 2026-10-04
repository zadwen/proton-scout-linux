#!/usr/bin/env python3
"""Install Proton Scout into this user's applications menu. No root needed."""
import os
import shutil
import sys
from pathlib import Path

source = Path(__file__).resolve().parent
target = Path.home() / '.local/share/proton-scout'
target.mkdir(parents=True, exist_ok=True)
for name in ('app.py', 'core.py', 'run.sh', 'README.md', 'LICENSE', 'NOTICE.md'):
    if source != target:
        shutil.copy2(source / name, target / name)
if source != target:
    shutil.copytree(source / 'web', target / 'web', dirs_exist_ok=True)
(target / 'run.sh').chmod(0o755)
def quote(value):
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('`', '\\`').replace('$', '\\$').replace('%', '%%') + '"'
applications = Path.home() / '.local/share/applications'
applications.mkdir(parents=True, exist_ok=True)
(applications / 'proton-scout.desktop').write_text('[Desktop Entry]\nType=Application\nName=Proton Scout\nComment=Hardware-aware Proton community recommendations\nExec=' + quote(sys.executable) + ' ' + quote(target / 'app.py') + '\nIcon=applications-games\nTerminal=false\nCategories=Game;Utility;\n')
print('Installed. Open Proton Scout from your applications menu.')
