@echo off
echo ============================================================
echo  SharePoint Setup
echo ============================================================
echo.
call conda activate ekm
echo Installing SharePoint auth packages...
pip install requests-negotiate-sspi==0.5.2 requests-ntlm==1.3.0
echo.
echo Done! Now:
echo  1. Edit sharepoint_sites.txt - add your SharePoint site URLs
echo  2. Restart backend and click Sync All
echo  3. No username/password needed - uses your Windows login
echo ============================================================
pause
