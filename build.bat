@echo off
chcp 65001 >nul
echo ========================================
echo    浮动控制台 - 一键打包工具
echo ========================================
echo.

:: 检查 Python 是否安装
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未检测到 Python，请先安装 Python 3.7+
    pause
    exit /b 1
)

echo [1/4] 检查并安装依赖...
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
if errorlevel 1 (
    echo [警告] 依赖安装可能存在问题，继续尝试打包...
)

echo.
echo [2/4] 检查 PyInstaller...
pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo 正在安装 PyInstaller...
    pip install pyinstaller -i https://pypi.tuna.tsinghua.edu.cn/simple
)

echo.
echo [3/4] 开始打包应用程序...
pyinstaller --onefile ^
    --windowed ^
    --name "浮动控制台" ^
    --hidden-import=win32timezone ^
    --hidden-import=win32api ^
    --hidden-import=win32con ^
    --hidden-import=win32gui ^
    --hidden-import=win32process ^
    --collect-all pywin32 ^
    --noconsole ^
    floating_console.py

if errorlevel 1 (
    echo.
    echo [错误] 打包失败！
    pause
    exit /b 1
)

echo.
echo [4/4] 清理临时文件...
if exist build rmdir /s /q build
if exist __pycache__ rmdir /s /q __pycache__

echo.
echo ========================================
echo    打包完成！
echo ========================================
echo.
echo 可执行文件位置: dist\浮动控制台.exe
echo.
echo 按任意键打开输出目录...
pause >nul
explorer dist

exit /b 0
