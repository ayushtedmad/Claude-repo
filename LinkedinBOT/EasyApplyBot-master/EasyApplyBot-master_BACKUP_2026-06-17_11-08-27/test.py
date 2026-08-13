from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
import os

# Debug print
print(f"Script starting from: {os.getcwd()}")

# Chrome path verification
CHROME_PATH = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"
print(f"Chrome exists: {os.path.exists(CHROME_PATH)}")

# Set up Chrome options
options = Options()
options.binary_location = CHROME_PATH
options.add_argument('--no-sandbox')
options.add_argument('--start-maximized')
options.add_argument('--disable-gpu')
options.add_argument('--disable-dev-shm-usage')
options.add_argument('--remote-debugging-port=9222')

try:
    print("Setting up ChromeDriver...")
    service = Service(ChromeDriverManager().install())
    
    print("Initializing Chrome...")
    driver = webdriver.Chrome(service=service, options=options)
    
    print("Opening Google...")
    driver.get("https://www.google.com")
    print("Browser opened successfully!")
    
except Exception as e:
    print(f"Error occurred: {str(e)}")
finally:
    if 'driver' in locals():
        driver.quit()