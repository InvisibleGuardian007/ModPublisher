@echo off
rem 源码运行（开发用）：无控制台窗口，直接打开发布器界面
rem 注意：PATH 上的 python/pythonw 是 2.7，必须经 py 启动器指定 3.x
cd /d "%~dp0"
start "" pyw -3 mod_publisher.py
