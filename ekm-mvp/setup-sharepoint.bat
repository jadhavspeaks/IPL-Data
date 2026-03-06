@echo off
echo ============================================================
echo  SharePoint Setup
echo ============================================================
call conda activate ekm
echo Installing Office365 REST client...
pip install Office365-REST-Python-Client==2.5.9
echo.
echo Done! Now add to your .env file:
echo   SHAREPOINT_USERNAME=firstname.lastname@citi.com
echo   SHAREPOINT_PASSWORD=your-windows-password
echo.
echo Then add sites to sharepoint_sites.txt and restart backend.
echo ============================================================
pause
