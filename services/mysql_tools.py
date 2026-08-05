"""Helpers for locating MySQL command-line tools."""

import os
import shutil


def tool_path(name, mysql_bin_dir=""):
    exe = f"{name}.exe" if os.name == "nt" else name
    candidates = []
    if mysql_bin_dir:
        candidates.append(os.path.join(mysql_bin_dir, exe))

    resolved = shutil.which(exe)
    if resolved:
        candidates.append(resolved)

    if os.name == "nt":
        candidates.extend([
            os.path.join(r"E:\MySQL\bin", exe),
            os.path.join(r"D:\MySQL\bin", exe),
            os.path.join(r"D:\mysql\bin", exe),
            os.path.join(r"D:\dvptool\mysql\bin", exe),
            os.path.join(r"C:\Program Files\MySQL\MySQL Server 8.4\bin", exe),
            os.path.join(r"C:\Program Files\MySQL\MySQL Server 8.0\bin", exe),
        ])

    for path in candidates:
        if path and os.path.exists(path):
            return path
    return exe
