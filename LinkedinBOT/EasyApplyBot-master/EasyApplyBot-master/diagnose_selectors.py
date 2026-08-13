"""
Run this script to discover what LinkedIn job-list selectors are
present in the current version of the jobs search page.
"""
import yaml, os, time
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager

URL = "https://www.linkedin.com/jobs/search-results/?keywords=Technical%20account%20manager&f_AL=true"

with open("config.yaml", "r", encoding="utf-8") as f:
    params = yaml.safe_load(f)

options = Options()
# Connect to the already-running Chrome (launched by main.py on port 9222)
options.add_experimental_option("debuggerAddress", "127.0.0.1:9222")

service = Service(ChromeDriverManager().install())
driver = webdriver.Chrome(service=service, options=options)
driver.implicitly_wait(2)

print(f"\nConnected to existing Chrome session")
print(f"Current URL: {driver.current_url}")
print(f"Waiting 3s for page to settle...")
time.sleep(3)

CSS_CANDIDATES = [
    "li[data-occludable-job-id]",
    "li[data-job-id]",
    ".jobs-search-results__list-item",
    ".scaffold-layout__list-item",
    ".job-card-container",
    ".jobs-search-results__list",
    ".scaffold-layout__list",
    "ul.artdeco-list",
    ".artdeco-list__item",
    "div.jobs-search-two-pane__job-card-container--viewport",
]

XPATH_CANDIDATES = [
    '//li[.//a[contains(@class,"job-card-list__title--link")]]',
    '//li[.//div[contains(@class,"job-card-container")]]',
    '//li[@data-occludable-job-id]',
]

print("\n" + "="*60)
print("CSS SELECTOR PROBE")
print("="*60)
for sel in CSS_CANDIDATES:
    try:
        els = driver.find_elements(By.CSS_SELECTOR, sel)
        if els:
            first_cls = els[0].get_attribute("class") or "(no class)"
            print(f"  FOUND {len(els):3d} elements  |  {sel}")
            print(f"       first-class: {first_cls[:80]}")
        else:
            print(f"  EMPTY 0 elements  |  {sel}")
    except Exception as e:
        print(f"  ERROR             |  {sel}  -> {e}")

print("\n" + "="*60)
print("XPATH PROBE")
print("="*60)
for xp in XPATH_CANDIDATES:
    try:
        els = driver.find_elements(By.XPATH, xp)
        if els:
            print(f"  FOUND {len(els):3d} elements  |  {xp}")
        else:
            print(f"  EMPTY 0 elements  |  {xp}")
    except Exception as e:
        print(f"  ERROR             |  {xp}  -> {e}")

print("\n" + "="*60)
print("ALL <ul> CLASSES ON PAGE")
print("="*60)
uls = driver.find_elements(By.TAG_NAME, "ul")
for ul in uls:
    cls = (ul.get_attribute("class") or "").strip()
    if cls:
        children = ul.find_elements(By.XPATH, "./li")
        print(f"  ul  [{len(children):3d} li]  class='{cls[:100]}'")

print("\n" + "="*60)
print(f"Page title : {driver.title}")
print(f"Current URL: {driver.current_url}")
print("="*60)

input("\nPress ENTER to close browser...")
driver.quit()
