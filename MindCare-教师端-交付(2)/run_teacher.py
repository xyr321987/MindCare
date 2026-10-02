# -*- coding: utf-8 -*-
"""PyInstaller 入口：教师端（打包成独立 exe 时用，见 build-exe.md）。"""
import sys

from teacher_desktop.app.main import main

if __name__ == "__main__":
    sys.exit(main())
