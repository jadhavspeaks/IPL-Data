@echo off
echo ============================================================
echo  SharePoint Setup - Installing Playwright + Edge driver
echo ============================================================
echo.

call conda activate ekm

echo Step 1: Installing Playwright...
pip install playwright==1.44.0

echo.
echo Step 2: Installing Edge browser driver...
playwright install msedge

echo.
echo ============================================================
echo  Setup complete!
echo  
echo  Next steps:
echo  1. Edit sharepoint_sites.txt - add your SharePoint URLs
echo  2. Make sure Edge is open and you are logged into SharePoint
echo  3. Restart backend and click Sync All
echo ============================================================
pause
