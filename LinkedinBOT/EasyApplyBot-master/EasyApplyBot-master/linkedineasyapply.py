import time, random, csv, pyautogui, traceback, os, re, base64, json, uuid
import requests as _requests
import chat_server as _chat_server
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from selenium.common.exceptions import StaleElementReferenceException
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select
from datetime import date, datetime
from itertools import product
from pypdf import PdfReader
from openai import OpenAI

class AIResponseGenerator:
    def __init__(self, api_key, personal_info, experience, languages, resume_path, text_resume_path=None, debug=False):
        self.personal_info = personal_info
        self.experience = experience
        self.languages = languages
        self.pdf_resume_path = resume_path
        self.text_resume_path = text_resume_path
        self._resume_content = None
        self._client = OpenAI(api_key=api_key) if api_key else None
        self.debug = debug
    @property
    def resume_content(self):
        if self._resume_content is None:
            # First try to read from text resume if available
            if self.text_resume_path:
                try:
                    with open(self.text_resume_path, 'r', encoding='utf-8') as f:
                        self._resume_content = f.read()
                        print("Successfully loaded text resume")
                        return self._resume_content
                except Exception as e:
                    print(f"Could not read text resume: {str(e)}")

            # Fall back to PDF resume if text resume fails or isn't available
            try:
                content = []
                reader = PdfReader(self.pdf_resume_path)
                for page in reader.pages:
                    content.append(page.extract_text())
                self._resume_content = "\n".join(content)
                print("Successfully loaded PDF resume")
            except Exception as e:
                print(f"Could not extract text from resume PDF: {str(e)}")
                self._resume_content = ""
        return self._resume_content

    def _build_context(self):
        return f"""
        Personal Information:
        - Name: {self.personal_info['First Name']} {self.personal_info['Last Name']}
        - Current Role: {self.experience.get('currentRole', '')}
        - Skills: {', '.join(self.experience.keys())}
        - Languages: {', '.join(f'{lang}: {level}' for lang, level in self.languages.items())}
        - Professional Summary: {self.personal_info.get('MessageToManager', '')}

        Resume Content (Give the greatest weight to this information, if specified):
        {self.resume_content}
        """

    def generate_response(self, question_text, response_type="text", options=None, max_tokens=100):
        """
        Generate a response using OpenAI's API
        
        Args:
            question_text: The application question to answer
            response_type: "text", "numeric", or "choice"
            options: For "choice" type, a list of tuples containing (index, text) of possible answers
            max_tokens: Maximum length of response
            
        Returns:
            - For text: Generated text response or None
            - For numeric: Integer value or None
            - For choice: Integer index of selected option or None
        """
        if not self._client:
            return None
            
        try:
            context = self._build_context()
            
            system_prompt = {
                "text": "You are a helpful assistant answering job application questions professionally and concisely. Use the candidate's background information and resume to personalize responses.",
                "numeric": "You are a helpful assistant providing numeric answers to job application questions. Based on the candidate's experience, provide a single number as your response. No explanation needed.",
                "choice": "You are a helpful assistant selecting the most appropriate answer choice for job application questions. Based on the candidate's background, select the best option by returning only its index number. No explanation needed."
            }[response_type]

            user_content = f"Using this candidate's background and resume:\n{context}\n\nPlease answer this job application question: {question_text}"
            if response_type == "choice" and options:
                options_text = "\n".join([f"{idx}: {text}" for idx, text in options])
                user_content += f"\n\nSelect the most appropriate answer by providing its index number from these options:\n{options_text}"

            response = self._client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content}
                ],
                max_tokens=max_tokens,
                temperature=0.7
            )
            
            answer = response.choices[0].message.content.strip()
            print(f"AI response: {answer}")  # TODO: Put logging behind a debug flag
            
            if response_type == "numeric":
                # Extract first number from response
                numbers = re.findall(r'\d+', answer)
                if numbers:
                    return int(numbers[0])
                return 0
            elif response_type == "choice":
                # Extract the index number from the response
                numbers = re.findall(r'\d+', answer)
                if numbers and options:
                    index = int(numbers[0])
                    # Ensure index is within valid range
                    if 0 <= index < len(options):
                        return index
                return None  # Return None if the index is not within the valid range
                
            return answer
            
        except Exception as e:
            print(f"Error using AI to generate response: {str(e)}")
            return None

    def evaluate_job_fit(self, job_title, job_description):
        """
        Evaluate whether a job is worth applying to based on the candidate's experience and the job requirements
        
        Args:
            job_title: The title of the job posting
            job_description: The full job description text
            
        Returns:
            bool: True if should apply, False if should skip
        """
        if not self._client:
            return True  # Proceed with application if AI not available
            
        try:
            context = self._build_context()
            
            system_prompt = """You are evaluating job fit for technical roles. 
            Recommend APPLY if:
            - Candidate meets 65 percent of the core requirements
            - Experience gap is 2 years or less
            - Has relevant transferable skills
            
            Return SKIP if:
            - Experience gap is greater than 2 years
            - Missing multiple core requirements
            - Role is clearly more senior
            - The role is focused on an uncommon technology or skill that is required and that the candidate does not have experience with
            - The role is a leadership role or a role that requires managing people and the candidate has no experience leading or managing people

            """
            #Consider the candidate's education level when evaluating whether they meet the core requirements. Having higher education than required should allow for greater flexibility in the required experience.
            
            if self.debug:
                system_prompt += """
                You are in debug mode. Return a detailed explanation of your reasoning for each requirement.

                Return APPLY or SKIP followed by a brief explanation.

                Format response as: APPLY/SKIP: [brief reason]"""
            else:
                system_prompt += """Return only APPLY or SKIP."""

            response = self._client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Job: {job_title}\n{job_description}\n\nCandidate:\n{context}"}
                ],
                max_tokens=250 if self.debug else 1,  # Allow more tokens when debug is enabled
                temperature=0.2  # Lower temperature for more consistent decisions
            )
            
            answer = response.choices[0].message.content.strip()
            print(f"AI evaluation: {answer}")
            return answer.upper().startswith('A')  # True for APPLY, False for SKIP
            
        except Exception as e:
            print(f"Error evaluating job fit: {str(e)}")
            return True  # Proceed with application if evaluation fails

    def analyze_page_html(self, interactive_html, page_title, page_url, candidate_info):
        """
        Send the compact interactive HTML of a company job page to GPT-4o-mini
        and get back a structured JSON action plan.

        No screenshot needed — text-only, cheaper and faster than vision.

        Returns dict action plan or None on failure.
        Schema identical to the old vision method for full compatibility:
        {
          "strategy": "linkedin_button"|"cv_upload"|"manual_form"|"unknown",
          "explanation": "...",
          "steps": [
            {"action": "click"|"fill"|"upload"|"scroll"|"wait",
             "selector": "CSS", "value": "{token}", ...}
          ]
        }
        Tokens: {first_name} {last_name} {full_name} {email} {phone} {linkedin} {website}
        """
        if not self._client:
            return None
        if not interactive_html or not interactive_html.strip():
            print("No interactive HTML to analyse.")
            return None

        system_prompt = """You are an expert web-automation assistant helping a job-seeker apply on company websites.
You receive:
  1. The page URL and title.
  2. A compact HTML snippet of ONLY the interactive elements (inputs, buttons, selects, links, file inputs).
  3. Basic candidate info.

Produce a JSON action plan a Selenium bot can execute step by step.

RULES:
- Prefer "Apply with LinkedIn" / "Sign in with LinkedIn" buttons — fastest path.
- If a file upload input exists, always upload CV first (triggers autofill on many ATS).
- Only use CSS selectors that are present in the HTML snippet.
- Prefer id-based selectors (#id) over class-based ones.
- Do NOT include a submit step unless you are very confident the form is complete.
- If the page needs a login wall or is a multi-step flow you cannot determine, set strategy to "unknown".
- Return ONLY valid JSON. No markdown fences, no extra text.

JSON schema:
{
  "strategy": "linkedin_button" | "cv_upload" | "manual_form" | "unknown",
  "explanation": "one sentence describing what you see",
  "steps": [
    {"action": "click",  "selector": "CSS_SELECTOR"},
    {"action": "fill",   "selector": "CSS_SELECTOR", "value": "{first_name}"},
    {"action": "upload", "selector": "input[type='file']"},
    {"action": "scroll", "direction": "down"},
    {"action": "wait",   "seconds": 3}
  ]
}

Token substitutions available for fill "value":
  {first_name}  {last_name}  {full_name}  {email}  {phone}  {linkedin}  {website}
"""
        user_text = (
            f"Page URL  : {page_url}\n"
            f"Page title: {page_title}\n\n"
            f"Candidate : {candidate_info.get('first_name','')} {candidate_info.get('last_name','')}"
            f" | Email: {candidate_info.get('email','')}"
            f" | Phone: {candidate_info.get('phone','')}\n\n"
            f"Interactive HTML elements:\n{interactive_html[:8000]}\n\n"
            "Produce the JSON action plan:"
        )
        try:
            response = self._client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_text}
                ],
                max_tokens=800,
                temperature=0.1
            )
            raw = response.choices[0].message.content.strip()
            raw = re.sub(r'^```(?:json)?\s*', '', raw, flags=re.MULTILINE)
            raw = re.sub(r'\s*```$',           '', raw, flags=re.MULTILINE)
            plan = json.loads(raw)
            print(f"AI plan: strategy={plan.get('strategy')} | {plan.get('explanation','')}")
            return plan
        except json.JSONDecodeError as e:
            print(f"AI returned invalid JSON: {e}\nRaw: {raw[:300]}")
            return None
        except Exception as e:
            print(f"Error in AI page analysis: {e}")
            return None


class DailyLimitReachedException(Exception):
    """Raised when LinkedIn's daily Easy Apply submission limit is detected."""
    pass


class LinkedinEasyApply:
    def __init__(self, parameters, driver):
        self.browser = driver
        self.browser_factory = None  # Set by main.py after construction to allow browser restarts
        self.email = parameters['email']
        self.password = parameters['password']
        self.openai_api_key = parameters.get('openaiApiKey', '')  # Get API key with empty default
        self.disable_lock = parameters['disableAntiLock']
        self.company_blacklist = parameters.get('companyBlacklist', []) or []
        self.title_blacklist = parameters.get('titleBlacklist', []) or []
        self.poster_blacklist = parameters.get('posterBlacklist', []) or []
        self.positions = parameters.get('positions', [])
        self.locations = parameters.get('locations', [])
        self.residency = parameters.get('residentStatus', [])
        self.base_search_url = self.get_base_search_url(parameters)
        self.direct_url = parameters.get('url', '').strip() if parameters.get('url') else ''
        self.seen_jobs = []
        self._easy_apply_exhausted = False   # set True once daily Easy Apply limit is hit
        self.applied_jobs_file = "applied_jobs.csv"     # persistent cross-session tracker
        self.applied_job_links = self._load_applied_jobs()  # set of previously applied URLs
        self.file_name = "output"
        self.unprepared_questions_file_name = "unprepared_questions"
        self.unanswered_questions_file_name = "unanswered_question"  # user-editable manual answer file
        self.user_answers = self._load_user_answers()  # pre-load answers user filled in
        self._job_counter = 0          # running count of jobs attempted this session
        self.output_file_directory = parameters['outputFileDirectory']
        self.resume_dir = parameters['uploads']['resume']
        self.text_resume = parameters.get('textResume', '')
        if 'coverLetter' in parameters['uploads']:
            self.cover_letter_dir = parameters['uploads']['coverLetter']
        else:
            self.cover_letter_dir = ''
        self.checkboxes = parameters.get('checkboxes', [])
        self.university_gpa = parameters['universityGpa']
        self.salary_minimum = parameters['salaryMinimum']
        self.notice_period = int(parameters['noticePeriod'])
        self.languages = parameters.get('languages', [])
        self.experience = parameters.get('experience', [])
        self.personal_info = parameters.get('personalInfo', [])
        self.eeo = parameters.get('eeo', [])
        self.experience_default = int(self.experience['default'])
        self.debug = parameters.get('debug', False)
        self.evaluate_job_fit = parameters.get('evaluateJobFit', True)
        self.apply_external_jobs = parameters.get('applyExternalJobs', False)
        self.external_file_name = "external_applied"
        self.site_patterns_file = "site_patterns.json"          # per-domain learned patterns
        self.site_patterns = self._load_site_patterns()          # loaded at startup
        self.ai_response_generator = AIResponseGenerator(
            api_key=self.openai_api_key,
            personal_info=self.personal_info,
            experience=self.experience,
            languages=self.languages,
            resume_path=self.resume_dir,
            text_resume_path=self.text_resume,
            debug=self.debug
        )

        # ── Browser chat assistant ────────────────────────────────────────────
        _chat_server.start_server()   # start Flask chat-bridge (daemon thread)

        # Patch browser.get so the panel is re-injected after every navigation
        _orig_get = self.browser.get
        def _get_with_inject(url):
            _orig_get(url)
            time.sleep(0.6)           # wait for DOM to settle
            self._inject_chat_panel()
        self.browser.get = _get_with_inject

    # ── Logging helper ────────────────────────────────────────────────────────
    def _log(self, msg, level="INFO"):
        """Print a timestamped log line to the terminal and browser overlay."""
        ts = datetime.now().strftime("%H:%M:%S")
        icons = {"INFO": "ℹ️ ", "OK": "✅", "WARN": "⚠️ ", "SKIP": "⏩", "STEP": "🔹", "FAIL": "❌"}
        icon = icons.get(level, "  ")
        line = f"[{ts}] {icon} {msg}"
        print(line)                                    # terminal
        try:
            _chat_server.push_log(line, level)         # browser overlay
        except Exception:
            pass

    def _dismiss_modal(self):
        """Close any open LinkedIn modal — tries multiple selectors for robustness."""
        selectors = [
            (By.CLASS_NAME, 'artdeco-modal__dismiss'),
            (By.CSS_SELECTOR, 'button[aria-label="Dismiss"]'),
            (By.CSS_SELECTOR, 'button[aria-label="Cancel"]'),
            (By.CSS_SELECTOR, 'button[aria-label="Close"]'),
            (By.CSS_SELECTOR, '[role="dialog"] button[type="button"]:last-child'),
        ]
        for by, sel in selectors:
            try:
                btn = self.browser.find_element(by, sel)
                btn.click()
                return True
            except:
                pass
        return False

    def _log_banner(self, title, width=60):
        """Print a section banner."""
        ts = datetime.now().strftime("%H:%M:%S")
        bar = "─" * width
        print(f"\n[{ts}] ┌{bar}")
        print(f"[{ts}] │  {title}")
        print(f"[{ts}] └{bar}")

    # ── Domain pattern learning ───────────────────────────────────────────────

    @staticmethod
    def _get_domain(url):
        """Extract the root domain (e.g. 'workday.com') from any URL."""
        import re as _re
        m = _re.search(r'https?://(?:www\.)?([^/]+)', url or '')
        if not m:
            return 'unknown'
        parts = m.group(1).split('.')
        return '.'.join(parts[-2:]) if len(parts) >= 2 else m.group(1)

    def _load_site_patterns(self):
        """Load per-domain action patterns from site_patterns.json."""
        if not os.path.exists(self.site_patterns_file):
            return {}
        try:
            with open(self.site_patterns_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self._log(f"Loaded patterns for {len(data)} domain(s) from {self.site_patterns_file}.", "INFO")
            return data
        except Exception as e:
            print(f"Could not load site patterns: {e}")
            return {}

    def _save_site_patterns(self):
        """Persist all learned domain patterns to site_patterns.json."""
        try:
            with open(self.site_patterns_file, 'w', encoding='utf-8') as f:
                json.dump(self.site_patterns, f, indent=2)
        except Exception as e:
            print(f"Could not save site patterns: {e}")

    def _try_site_pattern(self, domain):
        """
        Replay the saved pattern for this domain (if any).
        Returns True if any steps executed successfully.
        """
        pattern = self.site_patterns.get(domain)
        if not pattern or not pattern.get('steps'):
            return False
        success = pattern.get('success_count', 0)
        self._log(f"Found saved pattern for '{domain}' (used {success}x) — replaying...", "STEP")
        plan = {'steps': pattern['steps'], 'strategy': pattern.get('strategy', 'manual_form')}
        result = self._ext_execute_ai_plan(plan)
        if result:
            pattern['success_count'] = success + 1
            pattern['last_used'] = datetime.now().strftime("%Y-%m-%d")
            self._save_site_patterns()
            self._log(f"Pattern for '{domain}' replayed successfully.", "OK")
            return True
        self._log(f"Saved pattern for '{domain}' produced no results — falling back.", "WARN")
        return False

    # ── Human-in-the-loop click capture ───────────────────────────────────

    # JavaScript injected into the company page to record all user interactions
    _CAPTURE_JS = """
    (function() {
        if (window._botCaptureActive) return;  // don't double-inject
        window._botCaptureActive = true;
        window._botCapture = [];

        function getCssSelector(el) {
            if (!el || el.nodeType !== 1) return '';
            if (el.id)   return '#' + el.id;
            if (el.name) return el.tagName.toLowerCase() + '[name="' + el.name + '"]';
            var cls = Array.from(el.classList).filter(Boolean).slice(0,2).join('.');
            if (cls)     return el.tagName.toLowerCase() + '.' + cls;
            // nth-child fallback
            var path = '', node = el;
            while (node && node.nodeType === 1 && node.tagName !== 'BODY') {
                var tag = node.tagName.toLowerCase();
                if (node.id) { path = '#' + node.id + (path ? ' > ' + path : ''); break; }
                var idx = Array.from(node.parentNode.children).indexOf(node) + 1;
                path = tag + ':nth-child(' + idx + ')' + (path ? ' > ' + path : '');
                node = node.parentNode;
            }
            return path;
        }

        document.addEventListener('click', function(e) {
            var el  = e.target;
            var sel = getCssSelector(el);
            if (!sel) return;
            window._botCapture.push({
                action: 'click',
                selector: sel,
                tag: el.tagName,
                text: (el.innerText || '').trim().slice(0,60)
            });
        }, true);

        document.addEventListener('input', function(e) {
            var el  = e.target;
            var sel = getCssSelector(el);
            if (!sel) return;
            if (el.type === 'password') return;  // never capture passwords
            window._botCapture.push({
                action: 'fill',
                selector: sel,
                value:    el.value,
                input_type: el.type || 'text',
                name:     el.name  || '',
                label_hint: (document.querySelector('label[for="' + el.id + '"]') || {}).innerText || ''
            });
        }, true);

        document.addEventListener('change', function(e) {
            var el  = e.target;
            var sel = getCssSelector(el);
            if (!sel) return;
            if (el.type === 'file') {
                window._botCapture.push({action: 'upload', selector: sel});
            }
        }, true);
    })();
    """

    def _start_capture_js(self):
        """Inject the JS click/input recorder into the current page."""
        try:
            self.browser.execute_script(self._CAPTURE_JS)
        except Exception as e:
            self._log(f"Could not inject click capture JS: {e}", "WARN")

    def _stop_capture_js(self):
        """
        Read and return all captured interactions, then clear the buffer.
        Returns a list of event dicts.
        """
        try:
            events = self.browser.execute_script(
                "var e = window._botCapture || []; window._botCapture = []; return e;"
            )
            return events or []
        except Exception:
            return []

    def _tokenize_captured_actions(self, events):
        """
        Convert raw captured events into replayable action steps by replacing
        actual typed values with {token} placeholders based on candidate info.

        Returns a list of action-plan step dicts.
        """
        # Build value → token map
        token_map = {}
        pi = self.personal_info
        fn  = (pi.get('First Name') or '').strip()
        ln  = (pi.get('Last Name')  or '').strip()
        full = f"{fn} {ln}".strip()
        for val, tok in [
            (self.email,                                              '{email}'),
            (str(pi.get('Mobile Phone Number', '')).strip(),          '{phone}'),
            (fn,                                                      '{first_name}'),
            (ln,                                                      '{last_name}'),
            (full,                                                    '{full_name}'),
            ((pi.get('Linkedin') or '').strip(),                      '{linkedin}'),
            ((pi.get('Website')  or '').strip(),                      '{website}'),
        ]:
            if val:
                token_map[val.lower()] = tok

        steps = []
        seen_selectors = set()   # deduplicate repeated input events on same field
        for ev in events:
            action = ev.get('action', '')
            sel    = ev.get('selector', '')
            if not sel:
                continue

            if action == 'click':
                # Skip click on inputs — the fill event already covers those
                tag = (ev.get('tag') or '').upper()
                if tag not in ('INPUT', 'TEXTAREA', 'SELECT'):
                    steps.append({'action': 'click', 'selector': sel})

            elif action == 'fill':
                raw_val = (ev.get('value') or '').strip()
                if not raw_val:
                    continue
                token = token_map.get(raw_val.lower(), raw_val)
                key = (sel, token)
                if key not in seen_selectors:
                    seen_selectors.add(key)
                    steps.append({'action': 'fill', 'selector': sel, 'value': token})

            elif action == 'upload':
                if sel not in seen_selectors:
                    seen_selectors.add(sel)
                    steps.append({'action': 'upload', 'selector': sel})

        return steps

    def _wait_for_human_assistance(self, domain, timeout=30):
        """
        Pause and wait for the human to interact with the page.
        During the wait, JS event listeners record every click and input.
        After the timeout, captured interactions are tokenised and saved as a
        replayable pattern for this domain.

        Returns True if the human made at least one interaction.
        """
        self._log_banner(f"👤 HUMAN ASSISTANCE NEEDED  —  {domain}")
        self._log(f"Bot is stuck. You have {timeout} seconds to interact with the page.", "WARN")
        self._log("Fill in fields, click buttons, etc.  The bot is watching and learning.", "WARN")
        self._log(f"It will continue automatically when the timer runs out.", "INFO")

        self._start_capture_js()

        for remaining in range(timeout, 0, -5):
            self._log(f"  ⏳ {remaining}s remaining for human interaction...", "INFO")
            time.sleep(5)

        events = self._stop_capture_js()
        if not events:
            self._log("No human interactions detected.", "WARN")
            return False

        self._log(f"Captured {len(events)} human interaction(s) — tokenising...", "OK")
        steps = self._tokenize_captured_actions(events)

        if steps:
            self._log(f"Saving {len(steps)} step(s) as pattern for '{domain}'.", "OK")
            self.site_patterns[domain] = {
                'steps':         steps,
                'strategy':      'manual_form',
                'success_count': 1,
                'last_used':     datetime.now().strftime("%Y-%m-%d"),
                'learned_from':  datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            self._save_site_patterns()
            self._log(f"✨ Pattern for '{domain}' saved — will be replayed automatically next time!", "OK")
        else:
            self._log("Could not extract replayable steps from human interactions.", "WARN")

        return True

    def login(self):
        try:
            # Check if the "chrome_bot" directory exists
            print("Attempting to restore previous session...")
            if os.path.exists("chrome_bot"):
                self.browser.get("https://www.linkedin.com/feed/")
                time.sleep(random.uniform(5, 10))

                # Check if the current URL is the feed page
                if self.browser.current_url != "https://www.linkedin.com/feed/":
                    print("Feed page not loaded, proceeding to login.")
                    self.load_login_page_and_login()
            else:
                print("No session found, proceeding to login.")
                self.load_login_page_and_login()

        except TimeoutException:
            print("Timeout occurred, checking for security challenges...")
            self.security_check()
            # raise Exception("Could not login!")

    def security_check(self):
        current_url = self.browser.current_url
        page_source = self.browser.page_source

        if '/checkpoint/challenge/' in current_url or 'security check' in page_source or 'quick verification' in page_source:
            input("Please complete the security check and press enter on this console when it is done.")
            time.sleep(random.uniform(5.5, 10.5))

    def load_login_page_and_login(self):
        self.browser.get("https://www.linkedin.com/login")

        # Wait for the username field to be present
        WebDriverWait(self.browser, 10).until(
            EC.presence_of_element_located((By.ID, "username"))
        )

        self.browser.find_element(By.ID, "username").send_keys(self.email)
        self.browser.find_element(By.ID, "password").send_keys(self.password)
        self.browser.find_element(By.CSS_SELECTOR, ".btn__primary--large").click()

        # Wait for the feed page to load after login
        WebDriverWait(self.browser, 10).until(
            EC.url_contains("https://www.linkedin.com/feed/")
        )

        time.sleep(random.uniform(5, 10))

    def start_applying(self):
        page_sleep = 0
        minimum_time = 3  # seconds to wait between pages (reduced for speed)
        minimum_page_time = time.time() + minimum_time

        # ── Direct URL mode ──────────────────────────────────────────────────
        if self.direct_url:
            self._log_banner(f"DIRECT URL MODE")
            self._log(f"Target URL: {self.direct_url}")
            job_page_number = -1
            try:
                while True:
                    if _chat_server.is_stopped():
                        self._log("⏹ Bot stopped by user via browser.", "FAIL")
                        return
                    page_sleep += 1
                    job_page_number += 1
                    self._log_banner(f"FETCHING PAGE {job_page_number}  (direct URL mode)")
                    self.next_job_page_direct(self.direct_url, job_page_number)
                    time.sleep(random.uniform(1, 2))
                    self._log("Page loaded — scanning job tiles...", "STEP")
                    try:
                        self.apply_jobs("")
                    except DailyLimitReachedException:
                        self._handle_daily_limit_reached()
                        continue
                    except Exception as _e:
                        msg = str(_e)
                        if any(m in msg for m in ["No more jobs", "Nothing to do here", "No job results"]):
                            self._log(f"End of results — stopping: {msg}", "INFO")
                            break
                        traceback.print_exc()
                        break  # unexpected error — stop pagination
                    self._log("All jobs on this page processed.", "OK")

                    time_left = minimum_page_time - time.time()
                    if time_left > 0:
                        self._log(f"Pacing delay: sleeping {time_left:.0f}s before next page...", "INFO")
                        time.sleep(time_left)
                        minimum_page_time = time.time() + minimum_time
                    if page_sleep % 5 == 0:
                        sleep_time = random.randint(3, 5)
                        self._log(f"Anti-detection break: sleeping {sleep_time}s...", "WARN")
                        time.sleep(sleep_time)
                        page_sleep += 1
            except Exception:
                traceback.print_exc()
            return
        # ── Normal positions × locations mode ────────────────────────────────

        searches = list(product(self.positions, self.locations))
        random.shuffle(searches)
        total = len(searches)

        for idx, (position, location) in enumerate(searches, start=1):
            location_url = "&location=" + location
            job_page_number = -1

            self._log_banner(f"SEARCH {idx}/{total}  →  '{position}'  in  '{location}'")

            try:
                while True:
                    if _chat_server.is_stopped():
                        self._log("⏹ Bot stopped by user via browser.", "FAIL")
                        return
                    page_sleep += 1
                    job_page_number += 1
                    self._log(f"Loading page {job_page_number} of results...", "STEP")
                    self.next_job_page(position, location_url, job_page_number)
                    time.sleep(random.uniform(1, 2))
                    self._log("Page loaded — scanning job tiles...", "STEP")
                    try:
                        self.apply_jobs(location)
                    except DailyLimitReachedException:
                        self._handle_daily_limit_reached()
                        continue
                    except Exception as _e:
                        msg = str(_e)
                        if any(m in msg for m in ["No more jobs", "Nothing to do here", "No job results"]):
                            self._log(f"End of results — next search: {msg}", "INFO")
                            break
                        traceback.print_exc()
                        break
                    self._log("All jobs on this page processed.", "OK")

                    time_left = minimum_page_time - time.time()
                    if time_left > 0:
                        self._log(f"Pacing delay: sleeping {time_left:.0f}s before next page...", "INFO")
                        time.sleep(time_left)
                        minimum_page_time = time.time() + minimum_time
                    if page_sleep % 5 == 0:
                        sleep_time = random.randint(3, 5)
                        self._log(f"Anti-detection break: sleeping {sleep_time}s...", "WARN")
                        time.sleep(sleep_time)
                        page_sleep += 1
            except Exception:
                traceback.print_exc()
                pass

            time_left = minimum_page_time - time.time()
            if time_left > 0:
                self._log(f"Pacing delay: sleeping {time_left:.0f}s before next search...", "INFO")
                time.sleep(time_left)
                minimum_page_time = time.time() + minimum_time
            if page_sleep % 5 == 0:
                sleep_time = random.randint(3, 5)
                self._log(f"Anti-detection break: sleeping {sleep_time}s...", "WARN")
                time.sleep(sleep_time)
                page_sleep += 1

    def apply_jobs(self, location):
        no_jobs_text = ""
        try:
            no_jobs_element = self.browser.find_element(By.CLASS_NAME,
                                                        'jobs-search-two-pane__no-results-banner--expand')
            no_jobs_text = no_jobs_element.text
        except:
            pass
        if 'No matching jobs found' in no_jobs_text:
            self._log("No matching jobs — stopping pagination.", "INFO")
            return  # graceful stop, not an exception

        if 'unfortunately, things are' in self.browser.page_source.lower():
            self._log("LinkedIn error page — stopping pagination.", "INFO")
            return

        # ── Daily limit check at the search-page level ─────────────────────────
        # Only raise if we haven't already noted the limit — otherwise keep scanning
        # so the bot can still find and apply to external (non-Easy-Apply) jobs.
        if self._is_daily_limit_page() and not self._easy_apply_exhausted:
            raise DailyLimitReachedException(
                "LinkedIn daily submission limit detected on the search/job page."
            )

        job_results_header = ""
        maybe_jobs_crap = ""
        try:
            # LinkedIn periodically renames this class — safe-guard with try/except
            job_results_header = self.browser.find_element(By.CLASS_NAME, "jobs-search-results-list__text")
            maybe_jobs_crap = job_results_header.text
        except:
            # Class no longer present on this version of LinkedIn — skip the check
            pass

        if 'Jobs you may be interested in' in maybe_jobs_crap:
            raise Exception("Nothing to do here, moving forward...")

        try:
            job_list = []

            # ── Wait for at least one job link to appear before scanning ──
            try:
                WebDriverWait(self.browser, 8).until(
                    lambda d: d.execute_script(
                        "return document.querySelector('a[href*=\"/jobs/view/\"]') !== null"
                        " || document.querySelector('li[data-occludable-job-id]') !== null"
                        " || document.querySelectorAll('li').length > 5;"
                    )
                )
            except TimeoutException:
                pass  # Proceed anyway — DOM dump will catch the real issue

            # ── Strategy 1: JS-based — find <li> elements containing any job link ──
            # Tries /jobs/view/ first (standard), then broader patterns for newer LinkedIn URLs.
            job_list = self.browser.execute_script("""
                var lis = Array.from(document.querySelectorAll('li'));

                // Pattern A: standard /jobs/view/ href
                var result = lis.filter(function(li) {
                    return li.querySelector('a[href*="/jobs/view/"]') !== null;
                });
                if (result.length > 0) return result;

                // Pattern B: any <a> inside <li> whose href contains a 7+ digit job ID
                result = lis.filter(function(li) {
                    var a = li.querySelector('a[href]');
                    if (!a) return false;
                    var href = a.getAttribute('href') || '';
                    return /\\/jobs\\/[a-z-]*\\d{7,}/.test(href);
                });
                if (result.length > 0) return result;

                // Pattern C: data attribute on the <li> itself
                result = lis.filter(function(li) {
                    return li.hasAttribute('data-occludable-job-id')
                        || li.hasAttribute('data-job-id')
                        || li.hasAttribute('data-entity-urn');
                });
                return result;
            """)
            if job_list:
                print(f"Strategy 1 (JS job-link): found {len(job_list)} job tiles")

            # ── Strategy 2: data-occludable-job-id attribute ──
            if not job_list:
                job_list = self.browser.find_elements(By.CSS_SELECTOR, "li[data-occludable-job-id]")
                if job_list:
                    print(f"Strategy 2 (data-occludable-job-id): found {len(job_list)} job tiles")

            # ── Strategy 3: job-card-list__title--link ancestor ──
            if not job_list:
                job_list = self.browser.find_elements(By.XPATH,
                    '//li[.//a[contains(@class,"job-card-list__title--link")]]')
                if job_list:
                    print(f"Strategy 3 (title-link ancestor): found {len(job_list)} job tiles")

            # ── Strategy 4: scaffold-layout__list-item ──
            if not job_list:
                job_list = self.browser.find_elements(By.CLASS_NAME, "scaffold-layout__list-item")
                if job_list:
                    print(f"Strategy 4 (scaffold-layout__list-item): found {len(job_list)} job tiles")

            # ── All strategies failed: dump DOM hints and give up ──
            if not job_list:
                print("All job-tile strategies failed. Dumping DOM hints...")
                try:
                    ul_classes = self.browser.execute_script(
                        "return Array.from(document.querySelectorAll('ul'))"
                        ".map(u => u.className.trim())"
                        ".filter(c => c.length > 0)"
                        ".slice(0, 20);"
                    )
                    print("  <ul> classes on page:")
                    for cls in ul_classes:
                        print(f"    {cls[:120]}")
                    li_count = self.browser.execute_script(
                        "return document.querySelectorAll('li').length;"
                    )
                    print(f"  Total <li> elements: {li_count}")
                    print(f"  Page title: {self.browser.title}")
                except Exception as dump_err:
                    print(f"  DOM dump failed: {dump_err}")
                raise Exception("No more jobs on this page.")

            # ── Scroll the job panel to load all tiles ──────────────────────────────
            try:
                scroll_target = job_list[0].find_element(By.XPATH, "./ancestor::ul[1]")
            except Exception:
                scroll_target = job_list[0]
            self.scroll_slow(scroll_target)
            self.scroll_slow(scroll_target, step=300, reverse=True)

            # Re-fetch after scroll in case new tiles loaded
            job_list = self.browser.execute_script("""
                var lis = Array.from(document.querySelectorAll('li'));
                var result = lis.filter(function(li) {
                    return li.querySelector('a[href*="/jobs/view/"]') !== null;
                });
                if (result.length > 0) return result;
                result = lis.filter(function(li) {
                    var a = li.querySelector('a[href]');
                    if (!a) return false;
                    var href = a.getAttribute('href') || '';
                    return /\\/jobs\\/[a-z-]*\\d{7,}/.test(href);
                });
                if (result.length > 0) return result;
                return lis.filter(function(li) {
                    return li.hasAttribute('data-occludable-job-id')
                        || li.hasAttribute('data-job-id')
                        || li.hasAttribute('data-entity-urn');
                });
            """)
            print(f"Found {len(job_list)} jobs on this page")

        except NoSuchElementException:
            print("No job results found using the specified XPaths or class.")

        except Exception as e:
            print(f"An unexpected error occurred: {e}")

        for job_tile in job_list:
            job_title, company, poster, job_location, apply_method, link = "", "", "", "", "", ""

            try:
                # Title & link — try /jobs/view/ first, then any /jobs/NNNNNN pattern
                job_link_el = None
                for sel in ['a[href*="/jobs/view/"]', 'a[href*="/jobs/"]']:
                    try:
                        el = job_tile.find_element(By.CSS_SELECTOR, sel)
                        if el:
                            job_link_el = el
                            break
                    except:
                        pass
                if job_link_el:
                    link = job_link_el.get_attribute('href').split('?')[0]
                    try:
                        job_title = job_link_el.find_element(By.TAG_NAME, 'strong').text.strip()
                    except:
                        job_title = job_link_el.text.strip()
                    if not job_title:
                        job_title = (job_link_el.get_attribute('aria-label') or '').strip()
            except:
                pass
            try:
                # Company: try the subtitle class first, then any element with aria-label="company name"
                company = job_tile.find_element(By.CLASS_NAME, 'artdeco-entity-lockup__subtitle').text
            except:
                try:
                    company = job_tile.find_element(By.CSS_SELECTOR, '[data-test-entity-lockup-company-name]').text
                except:
                    pass
            try:
                # Poster: look for " is hiring for this" text
                hiring_line = job_tile.find_element(By.XPATH, './/span[contains(., " is hiring for this")]')
                hiring_line_text = hiring_line.text
                name_terminating_index = hiring_line_text.find(' is hiring for this')
                if name_terminating_index != -1:
                    poster = hiring_line_text[:name_terminating_index]
            except:
                pass
            try:
                job_location = job_tile.find_element(By.CLASS_NAME, 'job-card-container__metadata-item').text
            except:
                try:
                    # Grab first metadata li element as fallback
                    job_location = job_tile.find_elements(By.XPATH, './/li')[0].text
                except:
                    pass
            try:
                apply_method = job_tile.find_element(By.CLASS_NAME, 'job-card-container__apply-method').text
            except:
                pass

            contains_blacklisted_keywords = False
            job_title_parsed = job_title.lower().split(' ')

            for word in self.title_blacklist:
                if word.lower() in job_title_parsed:
                    contains_blacklisted_keywords = True
                    break

            already_applied = link and link in self.applied_job_links

            if company.lower() not in [word.lower() for word in self.company_blacklist] and \
                    poster.lower() not in [word.lower() for word in self.poster_blacklist] and \
                    contains_blacklisted_keywords is False and link not in self.seen_jobs and \
                    not already_applied:

                self._job_counter += 1
                self._log_banner(
                    f"JOB #{self._job_counter}  |  {job_title}  —  {company}  |  {job_location}"
                )
                self._log(f"Link    : {link}", "INFO")
                self._log(f"Poster  : {poster if poster else '(not listed)'}", "INFO")
                self._log(f"Method  : {apply_method if apply_method else 'Easy Apply'}", "INFO")

                try:
                    # Click the job to load description
                    max_retries = 3
                    retries = 0
                    while retries < max_retries:
                        try:
                            # Try /jobs/view/ first, then any /jobs/ link
                            job_el = None
                            for sel in ['a[href*="/jobs/view/"]', 'a[href*="/jobs/"]']:
                                try:
                                    job_el = job_tile.find_element(By.CSS_SELECTOR, sel)
                                    if job_el:
                                        break
                                except:
                                    pass
                            if job_el:
                                job_el.click()
                            break
                        except StaleElementReferenceException:
                            retries += 1
                            continue

                    time.sleep(random.uniform(2, 3))

                    # TODO: Check if the job is already applied or the application has been reached
                    # "You've reached the Easy Apply application limit for today. Save this job and come back tomorrow to continue applying."
                    # Do this before evaluating job fit to save on API calls

                    if self.evaluate_job_fit:
                        try:
                            self._log("Fetching job description for AI fit evaluation...", "STEP")
                            job_description = self.browser.find_element(
                                By.ID, 'job-details'
                            ).text

                            self._log("Evaluating job fit with AI...", "STEP")
                            if not self.ai_response_generator.evaluate_job_fit(job_title, job_description):
                                self._log("AI: job requirements don't match profile — SKIPPING.", "SKIP")
                                continue
                            self._log("AI: job fit confirmed — proceeding to apply.", "OK")
                        except:
                            self._log("Could not load job description for AI evaluation.", "WARN")

                    try:
                        self._log("Checking apply button type...", "STEP")
                        result = self.apply_to_job()
                        if result == "easy_apply_success":
                            self._log(f"APPLICATION SUBMITTED ✔  →  {job_title} at {company}", "OK")
                            self._mark_job_applied(link, job_title, company, "easy_apply")
                            try:
                                self.write_to_file(company, job_title, link, job_location, location)
                            except Exception:
                                traceback.print_exc()
                        elif result == "external_apply_success":
                            self._log(f"EXTERNAL APPLICATION ATTEMPTED ✔  →  {job_title} at {company}", "OK")
                            self._mark_job_applied(link, job_title, company, "external")
                            try:
                                self.write_external_to_file(company, job_title, link, job_location, location)
                            except Exception:
                                traceback.print_exc()
                        elif result == "external_skipped":
                            self._log(f"External job skipped (applyExternalJobs is False) — {job_title} at {company}", "SKIP")
                        elif result == "easy_apply_skipped":
                            self._log(f"Easy Apply limit reached — skipped Easy Apply job: {job_title} at {company}", "SKIP")
                            # Mark as seen so it isn't re-evaluated on the next page scan
                            self.seen_jobs += link
                        else:
                            self._log(f"Already applied or apply button unavailable for this job.", "SKIP")
                    except DailyLimitReachedException:
                        raise  # propagate immediately — do not log as a failed job
                    except:
                        temp = self.file_name
                        self.file_name = "failed"
                        self._log(f"FAILED to apply — logged to failed.csv | {link}", "FAIL")
                        try:
                            self.write_to_file(company, job_title, link, job_location, location)
                        except:
                            pass
                        self.file_name = temp
                except DailyLimitReachedException:
                    raise  # propagate up to start_applying()
                except:
                    traceback.print_exc()
                    self._log(f"Unexpected error processing job at {company} — skipping.", "FAIL")
                    pass
            else:
                reason = "already applied (persistent)" if already_applied else \
                         "blacklisted company" if company.lower() in [w.lower() for w in self.company_blacklist] else \
                         "blacklisted poster" if poster.lower() in [w.lower() for w in self.poster_blacklist] else \
                         "blacklisted title keyword" if contains_blacklisted_keywords else \
                         "already seen this session"
                self._log(f"SKIP  [{reason}]  —  {job_title} @ {company}", "SKIP")

            self.seen_jobs += link

    # Phrases LinkedIn shows when the daily Easy Apply limit is reached
    DAILY_LIMIT_PHRASES = [
        'we limit daily submissions',
        'save this job and apply tomorrow',
        'limit daily submissions to maintain quality',
    ]

    def _load_applied_jobs(self):
        """
        Load the set of job links already applied to from the persistent
        applied_jobs.csv file.  Called once at startup so the bot never
        re-applies across sessions.
        """
        links = set()
        if not os.path.exists(self.applied_jobs_file):
            return links
        try:
            with open(self.applied_jobs_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    url = row.get('link', '').strip()
                    if url:
                        links.add(url)
            self._log(f"Loaded {len(links)} previously applied job(s) from {self.applied_jobs_file}.", "INFO")
        except Exception as e:
            print(f"Could not load applied jobs: {e}")
        return links

    def _mark_job_applied(self, link, job_title, company, method):
        """
        Add a job URL to the in-memory set AND append it to the persistent
        applied_jobs.csv so the bot skips it on future runs.

        Args:
            link      : canonical job URL
            job_title : job title string
            company   : company name string
            method    : 'easy_apply' | 'external'
        """
        if not link:
            return
        self.applied_job_links.add(link)
        file_exists = os.path.exists(self.applied_jobs_file)
        try:
            with open(self.applied_jobs_file, 'a', newline='', encoding='utf-8') as f:
                fieldnames = ['link', 'job_title', 'company', 'method', 'timestamp']
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                if not file_exists:
                    writer.writeheader()
                writer.writerow({
                    'link':      link,
                    'job_title': job_title,
                    'company':   company,
                    'method':    method,
                    'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                })
        except Exception as e:
            print(f"Could not save applied job to {self.applied_jobs_file}: {e}")

    def _is_daily_limit_page(self):
        """Return True if the current page / modal contains the daily limit message."""
        try:
            src = self.browser.page_source.lower()
            return any(phrase in src for phrase in self.DAILY_LIMIT_PHRASES)
        except Exception:
            return False

    def _handle_daily_limit_reached(self):
        """
        Called when LinkedIn's Easy Apply daily limit is detected.
        Instead of closing the browser, sets a flag so the bot skips
        Easy Apply but continues processing external (company-website) jobs.
        """
        if self._easy_apply_exhausted:
            return  # already in external-only mode, nothing to do
        self._easy_apply_exhausted = True
        self._log_banner("EASY APPLY DAILY LIMIT REACHED")
        self._log("Switching to EXTERNAL-ONLY mode — browser stays open.", "WARN")
        self._log("Easy Apply jobs will be SKIPPED; external jobs will still be applied.", "WARN")
        if not self.apply_external_jobs:
            self._log(
                "applyExternalJobs is False — nothing left to do. "
                "Set applyExternalJobs: True in config.yaml to keep running.",
                "WARN"
            )

    def apply_to_job(self):
        """
        Detect the type of apply button on the current job page and route accordingly.

        Returns:
            "easy_apply_success"  — Easy Apply modal completed and submitted.
            "external_apply_success" — External website opened, CV uploaded, fields filled.
            "external_skipped"    — External job found but applyExternalJobs is disabled.
            False                 — No applicable button found (already applied, etc.).
        """
        # ── Detect button type ────────────────────────────────────────────────
        apply_button = None
        is_easy_apply = False
        try:
            # Try Easy Apply button first (has aria-label containing 'Easy Apply')
            candidates = self.browser.find_elements(By.CLASS_NAME, 'jobs-apply-button')
            for btn in candidates:
                label = (btn.get_attribute('aria-label') or btn.text or '').lower()
                if 'easy apply' in label:
                    apply_button = btn
                    is_easy_apply = True
                    break
            # If none matched as Easy Apply, take the first button as external
            if apply_button is None and candidates:
                apply_button = candidates[0]
                is_easy_apply = False
        except Exception:
            pass

        if apply_button is None:
            self._log("No apply button found — job may already be applied.", "SKIP")
            return False

        # ── If daily Easy Apply limit already hit, skip Easy Apply jobs ───────
        if is_easy_apply and self._easy_apply_exhausted:
            self._log("Easy Apply limit reached — skipping this Easy Apply job.", "SKIP")
            return "easy_apply_skipped"

        # ── Daily limit check (only relevant for Easy Apply path) ─────────────
        if is_easy_apply and self._is_daily_limit_page():
            raise DailyLimitReachedException(
                "LinkedIn daily submission limit detected before clicking Easy Apply."
            )

        # ── Route: External Apply ─────────────────────────────────────────────
        if not is_easy_apply:
            btn_text = (apply_button.get_attribute('aria-label') or apply_button.text or '').strip()
            self._log(f"Detected EXTERNAL apply button: '{btn_text}'", "INFO")
            if not self.apply_external_jobs:
                self._log("applyExternalJobs is False — skipping external job.", "SKIP")
                return "external_skipped"
            return self.apply_to_job_externally(apply_button)

        # ── Route: Easy Apply ─────────────────────────────────────────────────
        try:
            job_description_area = self.browser.find_element(By.ID, "job-details")
            self._log("Scrolling job description panel...", "STEP")
            self.scroll_slow(job_description_area, end=1600)
            self.scroll_slow(job_description_area, end=1600, step=400, reverse=True)
        except:
            pass

        self._log("Clicking Easy Apply button...", "STEP")
        apply_button.click()
        time.sleep(random.uniform(2, 3))

        # ── Daily limit check AFTER the modal opens ───────────────────────────
        if self._is_daily_limit_page():
            self._dismiss_modal()
            raise DailyLimitReachedException(
                "LinkedIn daily submission limit detected inside Easy Apply modal."
            )

        self._log("Easy Apply modal open. Filling form pages...", "STEP")
        button_text = ""
        submit_application_text = 'submit application'
        form_page = 0
        while submit_application_text not in button_text.lower():
            try:
                form_page += 1
                self._log(f"Form page {form_page} — filling fields...", "STEP")
                self.fill_up()
                # Find the Next/Submit button — try primary class then fallback to button text
                next_button = None
                try:
                    next_button = self.browser.find_element(By.CLASS_NAME, "artdeco-button--primary")
                except:
                    pass
                if not next_button:
                    # Fallback: find button inside dialog containing 'next', 'review', 'submit'
                    for btn in self.browser.find_elements(By.CSS_SELECTOR, '[role="dialog"] button'):
                        txt = btn.text.lower()
                        if any(k in txt for k in ['next', 'review', 'submit', 'continue']):
                            next_button = btn
                            break
                if not next_button:
                    raise Exception("Could not find Next/Submit button in Easy Apply modal.")
                button_text = next_button.text.lower()
                if submit_application_text in button_text:
                    self._log("Reached SUBMIT page — unfollowing company then submitting...", "STEP")
                    try:
                        self.unfollow()
                    except:
                        self._log("Could not unfollow company (non-critical).", "WARN")
                else:
                    self._log(f"Clicking '{next_button.text.strip()}' to advance...", "STEP")
                time.sleep(random.uniform(1.5, 2.5))
                next_button.click()
                time.sleep(random.uniform(3.0, 5.0))

                error_messages = [
                    'enter a valid',
                    'enter a decimal',
                    'Enter a whole number'
                    'Enter a whole number between 0 and 99',
                    'file is required',
                    'whole number',
                    'make a selection',
                    'select checkbox to proceed',
                    'saisissez un numéro',
                    '请输入whole编号',
                    '请输入decimal编号',
                    '长度超过 0.0',
                    'Numéro de téléphone',
                    'Introduce un número de whole entre',
                    'Inserisci un numero whole compreso',
                    'Preguntas adicionales',
                    'Insira um um número',
                    'Cuántos años'
                    'use the format',
                    'A file is required',
                    '请选择',
                    '请 选 择',
                    'Inserisci',
                    'wholenummer',
                    'Wpisz liczb',
                    'zakresu od',
                    'tussen'
                ]

                if any(error in self.browser.page_source.lower() for error in error_messages):
                    self._log("Form validation error detected — a field was not answered correctly.", "FAIL")
                    raise Exception("Failed answering required questions or uploading required files.")
            except DailyLimitReachedException:
                raise
            except:
                traceback.print_exc()
                if self._is_daily_limit_page():
                    self._dismiss_modal()
                    raise DailyLimitReachedException(
                        "LinkedIn daily submission limit detected during form fill."
                    )
                self._log("Exception during form fill — discarding application.", "FAIL")
                self._dismiss_modal()
                time.sleep(random.uniform(1, 2))
                try:
                    self.browser.find_elements(By.CLASS_NAME, 'artdeco-modal__confirm-dialog-btn')[0].click()
                except:
                    try:
                        # Fallback: click first button in any confirm dialog
                        self.browser.find_elements(By.CSS_SELECTOR, '[role="dialog"] button')[0].click()
                    except:
                        pass
                time.sleep(random.uniform(1, 2))
                raise Exception("Failed to apply to job!")

        closed_notification = False
        time.sleep(random.uniform(1, 2))
        if self._dismiss_modal():
            closed_notification = True
            self._log("Confirmation modal closed.", "OK")
        try:
            self.browser.find_element(By.CLASS_NAME, 'artdeco-toast-item__dismiss').click()
            closed_notification = True
            self._log("Toast notification dismissed.", "OK")
        except:
            try:
                self.browser.find_element(By.CSS_SELECTOR, 'button[aria-label*="dismiss"]').click()
                closed_notification = True
            except:
                pass
        try:
            self.browser.find_element(By.CSS_SELECTOR, 'button[data-control-name="save_application_btn"]').click()
            closed_notification = True
            self._log("Application saved via save button.", "OK")
        except:
            pass

        time.sleep(random.uniform(1, 2))

        if closed_notification is False:
            # Don't raise — application may have been submitted fine without a dismissible notification
            self._log("No confirmation modal found — assuming application submitted.", "WARN")

        return "easy_apply_success"

    # ── External (company website) apply ──────────────────────────────────────

    # Common field name/id/placeholder patterns for heuristic detection
    _EXT_FIRST_NAME_HINTS  = ['first_name', 'firstname', 'fname', 'first-name', 'given']
    _EXT_LAST_NAME_HINTS   = ['last_name', 'lastname', 'lname', 'last-name', 'surname', 'family']
    _EXT_FULL_NAME_HINTS   = ['full_name', 'fullname', 'your_name', 'your-name', 'name']
    _EXT_EMAIL_HINTS       = ['email', 'e-mail', 'mail']
    _EXT_PHONE_HINTS       = ['phone', 'mobile', 'telephone', 'tel', 'cell']

    def _ext_field_matches(self, element, hints):
        """Return True if any hint string appears in the element's id, name, or placeholder."""
        attrs = [
            (element.get_attribute('id') or '').lower(),
            (element.get_attribute('name') or '').lower(),
            (element.get_attribute('placeholder') or '').lower(),
            (element.get_attribute('autocomplete') or '').lower(),
        ]
        combined = ' '.join(attrs)
        return any(h in combined for h in hints)

    def _ext_fill_text_inputs(self):
        """
        Scan all visible text/email/tel inputs on the current page and fill
        first name, last name, full name, email, and phone wherever detected.
        Returns a summary dict of what was filled.
        """
        filled = {}
        try:
            inputs = self.browser.find_elements(
                By.CSS_SELECTOR,
                'input[type="text"], input[type="email"], input[type="tel"], input:not([type])'
            )
            for inp in inputs:
                try:
                    if not inp.is_displayed() or not inp.is_enabled():
                        continue
                    val = (inp.get_attribute('value') or '').strip()

                    if self._ext_field_matches(inp, self._EXT_FIRST_NAME_HINTS):
                        if not val:  # don't overwrite autofilled content
                            inp.clear()
                            inp.send_keys(self.personal_info['First Name'])
                            filled['first_name'] = self.personal_info['First Name']
                            self._log(f"External form: filled first name", "STEP")

                    elif self._ext_field_matches(inp, self._EXT_LAST_NAME_HINTS):
                        if not val:
                            inp.clear()
                            inp.send_keys(self.personal_info['Last Name'])
                            filled['last_name'] = self.personal_info['Last Name']
                            self._log(f"External form: filled last name", "STEP")

                    elif self._ext_field_matches(inp, self._EXT_FULL_NAME_HINTS):
                        if not val and 'first_name' not in filled and 'last_name' not in filled:
                            full = self.personal_info['First Name'] + ' ' + self.personal_info['Last Name']
                            inp.clear()
                            inp.send_keys(full)
                            filled['full_name'] = full
                            self._log(f"External form: filled full name", "STEP")

                    elif self._ext_field_matches(inp, self._EXT_EMAIL_HINTS):
                        if not val:
                            inp.clear()
                            inp.send_keys(self.email)
                            filled['email'] = self.email
                            self._log(f"External form: filled email", "STEP")

                    elif self._ext_field_matches(inp, self._EXT_PHONE_HINTS):
                        if not val:
                            inp.clear()
                            inp.send_keys(str(self.personal_info['Mobile Phone Number']))
                            filled['phone'] = self.personal_info['Mobile Phone Number']
                            self._log(f"External form: filled phone", "STEP")
                except Exception:
                    continue
        except Exception as e:
            self._log(f"External form fill error: {e}", "WARN")
        return filled

    def _ext_upload_cv(self):
        """
        Find any file upload input on the page and send the resume path.
        Returns True if at least one upload succeeded.
        """
        uploaded = False
        try:
            file_inputs = self.browser.find_elements(
                By.CSS_SELECTOR, 'input[type="file"]'
            )
            for finput in file_inputs:
                try:
                    # Use JavaScript to make the element interactable even if visually hidden
                    self.browser.execute_script(
                        "arguments[0].style.display = 'block'; arguments[0].style.visibility = 'visible';",
                        finput
                    )
                    time.sleep(0.3)
                    finput.send_keys(self.resume_dir)
                    time.sleep(random.uniform(2, 4))  # wait for upload/parse
                    uploaded = True
                    self._log(f"External form: CV uploaded via file input", "OK")
                    break  # upload to the first file input found
                except Exception as e:
                    self._log(f"External form: could not upload to a file input — {e}", "WARN")
        except Exception as e:
            self._log(f"External form: file input search error — {e}", "WARN")
        return uploaded

    # Selectors / text hints that identify "Apply with LinkedIn" buttons on company ATS pages
    _LI_BUTTON_TEXTS = [
        'apply with linkedin',
        'sign in with linkedin',
        'continue with linkedin',
        'login with linkedin',
        'apply via linkedin',
    ]

    def _ext_try_apply_with_linkedin(self):
        """
        Look for an 'Apply with LinkedIn' / 'Sign in with LinkedIn' button on
        the current company page and click it.

        Flow:
          1. Search all buttons/links/images whose text, aria-label, alt, or
             src contains a LinkedIn-apply hint.
          2. Click the first match found.
          3. If clicking opens a new OAuth popup, switch to it, wait for it to
             close (LinkedIn handles the auth using the saved session cookie),
             then switch back.
          4. Return True if a button was found and clicked, False otherwise.
        """
        try:
            # ── Collect candidates ────────────────────────────────────────────
            candidates = []

            # a) Buttons and anchor tags whose visible text matches
            for tag in ('button', 'a'):
                elements = self.browser.find_elements(By.TAG_NAME, tag)
                for el in elements:
                    try:
                        text = (el.text or '').lower().strip()
                        aria = (el.get_attribute('aria-label') or '').lower()
                        combined = text + ' ' + aria
                        if any(hint in combined for hint in self._LI_BUTTON_TEXTS):
                            candidates.append(el)
                    except Exception:
                        continue

            # b) Images with alt text (some ATS render the LinkedIn button as an img)
            imgs = self.browser.find_elements(By.TAG_NAME, 'img')
            for img in imgs:
                try:
                    alt = (img.get_attribute('alt') or '').lower()
                    src = (img.get_attribute('src') or '').lower()
                    if any(hint in alt for hint in self._LI_BUTTON_TEXTS) or \
                       ('linkedin' in src and 'apply' in src):
                        # Click the parent element (the link/button wrapping the image)
                        parent = img.find_element(By.XPATH, '..')
                        candidates.append(parent)
                except Exception:
                    continue

            if not candidates:
                self._log("External form: no 'Apply with LinkedIn' button found.", "INFO")
                return False

            btn = candidates[0]
            btn_label = (btn.get_attribute('aria-label') or btn.text or 'Apply with LinkedIn').strip()
            self._log(f"External form: found LinkedIn button — '{btn_label}' — clicking...", "STEP")

            # ── Click and handle possible OAuth popup ─────────────────────────
            tabs_before = set(self.browser.window_handles)
            current_tab = self.browser.current_window_handle

            try:
                btn.click()
            except Exception:
                self.browser.execute_script("arguments[0].click();", btn)

            time.sleep(3)  # let any popup/redirect begin

            tabs_after = set(self.browser.window_handles)
            popup_tabs = tabs_after - tabs_before

            if popup_tabs:
                popup = popup_tabs.pop()
                self._log("LinkedIn OAuth popup opened — waiting for it to close...", "STEP")
                self.browser.switch_to.window(popup)

                # Wait up to 30 s for the popup to auto-close
                # (LinkedIn auto-authorises when the session cookie is present)
                for _ in range(30):
                    time.sleep(1)
                    if popup not in self.browser.window_handles:
                        break  # popup closed on its own — auth done
                else:
                    # Popup still open after 30 s — close it only if safe
                    if len(self.browser.window_handles) > 1:
                        try:
                            if popup in self.browser.window_handles:
                                self.browser.switch_to.window(popup)
                                self.browser.close()
                        except Exception:
                            pass

                # Return to the company page tab
                if current_tab in self.browser.window_handles:
                    self.browser.switch_to.window(current_tab)
                    time.sleep(random.uniform(2, 4))
                    self._log("Returned to company page after LinkedIn OAuth.", "OK")
            else:
                # No popup — LinkedIn button may have triggered an inline auth or redirect
                time.sleep(random.uniform(3, 5))

            self._log("'Apply with LinkedIn' interaction complete.", "OK")
            return True

        except Exception as e:
            self._log(f"External form: 'Apply with LinkedIn' attempt failed — {e}", "WARN")
            return False

    # ── AI-assisted external apply helpers ────────────────────────────────────

    def _ext_capture_interactive_html(self):
        """
        Extract a compact HTML snapshot of only the interactive elements on the
        current page (inputs, buttons, selects, textareas, file inputs, links
        that look like apply buttons).  This keeps the token count low when
        sending to GPT-4o.
        """
        try:
            snippet = self.browser.execute_script("""
                const tags = ['input','button','select','textarea','a'];
                const rows = [];
                tags.forEach(tag => {
                    document.querySelectorAll(tag).forEach(el => {
                        const attrs = Array.from(el.attributes)
                            .map(a => `${a.name}="${a.value}"`)
                            .join(' ');
                        const text = (el.innerText || '').trim().slice(0,80);
                        rows.push(`<${tag} ${attrs}>${text}</${tag}>`);
                    });
                });
                return rows.join('\\n');
            """)
            return snippet or ""
        except Exception as e:
            self._log(f"Could not capture interactive HTML: {e}", "WARN")
            return ""

    def _ext_execute_ai_plan(self, plan):
        """
        Execute a structured action plan returned by AIResponseGenerator.analyze_external_page().

        Supported step actions:
          click  — find element by CSS selector and click it
          fill   — find element by CSS selector and type a value ({token} substitution applied)
          upload — find file input by CSS selector and send the resume path
          scroll — scroll the page (direction: "down" | "up")
          wait   — sleep for 'seconds'

        Returns a summary dict: {action: success_count}
        """
        if not plan or 'steps' not in plan:
            return {}

        # Token substitution map
        tokens = {
            '{first_name}': self.personal_info.get('First Name', ''),
            '{last_name}':  self.personal_info.get('Last Name', ''),
            '{full_name}':  f"{self.personal_info.get('First Name','')} {self.personal_info.get('Last Name','')}".strip(),
            '{email}':      self.email,
            '{phone}':      str(self.personal_info.get('Mobile Phone Number', '')),
            '{linkedin}':   self.personal_info.get('Linkedin', ''),
            '{website}':    self.personal_info.get('Website', ''),
        }

        summary = {}
        steps = plan.get('steps', [])
        self._log(f"AI plan has {len(steps)} step(s) — executing...", "STEP")

        for i, step in enumerate(steps):
            action = step.get('action', '').lower()
            selector = step.get('selector', '')
            try:
                if action == 'click':
                    el = self.browser.find_element(By.CSS_SELECTOR, selector)
                    self.browser.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
                    time.sleep(0.3)
                    try:
                        el.click()
                    except Exception:
                        self.browser.execute_script("arguments[0].click();", el)
                    time.sleep(random.uniform(1.0, 2.0))
                    self._log(f"  Step {i+1}: clicked '{selector}'", "OK")
                    summary['click'] = summary.get('click', 0) + 1

                elif action == 'fill':
                    raw_value = step.get('value', '')
                    # Apply token substitution
                    for token, val in tokens.items():
                        raw_value = raw_value.replace(token, val)
                    el = self.browser.find_element(By.CSS_SELECTOR, selector)
                    self.browser.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
                    # Only fill if currently empty (don't overwrite autofilled data)
                    current_val = (el.get_attribute('value') or '').strip()
                    if not current_val:
                        el.clear()
                        el.send_keys(raw_value)
                        self._log(f"  Step {i+1}: filled '{selector}' with '{raw_value[:30]}...' " if len(raw_value) > 30 else f"  Step {i+1}: filled '{selector}' with '{raw_value}'", "OK")
                        summary['fill'] = summary.get('fill', 0) + 1
                    else:
                        self._log(f"  Step {i+1}: skipped fill '{selector}' (already has value)", "INFO")

                elif action == 'upload':
                    el = self.browser.find_element(By.CSS_SELECTOR, selector)
                    # Make hidden file inputs interactable
                    self.browser.execute_script(
                        "arguments[0].style.display='block'; arguments[0].style.visibility='visible';", el
                    )
                    time.sleep(0.3)
                    el.send_keys(self.resume_dir)
                    time.sleep(random.uniform(2, 4))  # wait for upload/parse
                    self._log(f"  Step {i+1}: uploaded CV to '{selector}'", "OK")
                    summary['upload'] = summary.get('upload', 0) + 1

                elif action == 'scroll':
                    direction = step.get('direction', 'down')
                    amount = 600 if direction == 'down' else -600
                    self.browser.execute_script(f"window.scrollBy(0, {amount});")
                    time.sleep(random.uniform(0.5, 1.0))
                    self._log(f"  Step {i+1}: scrolled {direction}", "OK")
                    summary['scroll'] = summary.get('scroll', 0) + 1

                elif action == 'wait':
                    secs = float(step.get('seconds', 2))
                    time.sleep(secs)
                    self._log(f"  Step {i+1}: waited {secs}s", "OK")
                    summary['wait'] = summary.get('wait', 0) + 1

                else:
                    self._log(f"  Step {i+1}: unknown action '{action}' — skipping", "WARN")

            except Exception as e:
                self._log(f"  Step {i+1}: FAILED action='{action}' selector='{selector}' — {e}", "WARN")
                continue

        self._log(f"AI plan execution done: {summary}", "OK")
        return summary

    def apply_to_job_externally(self, apply_button):
        """
        Click the external Apply button, switch to the new tab opened by the
        company website, then apply using a 3-tier strategy:

          Tier 1 (AI-guided)  — Screenshot + compact DOM → GPT-4o → JSON action plan → execute
          Tier 2 (LinkedIn)   — Detect and click 'Apply with LinkedIn' button
          Tier 3 (Heuristic)  — CV upload + heuristic name/email/phone field fill

        Returns:
            "external_apply_success"  if the tab was opened and interacted with.
            False                     if something went wrong before the tab opened.
        """
        linkedin_tab = self.browser.current_window_handle
        tabs_before = set(self.browser.window_handles)

        try:
            self._log("Clicking external Apply button...", "STEP")
            self.browser.execute_script("arguments[0].click();", apply_button)
            time.sleep(random.uniform(3, 5))
        except Exception as e:
            self._log(f"Could not click external Apply button: {e}", "FAIL")
            return False

        # ── Switch to newly opened tab ────────────────────────────────────────
        tabs_after = set(self.browser.window_handles)
        new_tab_handles = tabs_after - tabs_before
        opened_new_tab = bool(new_tab_handles)

        if opened_new_tab:
            new_tab = new_tab_handles.pop()
            self._log("Switching to new company tab...", "STEP")
            try:
                self.browser.switch_to.window(new_tab)
            except Exception as e:
                self._log(f"Could not switch to new tab: {e}", "WARN")
                return False
            time.sleep(5)
            time.sleep(random.uniform(1.5, 3.0))
            company_tab = new_tab
        else:
            self._log("No new tab detected — company site may have loaded in same tab.", "WARN")
            time.sleep(5)
            time.sleep(random.uniform(1.0, 2.0))
            company_tab = None

        company_url   = self.browser.current_url
        company_title = self.browser.title
        domain        = self._get_domain(company_url)
        self._log(f"Company page loaded: {company_url}  (domain: {domain})", "INFO")

        candidate_info = {
            'first_name':  self.personal_info.get('First Name', ''),
            'last_name':   self.personal_info.get('Last Name', ''),
            'email':       self.email,
            'phone':       str(self.personal_info.get('Mobile Phone Number', '')),
            'linkedin':    self.personal_info.get('Linkedin', ''),
            'website':     self.personal_info.get('Website', ''),
            'resume_path': self.resume_dir,
        }

        pattern_used     = False
        ai_succeeded     = False
        linkedin_applied = False
        cv_uploaded      = False
        fields_filled    = {}

        try:
            # ── Tier 0: Replay saved domain pattern ───────────────────────────
            pattern_used = self._try_site_pattern(domain)

            # ── Tier 1: AI analysis (HTML only, no screenshot) ────────────────
            if not pattern_used:
                self._log("Tier 1: capturing interactive DOM for AI analysis...", "STEP")
                interactive_html = self._ext_capture_interactive_html()

                self._log("Sending page HTML to GPT-4o-mini for action plan...", "STEP")
                plan = self.ai_response_generator.analyze_page_html(
                    interactive_html, company_title, company_url, candidate_info
                )

                if plan and plan.get('strategy') not in ('unknown', None):
                    self._log(f"AI strategy: {plan.get('strategy')} — {plan.get('explanation','')}", "OK")
                    result = self._ext_execute_ai_plan(plan)
                    ai_succeeded = bool(result)
                    if result and 'upload' in result:
                        self._log("Waiting for CV autofill after AI-guided upload...", "STEP")
                        time.sleep(random.uniform(4, 7))
                        refill_plan = {'steps': [s for s in plan.get('steps', []) if s.get('action') == 'fill']}
                        self._ext_execute_ai_plan(refill_plan)
                else:
                    self._log("AI returned 'unknown' strategy — moving to next tier.", "WARN")

            # ── Tier 2: Apply with LinkedIn button ────────────────────────────
            if not pattern_used and not ai_succeeded:
                self._log("Tier 2: looking for 'Apply with LinkedIn' button...", "STEP")
                linkedin_applied = self._ext_try_apply_with_linkedin()

            # ── Tier 3: Heuristic CV upload + field fill ──────────────────────
            if not pattern_used and not ai_succeeded and not linkedin_applied:
                self._log("Tier 3: heuristic CV upload + field fill...", "STEP")
                cv_uploaded = self._ext_upload_cv()
                if cv_uploaded:
                    self._log("Waiting for autofill after CV upload...", "STEP")
                    time.sleep(random.uniform(4, 7))
                fields_filled = self._ext_fill_text_inputs()

            # ── Tier 4 (Human-in-the-loop) ────────────────────────────────────
            # Trigger if no automated tier made any progress
            any_progress = pattern_used or ai_succeeded or linkedin_applied or cv_uploaded or bool(fields_filled)
            if not any_progress:
                self._wait_for_human_assistance(domain, timeout=30)
            else:
                # Still capture human corrections during review window
                self._log("⏳ Watching for human corrections — 15 seconds before closing tab...", "WARN")
                self._start_capture_js()
                time.sleep(15)
                correction_events = self._stop_capture_js()
                if correction_events:
                    self._log(f"Human made {len(correction_events)} correction(s) — updating pattern.", "OK")
                    steps = self._tokenize_captured_actions(correction_events)
                    if steps and domain not in self.site_patterns:
                        # Only auto-save corrections as a pattern if we don't have one yet
                        self.site_patterns[domain] = {
                            'steps':         steps,
                            'strategy':      'manual_form',
                            'success_count': 1,
                            'last_used':     datetime.now().strftime("%Y-%m-%d"),
                            'learned_from':  datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        }
                        self._save_site_patterns()
                        self._log(f"✨ Saved human corrections as pattern for '{domain}'.", "OK")

            summary = (
                f"Pattern: {pattern_used} | AI: {ai_succeeded} | "
                f"LinkedIn btn: {linkedin_applied} | CV: {cv_uploaded} | Fields: {list(fields_filled.keys())}"
            )
            self._log(f"External form interaction complete — {summary}", "OK")

        except Exception as e:
            self._log(f"Error interacting with external form: {e}", "WARN")
            traceback.print_exc()

        # ── Close company tab and return to LinkedIn ──────────────────────────
        try:
            all_handles = self.browser.window_handles
            if (
                opened_new_tab
                and company_tab in all_handles
                and len(all_handles) > 1
            ):
                self._log("Closing company tab and returning to LinkedIn...", "STEP")
                self.browser.switch_to.window(company_tab)
                self.browser.close()

            all_handles = self.browser.window_handles
            if linkedin_tab in all_handles:
                self.browser.switch_to.window(linkedin_tab)
                time.sleep(random.uniform(1.5, 2.5))
                self._log("Returned to LinkedIn tab.", "OK")
            else:
                if all_handles:
                    self._log("LinkedIn tab not found — switching to first available window.", "WARN")
                    self.browser.switch_to.window(all_handles[0])
                else:
                    self._log("No browser windows remaining — session may be lost.", "FAIL")
        except Exception as e:
            self._log(f"Tab clean-up error: {e}", "WARN")
            try:
                remaining = self.browser.window_handles
                if remaining:
                    self.browser.switch_to.window(remaining[0])
            except Exception:
                pass

        return "external_apply_success"



    def home_address(self, form):
        print("Trying to fill up home address fields")
        try:
            groups = form.find_elements(By.CLASS_NAME, 'jobs-easy-apply-form-section__grouping')
            if len(groups) > 0:
                for group in groups:
                    lb = group.find_element(By.TAG_NAME, 'label').text.lower()
                    input_field = group.find_element(By.TAG_NAME, 'input')
                    if 'street' in lb:
                        self.enter_text(input_field, self.personal_info['Street address'])
                    elif 'city' in lb:
                        self.enter_text(input_field, self.personal_info['City'])
                        time.sleep(3)
                        input_field.send_keys(Keys.DOWN)
                        input_field.send_keys(Keys.RETURN)
                    elif 'zip' in lb or 'zip / postal code' in lb or 'postal' in lb:
                        self.enter_text(input_field, self.personal_info['Zip'])
                    elif 'state' in lb or 'province' in lb:
                        self.enter_text(input_field, self.personal_info['State'])
                    else:
                        pass
        except:
            pass

    def get_answer(self, question):
        if self.checkboxes[question]:
            return 'yes'
        else:
            return 'no'

    def additional_questions(self, form):
        print("Trying to fill up additional questions")

        questions = form.find_elements(By.CLASS_NAME, 'fb-dash-form-element')
        for question in questions:
            # Honour pause before filling each individual question
            self._wait_if_paused()
            try:
                # Radio check
                radio_fieldset = question.find_element(By.TAG_NAME, 'fieldset')
                question_span = radio_fieldset.find_element(By.CLASS_NAME, 'fb-dash-form-element__label').find_elements(By.TAG_NAME, 'span')[0]
                radio_text = question_span.text.lower()
                print(f"Radio question text: {radio_text}")

                radio_labels = radio_fieldset.find_elements(By.TAG_NAME, 'label')
                radio_options = [(i, text.text.lower()) for i, text in enumerate(radio_labels)]
                print(f"radio options: {[opt[1] for opt in radio_options]}")
                
                if len(radio_options) == 0:
                    raise Exception("No radio options found in question")

                answer = None

                # Try to determine answer using existing logic
                if 'driver\'s licence' in radio_text or 'driver\'s license' in radio_text:
                    answer = self.get_answer('driversLicence')
                elif any(keyword in radio_text.lower() for keyword in
                         [
                             'Aboriginal', 'native', 'indigenous', 'tribe', 'first nations',
                             'native american', 'native hawaiian', 'inuit', 'metis', 'maori',
                             'aborigine', 'ancestral', 'native peoples', 'original people',
                             'first people', 'gender', 'race', 'disability', 'latino', 'torres',
                             'do you identify'
                         ]):
                    negative_keywords = ['prefer', 'decline', 'don\'t', 'specified', 'none', 'no']
                    answer = next((option for option in radio_options if
                                   any(neg_keyword in option[1].lower() for neg_keyword in negative_keywords)), None)

                elif 'assessment' in radio_text:
                    answer = self.get_answer("assessment")

                elif 'clearance' in radio_text:
                    answer = self.get_answer("securityClearance")

                elif 'north korea' in radio_text:
                    answer = 'no'

                elif 'previously employ' in radio_text or 'previous employ' in radio_text:
                    answer = 'no'

                elif 'authorized' in radio_text or 'authorised' in radio_text or 'legally' in radio_text:
                    answer = self.get_answer('legallyAuthorized')

                elif any(keyword in radio_text.lower() for keyword in
                         ['certified', 'certificate', 'cpa', 'chartered accountant', 'qualification']):
                    answer = self.get_answer('certifiedProfessional')

                elif 'urgent' in radio_text:
                    answer = self.get_answer('urgentFill')

                elif 'commut' in radio_text or 'on-site' in radio_text or 'hybrid' in radio_text or 'onsite' in radio_text:
                    answer = self.get_answer('commute')

                elif 'remote' in radio_text:
                    answer = self.get_answer('remote')

                elif 'background check' in radio_text:
                    answer = self.get_answer('backgroundCheck')

                elif 'drug test' in radio_text:
                    answer = self.get_answer('drugTest')

                elif 'currently living' in radio_text or 'currently reside' in radio_text or 'right to live' in radio_text:
                    answer = self.get_answer('residency')

                elif 'level of education' in radio_text:
                    for degree in self.checkboxes['degreeCompleted']:
                        if degree.lower() in radio_text:
                            answer = "yes"
                            break

                elif 'experience' in radio_text:
                    if self.experience_default > 0:
                        answer = 'yes'
                    else:
                        for experience in self.experience:
                            if experience.lower() in radio_text:
                                answer = "yes"
                                break

                elif 'data retention' in radio_text:
                    answer = 'no'

                elif 'sponsor' in radio_text:
                    answer = self.get_answer('requireVisa')
                
                to_select = None
                if answer is not None:
                    print(f"Choosing answer: {answer}")
                    i = 0
                    for radio in radio_labels:
                        if answer in radio.text.lower():
                            to_select = radio_labels[i]
                            break
                        i += 1
                    if to_select is None:
                        print("Answer not found in radio options")

                if to_select is None:
                    print("No answer determined")
                    self.record_unprepared_question("radio", radio_text)
                    self._save_unanswered_question("radio", radio_text)

                    # 1. Check if user manually provided an answer in unanswered_question.csv
                    user_ans = self.user_answers.get(radio_text.strip().lower())
                    if user_ans:
                        print(f"Using user-provided answer for radio: '{user_ans}'")
                        for i, radio in enumerate(radio_labels):
                            if user_ans.lower() in radio.text.lower():
                                to_select = radio_labels[i]
                                break

                    # 2. Ask user via browser chat if still unresolved
                    if to_select is None:
                        option_texts = [opt[1] for opt in radio_options]
                        chat_ans = self._ask_user_via_chat("radio", radio_text, options=option_texts)
                        if chat_ans:
                            for i, radio in enumerate(radio_labels):
                                if chat_ans.lower() in radio.text.lower():
                                    to_select = radio_labels[i]
                                    break

                    # 3. Fall back to AI if chat timed out
                    if to_select is None:
                        ai_response = self.ai_response_generator.generate_response(
                            radio_text,
                            response_type="choice",
                            options=radio_options
                        )
                        if ai_response is not None:
                            to_select = radio_labels[ai_response]
                        else:
                            to_select = radio_labels[len(radio_labels) - 1]
                to_select.click()

                if radio_labels:
                    continue
            except Exception as e:
                print("An exception occurred while filling up radio field")

            # Questions check
            try:
                question_text = question.find_element(By.TAG_NAME, 'label').text.lower()
                print( question_text )  # TODO: Put logging behind debug flag

                txt_field_visible = False
                try:
                    txt_field = question.find_element(By.TAG_NAME, 'input')
                    txt_field_visible = True
                except:
                    try:
                        txt_field = question.find_element(By.TAG_NAME, 'textarea')  # TODO: Test textarea
                        txt_field_visible = True
                    except:
                        raise Exception("Could not find textarea or input tag for question")

                if 'numeric' in txt_field.get_attribute('id').lower():
                    # For decimal and integer response fields, the id contains 'numeric' while the type remains 'text' 
                    text_field_type = 'numeric'
                elif 'text' in txt_field.get_attribute('type').lower():
                    text_field_type = 'text'
                else:
                    raise Exception("Could not determine input type of input field!")

                to_enter = ''
                if 'experience' in question_text or 'how many years in' in question_text:
                    no_of_years = None
                    for experience in self.experience:
                        if experience.lower() in question_text:
                            no_of_years = int(self.experience[experience])
                            break
                    if no_of_years is None:
                        self.record_unprepared_question(text_field_type, question_text)
                        no_of_years = int(self.experience_default)
                    to_enter = no_of_years

                elif 'grade point average' in question_text:
                    to_enter = self.university_gpa

                elif 'first name' in question_text:
                    to_enter = self.personal_info['First Name']

                elif 'last name' in question_text:
                    to_enter = self.personal_info['Last Name']

                elif 'name' in question_text:
                    to_enter = self.personal_info['First Name'] + " " + self.personal_info['Last Name']

                elif any(kw in question_text for kw in ('city', 'location (city)', 'location')):
                    # City / location typeahead field — type value then pick first suggestion
                    city_val = self.personal_info.get('City', '')
                    if city_val:
                        try:
                            current_val = txt_field.get_attribute('value') or ''
                            if current_val.strip().lower() == city_val.strip().lower():
                                # Already correctly filled — skip
                                continue
                            txt_field.clear()
                            txt_field.send_keys(city_val)
                            time.sleep(2)                   # wait for typeahead suggestions
                            txt_field.send_keys(Keys.DOWN)  # highlight first suggestion
                            time.sleep(0.5)
                            txt_field.send_keys(Keys.RETURN)  # select it
                            time.sleep(1)
                        except Exception as loc_err:
                            print(f"City/location field error: {loc_err}")
                        continue
                    else:
                        to_enter = ''   # fall through to AI/user-answer resolution

                elif 'pronouns' in question_text:
                    to_enter = self.personal_info['Pronouns']

                elif 'phone' in question_text:
                    to_enter = self.personal_info['Mobile Phone Number']

                elif 'linkedin' in question_text:
                    to_enter = self.personal_info['Linkedin']

                elif 'message to hiring' in question_text or 'cover letter' in question_text:
                    to_enter = self.personal_info['MessageToManager']

                elif 'website' in question_text or 'github' in question_text or 'portfolio' in question_text:
                    to_enter = self.personal_info['Website']

                elif 'notice' in question_text or 'weeks' in question_text:
                    if text_field_type == 'numeric':
                        to_enter = int(self.notice_period)
                    else:
                        to_enter = str(self.notice_period)

                elif 'salary' in question_text or 'expectation' in question_text or 'compensation' in question_text or 'CTC' in question_text:
                    if text_field_type == 'numeric':
                        to_enter = int(self.salary_minimum)
                    else:
                        to_enter = float(self.salary_minimum)
                    self.record_unprepared_question(text_field_type, question_text)

                # Resolve unanswered fields: user CSV → AI → safe default
                if text_field_type == 'numeric':
                    if not isinstance(to_enter, (int, float)):
                        # 1. Check user-provided answer
                        user_ans = self.user_answers.get(question_text.strip().lower())
                        if user_ans:
                            print(f"Using user-provided answer for numeric field: '{user_ans}'")
                            try:
                                to_enter = int(user_ans)
                            except ValueError:
                                try:
                                    to_enter = float(user_ans)
                                except ValueError:
                                    pass
                        # 2. Still not resolved → ask user via chat, then try AI
                        if not isinstance(to_enter, (int, float)):
                            self._save_unanswered_question('numeric', question_text)
                            chat_ans = self._ask_user_via_chat("numeric", question_text)
                            if chat_ans:
                                try:
                                    to_enter = int(chat_ans)
                                except ValueError:
                                    try:
                                        to_enter = float(chat_ans)
                                    except ValueError:
                                        pass
                        # 3. Still not resolved → fall back to AI
                        if not isinstance(to_enter, (int, float)):
                            ai_response = self.ai_response_generator.generate_response(
                                question_text,
                                response_type="numeric"
                            )
                            to_enter = ai_response if ai_response is not None else 0
                elif to_enter == '':
                    # 1. Check user-provided answer
                    user_ans = self.user_answers.get(question_text.strip().lower())
                    if user_ans:
                        print(f"Using user-provided answer for text field: '{user_ans}'")
                        to_enter = user_ans
                    else:
                        # 2. Save as unanswered & try AI
                        self._save_unanswered_question('text', question_text)
                        ai_response = self.ai_response_generator.generate_response(
                            question_text,
                            response_type="text"
                        )
                        to_enter = ai_response if ai_response is not None else " ‎ "

                self.enter_text(txt_field, to_enter)
                continue
            except:
                print("An exception occurred while filling up text field")  # TODO: Put logging behind debug flag

            # Date Check
            try:
                date_picker = question.find_element(By.CLASS_NAME, 'artdeco-datepicker__input ')
                date_picker.clear()
                date_picker.send_keys(date.today().strftime("%m/%d/%y"))
                time.sleep(3)
                date_picker.send_keys(Keys.RETURN)
                time.sleep(2)
                continue
            except:
                print("An exception occurred while filling up date picker field")  # TODO: Put logging behind debug flag

            # Dropdown check
            try:
                question_text = question.find_element(By.TAG_NAME, 'label').text.lower()
                print(f"Dropdown question text: {question_text}")  # TODO: Put logging behind debug flag
                dropdown_field = question.find_element(By.TAG_NAME, 'select')

                select = Select(dropdown_field)
                options = [options.text for options in select.options]
                print(f"Dropdown options: {options}")  # TODO: Put logging behind debug flag

                if 'proficiency' in question_text:
                    proficiency = "None"
                    for language in self.languages:
                        if language.lower() in question_text:
                            proficiency = self.languages[language]
                            break
                    self.select_dropdown(dropdown_field, proficiency)

                elif 'clearance' in question_text:
                    answer = self.get_answer('securityClearance')

                    choice = ""
                    for option in options:
                        if answer == 'yes':
                            choice = option
                        else:
                            if 'no' in option.lower():
                                choice = option
                    if choice == "":
                        self.record_unprepared_question(text_field_type, question_text)
                    self.select_dropdown(dropdown_field, choice)

                elif 'assessment' in question_text:
                    answer = self.get_answer('assessment')
                    choice = ""
                    for option in options:
                        if answer == 'yes':
                            choice = option
                        else:
                            if 'no' in option.lower():
                                choice = option
                    # if choice == "":
                    #    choice = options[len(options) - 1]
                    self.select_dropdown(dropdown_field, choice)

                elif 'commut' in question_text or 'on-site' in question_text or 'hybrid' in question_text or 'onsite' in question_text:
                    answer = self.get_answer('commute')

                    choice = ""
                    for option in options:
                        if answer == 'yes':
                            choice = option
                        else:
                            if 'no' in option.lower():
                                choice = option
                    # if choice == "":
                    #    choice = options[len(options) - 1]
                    self.select_dropdown(dropdown_field, choice)

                elif 'country code' in question_text:
                    self.select_dropdown(dropdown_field, self.personal_info['Phone Country Code'])

                elif 'north korea' in question_text:
                    choice = ""
                    for option in options:
                        if 'no' in option.lower():
                            choice = option
                    if choice == "":
                        choice = options[len(options) - 1]
                    self.select_dropdown(dropdown_field, choice)

                elif 'previously employed' in question_text or 'previous employment' in question_text:
                    choice = ""
                    for option in options:
                        if 'no' in option.lower():
                            choice = option
                    if choice == "":
                        choice = options[len(options) - 1]
                    self.select_dropdown(dropdown_field, choice)

                elif 'sponsor' in question_text:
                    answer = self.get_answer('requireVisa')
                    choice = ""
                    for option in options:
                        if answer == 'yes':
                            choice = option
                        else:
                            if 'no' in option.lower():
                                choice = option
                    if choice == "":
                        choice = options[len(options) - 1]
                    self.select_dropdown(dropdown_field, choice)

                elif 'above 18' in question_text.lower():  # Check for "above 18" in the question text
                    choice = ""
                    for option in options:
                        if 'yes' in option.lower():  # Select 'yes' option
                            choice = option
                    if choice == "":
                        choice = options[0]  # Default to the first option if 'yes' is not found
                    self.select_dropdown(dropdown_field, choice)

                elif 'currently living' in question_text or 'currently reside' in question_text:
                    answer = self.get_answer('residency')
                    choice = ""
                    for option in options:
                        if answer == 'yes':
                            choice = option
                        else:
                            if 'no' in option.lower():
                                choice = option
                    if choice == "":
                        choice = options[len(options) - 1]
                    self.select_dropdown(dropdown_field, choice)

                elif 'authorized' in question_text or 'authorised' in question_text:
                    answer = self.get_answer('legallyAuthorized')
                    choice = ""
                    for option in options:
                        if answer == 'yes':
                            # find some common words
                            choice = option
                        else:
                            if 'no' in option.lower():
                                choice = option
                    if choice == "":
                        choice = options[len(options) - 1]
                    self.select_dropdown(dropdown_field, choice)

                elif 'citizenship' in question_text:
                    answer = self.get_answer('legallyAuthorized')
                    choice = ""
                    for option in options:
                        if answer == 'yes':
                            if 'no' in option.lower():
                                choice = option
                    if choice == "":
                        choice = options[len(options) - 1]
                    self.select_dropdown(dropdown_field, choice)

                elif 'clearance' in question_text:
                    answer = self.get_answer('clearance')
                    choice = ""
                    for option in options:
                        if answer == 'yes':
                            choice = option
                        else:
                            if 'no' in option.lower():
                                choice = option
                    if choice == "":
                        choice = options[len(options) - 1]

                    self.select_dropdown(dropdown_field, choice)

                elif any(keyword in question_text.lower() for keyword in
                         [
                             'aboriginal', 'native', 'indigenous', 'tribe', 'first nations',
                             'native american', 'native hawaiian', 'inuit', 'metis', 'maori',
                             'aborigine', 'ancestral', 'native peoples', 'original people',
                             'first people', 'gender', 'race', 'disability', 'latino'
                         ]):
                    negative_keywords = ['prefer', 'decline', 'don\'t', 'specified', 'none']

                    choice = ""
                    choice = next((option for options in option.lower() if
                               any(neg_keyword in option.lower() for neg_keyword in negative_keywords)), None)

                    self.select_dropdown(dropdown_field, choice)

                elif 'email' in question_text:
                    continue  # assume email address is filled in properly by default

                elif 'experience' in question_text or 'understanding' in question_text or 'familiar' in question_text or 'comfortable' in question_text or 'able to' in question_text:
                    answer = 'no'
                    if self.experience_default > 0:
                        answer = 'yes'
                    else:
                        for experience in self.experience:
                            if experience.lower() in question_text and self.experience[experience] > 0:
                                answer = 'yes'
                                break
                    if answer == 'no':
                        # record unlisted experience as unprepared questions
                        self.record_unprepared_question("dropdown", question_text)

                    choice = ""
                    for option in options:
                        if answer in option.lower():
                            choice = option
                    if choice == "":
                        choice = options[len(options) - 1]
                    self.select_dropdown(dropdown_field, choice)

                else:
                    print(f"Unhandled dropdown question: {question_text}")
                    self.record_unprepared_question("dropdown", question_text)
                    self._save_unanswered_question("dropdown", question_text)

                    # 1. Check user-provided answer
                    user_ans = self.user_answers.get(question_text.strip().lower())
                    choice = options[len(options) - 1]  # safe default
                    if user_ans:
                        print(f"Using user-provided answer for dropdown: '{user_ans}'")
                        for option in options:
                            if user_ans.lower() in option.lower() or option.lower() in user_ans.lower():
                                choice = option
                                break
                    else:
                        # 2. Ask user via browser chat
                        chat_ans = self._ask_user_via_chat("dropdown", question_text, options=options)
                        if chat_ans:
                            for option in options:
                                if chat_ans.lower() in option.lower() or option.lower() in chat_ans.lower():
                                    choice = option
                                    break
                            if not choice:
                                choice = chat_ans  # use raw answer if no match found

                        # 3. Fall back to AI if chat timed out
                        if not choice:
                            choices = [(i, option) for i, option in enumerate(options)]
                            ai_response = self.ai_response_generator.generate_response(
                                question_text,
                                response_type="choice",
                                options=choices
                            )
                            if ai_response is not None:
                                choice = options[ai_response]
                            else:
                                choice = ""
                                for option in options:
                                    if 'yes' in option.lower():
                                        choice = option

                    print(f"Selected option: {choice}")
                    self.select_dropdown(dropdown_field, choice)
                continue
            except:
                print("An exception occurred while filling up dropdown field")  # TODO: Put logging behind debug flag

            # Checkbox check for agreeing to terms and service
            try:
                clickable_checkbox = question.find_element(By.TAG_NAME, 'label')
                clickable_checkbox.click()
            except:
                print("An exception occurred while filling up checkbox field")  # TODO: Put logging behind debug flag

    def unfollow(self):
        try:
            follow_checkbox = self.browser.find_element(By.XPATH,
                                                        "//label[contains(.,\'to stay up to date with their page.\')]").click()
            follow_checkbox.click()
        except:
            pass

    def send_resume(self):
        self._log("Form section: RESUME UPLOAD", "STEP")
        try:
            file_upload_elements = (By.CSS_SELECTOR, "input[name='file']")
            if len(self.browser.find_elements(file_upload_elements[0], file_upload_elements[1])) > 0:
                input_buttons = self.browser.find_elements(file_upload_elements[0], file_upload_elements[1])
                if len(input_buttons) == 0:
                    raise Exception("No input elements found in element")
                for upload_button in input_buttons:
                    upload_type = upload_button.find_element(By.XPATH, "..").find_element(By.XPATH,
                                                                                          "preceding-sibling::*")
                    if 'resume' in upload_type.text.lower():
                        self._log(f"Uploading resume: {self.resume_dir}", "STEP")
                        upload_button.send_keys(self.resume_dir)
                        self._log("Resume uploaded.", "OK")
                    elif 'cover' in upload_type.text.lower():
                        if self.cover_letter_dir != '':
                            self._log(f"Uploading cover letter: {self.cover_letter_dir}", "STEP")
                            upload_button.send_keys(self.cover_letter_dir)
                            self._log("Cover letter uploaded.", "OK")
                        elif 'required' in upload_type.text.lower():
                            self._log("Cover letter required but not configured — uploading resume instead.", "WARN")
                            upload_button.send_keys(self.resume_dir)
        except:
            self._log("Failed to upload resume or cover letter!", "FAIL")
            pass

    def enter_text(self, element, text):
        element.clear()
        element.send_keys(text)

    def select_dropdown(self, element, text):
        select = Select(element)
        select.select_by_visible_text(text)

    # Radio Select
    def radio_select(self, element, label_text, clickLast=False):
        label = element.find_element(By.TAG_NAME, 'label')
        if label_text in label.text.lower() or clickLast == True:
            label.click()

    # Contact info fill-up
    def contact_info(self, form):
        self._log("Form section: CONTACT INFO", "STEP")

        # ── Phone country code ──────────────────────────────────────────────────
        try:
            # Use RELATIVE xpath (.// = scoped to this form element)
            country_code_picker = form.find_element(
                By.XPATH, './/select[contains(@id,"phoneNumber") and contains(@id,"country")]'
            )
            self.select_dropdown(country_code_picker, self.personal_info['Phone Country Code'])
            self._log(f"Phone country code set to '{self.personal_info['Phone Country Code']}'", "STEP")
        except Exception as e:
            self._log(f"Could not set phone country code: {e}", "WARN")

        # ── Phone number ────────────────────────────────────────────────────────
        try:
            phone_number_field = form.find_element(
                By.XPATH, './/input[contains(@id,"phoneNumber") and contains(@id,"nationalNumber")]'
            )
            phone_number_field.clear()
            self.enter_text(phone_number_field, self.personal_info['Mobile Phone Number'])
            self._log(f"Phone number entered.", "STEP")
        except Exception:
            # Fallback: find any visible phone input that isn't already filled
            try:
                for inp in form.find_elements(By.XPATH, './/input[@type="tel" or contains(@id,"phone")]'):
                    if not inp.get_attribute('value'):
                        inp.clear()
                        self.enter_text(inp, self.personal_info['Mobile Phone Number'])
                        self._log("Phone number entered via fallback tel input.", "STEP")
                        break
            except Exception as e2:
                self._log(f"Could not enter phone number: {e2}", "WARN")

        # ── Label-based fallback loop (email + any remaining fields) ───────────
        try:
            for el in form.find_elements(By.TAG_NAME, 'label'):
                text = el.text.lower()
                if 'email address' in text:
                    continue  # LinkedIn pre-fills email
                # (phone already handled above)
        except Exception as e:
            self._log(f"contact_info label loop error: {e}", "WARN")

    def fill_up(self):
        # Honour pause before processing each form page
        self._wait_if_paused()
        try:
            # LinkedIn obfuscates class names — use role=dialog + form tag instead
            # Try multiple selectors for the modal content area
            modal = None
            for sel in [
                'div[role="dialog"]',
                '.jobs-easy-apply-modal',
                '.artdeco-modal',
                '.jobs-easy-apply-modal__content',
            ]:
                try:
                    modal = self.browser.find_element(By.CSS_SELECTOR, sel)
                    if modal:
                        break
                except:
                    pass

            if not modal:
                self._log("Could not find Easy Apply modal dialog.", "WARN")
                return

            # Find the form inside the modal
            try:
                form = modal.find_element(By.TAG_NAME, 'form')
            except:
                self._log("No form found inside modal.", "WARN")
                return

            try:
                label = form.find_element(By.TAG_NAME, 'h3').text.lower()
                self._log(f"Form section header: '{label}'", "STEP")
                if 'home address' in label:
                    self._log("Form section: HOME ADDRESS", "STEP")
                    self.home_address(form)
                elif 'contact info' in label:
                    self.contact_info(form)
                elif 'resume' in label:
                    self.send_resume()
                else:
                    self._log(f"Form section: ADDITIONAL QUESTIONS", "STEP")
                    self.additional_questions(form)
            except Exception as e:
                self._log(f"Exception while filling form section: {e}", "WARN")
                traceback.print_exc()
        except Exception as e:
            self._log(f"fill_up outer exception: {e}", "WARN")
            traceback.print_exc()

    def write_to_file(self, company, job_title, link, location, search_location):
        to_write = [company, job_title, link, location, search_location, datetime.now()]
        file_path = self.file_name + ".csv"
        print(f'updated {file_path}.')

        with open(file_path, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(to_write)

    def write_external_to_file(self, company, job_title, link, location, search_location, status="Externally Applied"):
        """Log an externally-applied job to external_applied.csv."""
        file_path = self.external_file_name + ".csv"
        file_exists = os.path.exists(file_path)
        to_write = {
            'company': company,
            'job_title': job_title,
            'link': link,
            'location': location,
            'search_location': search_location,
            'status': status,
            'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        with open(file_path, 'a', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=to_write.keys())
            if not file_exists:
                writer.writeheader()
            writer.writerow(to_write)
        print(f'Updated {file_path} with external application: {job_title} @ {company}.')

    def record_unprepared_question(self, answer_type, question_text):
        to_write = [answer_type, question_text]
        file_path = self.unprepared_questions_file_name + ".csv"

        try:
            with open(file_path, 'a') as f:
                writer = csv.writer(f)
                writer.writerow(to_write)
                print(f'Updated {file_path} with {to_write}.')
        except:
            print(
                "Special characters in questions are not allowed. Failed to update unprepared questions log.")
            print(question_text)

    # ── Browser chat helpers ──────────────────────────────────────────────────

    def _inject_chat_panel(self):
        """
        Inject the bot control panel directly into the current LinkedIn page.
        Uses inline JS/CSS so it works regardless of LinkedIn's CSP.
        Skips injection if the panel is already present on the page.
        """
        SERVER = f"http://127.0.0.1:{_chat_server.SERVER_PORT}"
        js = r"""
(function(){
  var S='http://127.0.0.1:5199';
  if(document.getElementById('agb-root')) return;

  /* ---- CSS ---- */
  var style=document.createElement('style');
  style.id='agb-style';
  style.textContent=`
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
  #agb-root *{box-sizing:border-box;margin:0;padding:0;font-family:'Inter',system-ui,sans-serif;}
  #agb-root{
    position:fixed;bottom:20px;left:20px;width:370px;
    background:#13151f;border:1px solid #2a2d44;border-radius:14px;
    box-shadow:0 24px 60px rgba(0,0,0,.75);z-index:2147483647;
    display:flex;flex-direction:column;overflow:hidden;
    transition:height .3s cubic-bezier(.4,0,.2,1);
    height:560px;
  }
  #agb-root.agb-collapsed{height:56px;}

  /* header */
  #agb-hdr{
    display:flex;align-items:center;gap:9px;padding:0 12px;
    height:56px;background:linear-gradient(135deg,#14162a,#1c1f35);
    border-bottom:1px solid #2a2d44;flex-shrink:0;cursor:pointer;
    user-select:none;
  }
  #agb-avatar{
    width:34px;height:34px;border-radius:50%;
    background:linear-gradient(135deg,#6366f1,#8b5cf6);
    display:flex;align-items:center;justify-content:center;
    font-size:17px;flex-shrink:0;
  }
  #agb-hinfo{flex:1;min-width:0;}
  #agb-hinfo h3{font-size:12.5px;font-weight:700;color:#e2e8f0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
  #agb-badge{display:flex;align-items:center;gap:4px;font-size:11px;font-weight:600;margin-top:1px;}
  .agb-sdot{width:7px;height:7px;border-radius:50%;flex-shrink:0;transition:background .3s;}

  /* control buttons */
  .agb-ctrl{
    display:flex;align-items:center;gap:5px;
    padding:6px 10px;border-radius:7px;border:none;
    font-size:11px;font-weight:700;cursor:pointer;
    transition:opacity .15s,transform .1s;flex-shrink:0;
    white-space:nowrap;
  }
  .agb-ctrl:hover{transform:translateY(-1px);opacity:.9;}
  .agb-ctrl:disabled{opacity:.4;cursor:default;transform:none;}
  .agb-ctrl svg{width:12px;height:12px;fill:currentColor;}
  #agb-pause-btn{background:linear-gradient(135deg,#f59e0b,#d97706);color:#1a0800;}
  #agb-resume-btn{background:linear-gradient(135deg,#22c55e,#16a34a);color:#001a08;}
  #agb-stop-btn{background:linear-gradient(135deg,#ef4444,#dc2626);color:#fff;}
  #agb-restart-btn{background:linear-gradient(135deg,#6366f1,#8b5cf6);color:#fff;}
  #agb-collapse-btn{
    background:none;border:none;cursor:pointer;color:#475569;
    padding:5px;border-radius:5px;display:flex;align-items:center;
    transition:color .15s,transform .3s;flex-shrink:0;
  }
  #agb-collapse-btn:hover{color:#e2e8f0;}
  #agb-root.agb-collapsed #agb-collapse-btn{transform:rotate(180deg);}

  /* body */
  #agb-body{flex:1;display:flex;flex-direction:column;overflow:hidden;}

  /* paused banner */
  #agb-banner{
    display:none;padding:8px 13px;
    background:linear-gradient(135deg,rgba(245,158,11,.14),rgba(245,158,11,.05));
    border-bottom:1px solid rgba(245,158,11,.25);
    font-size:11.5px;color:#fbbf24;flex-shrink:0;
  }
  #agb-banner.agb-visible{display:block;}
  #agb-banner strong{display:block;margin-bottom:2px;font-size:12px;}

  /* stopped banner */
  #agb-stop-banner{
    display:none;padding:8px 13px;
    background:linear-gradient(135deg,rgba(239,68,68,.14),rgba(239,68,68,.05));
    border-bottom:1px solid rgba(239,68,68,.25);
    font-size:11.5px;color:#fca5a5;flex-shrink:0;
  }
  #agb-stop-banner.agb-visible{display:block;}
  #agb-stop-banner strong{display:block;margin-bottom:2px;font-size:12px;}

  /* tabs */
  .agb-tabs{display:flex;flex-shrink:0;background:#1a1d2e;border-bottom:1px solid #2a2d44;}
  .agb-tab{
    flex:1;padding:8px 0;background:none;border:none;cursor:pointer;
    font-size:11.5px;font-weight:600;color:#475569;
    border-bottom:2px solid transparent;transition:color .15s,border-color .15s;
    display:flex;align-items:center;justify-content:center;gap:4px;
  }
  .agb-tab.agb-active{color:#6366f1;border-bottom-color:#6366f1;}
  .agb-tab:hover:not(.agb-active){color:#e2e8f0;}
  .agb-tbadge{
    background:#ef4444;color:#fff;font-size:10px;font-weight:700;
    padding:1px 5px;border-radius:10px;display:none;
  }
  .agb-tbadge.agb-visible{display:inline-block;}

  /* panes */
  .agb-pane{display:none;flex:1;flex-direction:column;overflow:hidden;}
  .agb-pane.agb-active{display:flex;}

  /* log */
  #agb-log{
    flex:1;overflow-y:auto;padding:6px 0;
    font-family:'JetBrains Mono',monospace;font-size:11px;line-height:1.6;
  }
  #agb-log::-webkit-scrollbar{width:3px;}
  #agb-log::-webkit-scrollbar-thumb{background:#2a2d44;border-radius:99px;}
  .agb-lr{
    display:flex;gap:7px;align-items:flex-start;
    padding:1px 10px;border-left:3px solid transparent;
  }
  .agb-lr:hover{background:rgba(255,255,255,.02);}
  .agb-lt{color:#475569;flex-shrink:0;font-size:10px;padding-top:1px;}
  .agb-lm{flex:1;color:#94a3b8;word-break:break-all;white-space:pre-wrap;}
  .agb-lr.OK  {border-left-color:#22c55e;} .agb-lr.OK   .agb-lm{color:#86efac;}
  .agb-lr.WARN{border-left-color:#f59e0b;} .agb-lr.WARN .agb-lm{color:#fcd34d;}
  .agb-lr.FAIL{border-left-color:#ef4444;} .agb-lr.FAIL .agb-lm{color:#fca5a5;}
  .agb-lr.SKIP{border-left-color:#475569;} .agb-lr.SKIP .agb-lm{color:#475569;}
  .agb-lr.STEP{border-left-color:#38bdf8;} .agb-lr.STEP .agb-lm{color:#7dd3fc;}
  .agb-log-tb{
    display:flex;align-items:center;justify-content:space-between;
    padding:4px 10px;border-top:1px solid #2a2d44;background:#1a1d2e;flex-shrink:0;
  }
  .agb-log-tb span{font-size:10.5px;color:#475569;}
  .agb-log-tb button{
    background:none;border:1px solid #2a2d44;color:#475569;
    font-size:10px;padding:2px 7px;border-radius:4px;cursor:pointer;
    transition:color .15s,border-color .15s;font-family:'Inter',sans-serif;
  }
  .agb-log-tb button:hover{color:#e2e8f0;border-color:#6366f1;}
  .agb-log-tb button.on{color:#22c55e;border-color:#22c55e;}

  /* chat */
  #agb-msgs{
    flex:1;overflow-y:auto;padding:10px;
    display:flex;flex-direction:column;gap:9px;scroll-behavior:smooth;
  }
  #agb-msgs::-webkit-scrollbar{width:3px;}
  #agb-msgs::-webkit-scrollbar-thumb{background:#2a2d44;border-radius:99px;}
  .agb-msg{display:flex;gap:7px;max-width:100%;animation:agbIn .2s ease;}
  @keyframes agbIn{from{opacity:0;transform:translateY(5px)}to{opacity:1;transform:none}}
  .agb-msg.bot {align-self:flex-start;}
  .agb-msg.usr {align-self:flex-end;flex-direction:row-reverse;}
  .agb-msg.sys {align-self:center;}
  .agb-av{
    width:26px;height:26px;border-radius:50%;flex-shrink:0;
    background:linear-gradient(135deg,#6366f1,#8b5cf6);
    display:flex;align-items:center;justify-content:center;
    font-size:12px;margin-top:2px;
  }
  .agb-msg.usr .agb-av{background:#222538;}
  .agb-bbl{
    padding:8px 12px;border-radius:12px;
    font-size:12.5px;line-height:1.5;max-width:260px;word-break:break-word;
    color:#e2e8f0;
  }
  .agb-msg.bot .agb-bbl{background:#222538;border-bottom-left-radius:3px;}
  .agb-msg.usr .agb-bbl{background:linear-gradient(135deg,#6366f1,#8b5cf6);border-bottom-right-radius:3px;color:#fff;}
  .agb-msg.sys .agb-bbl{
    background:rgba(245,158,11,.1);border:1px solid rgba(245,158,11,.2);
    color:#fcd34d;font-size:11px;border-radius:7px;text-align:center;
  }
  #agb-typing{display:none;align-items:center;gap:7px;padding:2px 0;}
  #agb-typing.agb-visible{display:flex;}
  .agb-dots span{
    display:inline-block;width:5px;height:5px;border-radius:50%;
    background:#475569;margin:0 1px;
    animation:agbB .8s ease-in-out infinite;
  }
  .agb-dots span:nth-child(2){animation-delay:.15s}
  .agb-dots span:nth-child(3){animation-delay:.3s}
  @keyframes agbB{0%,80%,100%{transform:translateY(0)}40%{transform:translateY(-5px)}}
  #agb-opts{padding:0 10px 7px;display:flex;flex-wrap:wrap;gap:5px;}
  .agb-opt{
    padding:5px 11px;border-radius:16px;
    border:1px solid #2a2d44;background:#222538;
    color:#e2e8f0;font-size:11.5px;cursor:pointer;
    transition:border-color .15s,background .15s;
  }
  .agb-opt:hover{border-color:#6366f1;background:rgba(99,102,241,.1);}
  .agb-foot{
    padding:9px 10px;border-top:1px solid #2a2d44;background:#13151f;
    display:flex;gap:7px;align-items:flex-end;flex-shrink:0;
  }
  #agb-inp{
    flex:1;background:#222538;border:1px solid #2a2d44;border-radius:8px;
    color:#e2e8f0;font-size:12.5px;padding:8px 11px;resize:none;
    min-height:36px;max-height:80px;outline:none;
    transition:border-color .15s;line-height:1.4;
  }
  #agb-inp:focus{border-color:#6366f1;}
  #agb-inp::placeholder{color:#475569;}
  #agb-send{
    width:36px;height:36px;flex-shrink:0;border-radius:8px;
    background:linear-gradient(135deg,#6366f1,#8b5cf6);
    border:none;cursor:pointer;display:flex;align-items:center;justify-content:center;
    transition:opacity .15s,transform .1s;
  }
  #agb-send:hover{transform:translateY(-1px);}
  #agb-send:disabled{opacity:.4;cursor:default;transform:none;}
  #agb-send svg{width:15px;height:15px;fill:#fff;}
  `;
  document.head.appendChild(style);

  /* ---- HTML ---- */
  var root=document.createElement('div');
  root.id='agb-root';
  root.innerHTML=`
  <div id="agb-hdr">
    <div id="agb-avatar">🤖</div>
    <div id="agb-hinfo">
      <h3>EasyApply Bot</h3>
      <div id="agb-badge">
        <span class="agb-sdot" id="agb-sdot"></span>
        <span id="agb-slabel">Connecting...</span>
      </div>
    </div>
    <button class="agb-ctrl" id="agb-pause-btn" title="Pause bot">
      <svg viewBox="0 0 24 24"><path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/></svg>Pause
    </button>
    <button class="agb-ctrl" id="agb-resume-btn" title="Resume bot" style="display:none">
      <svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>Resume
    </button>
    <button class="agb-ctrl" id="agb-stop-btn" title="Stop bot">
      <svg viewBox="0 0 24 24"><path d="M6 6h12v12H6z"/></svg>Stop
    </button>
    <button class="agb-ctrl" id="agb-restart-btn" title="Restart bot" style="display:none">
      <svg viewBox="0 0 24 24"><path d="M17.65 6.35A7.96 7.96 0 0012 4C7.58 4 4 7.58 4 12s3.58 8 8 8c3.73 0 6.84-2.55 7.73-6h-2.08A5.99 5.99 0 0112 18c-3.31 0-6-2.69-6-6s2.69-6 6-6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z"/></svg>Restart
    </button>
    <button id="agb-collapse-btn" title="Collapse">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M7.41 15.41L12 10.83l4.59 4.58L18 14l-6-6-6 6z"/></svg>
    </button>
  </div>
  <div id="agb-body">
    <div id="agb-banner"><strong>⏸ Bot paused — fill the form manually</strong>Click Resume when done.</div>
    <div id="agb-stop-banner"><strong>⏹ Bot stopped</strong>Click Restart to resume applying.</div>
    <div class="agb-tabs">
      <button class="agb-tab agb-active" data-tab="log">📋 Activity Log</button>
      <button class="agb-tab" data-tab="chat">💬 Chat <span class="agb-tbadge" id="agb-cbadge">!</span></button>
    </div>
    <div class="agb-pane agb-active" id="agb-pane-log">
      <div id="agb-log"></div>
      <div class="agb-log-tb">
        <span id="agb-lcount">0 entries</span>
        <div style="display:flex;gap:5px">
          <button id="agb-clear">Clear</button>
          <button id="agb-ascroll" class="on">Auto ✓</button>
        </div>
      </div>
    </div>
    <div class="agb-pane" id="agb-pane-chat">
      <div id="agb-msgs">
        <div class="agb-msg bot"><div class="agb-av">🤖</div>
          <div class="agb-bbl">👋 I'm your <strong>EasyApply Bot</strong>.<br>Watch the log, use buttons to control me, and I'll ask here when I need help!</div></div>
      </div>
      <div id="agb-typing"><div class="agb-av" style="width:26px;height:26px;font-size:12px;">🤖</div>
        <div class="agb-dots"><span></span><span></span><span></span></div></div>
      <div id="agb-opts"></div>
      <div class="agb-foot">
        <textarea id="agb-inp" placeholder="Type your answer..." rows="1"></textarea>
        <button id="agb-send" disabled><svg viewBox="0 0 24 24"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg></button>
      </div>
    </div>
  </div>`;
  document.body.appendChild(root);

  /* ---- State ---- */
  var collapsed=false, botPaused=false, botStopped=false,
      awaitingAnswer=false, currentQId=null, lastLogIdx=-1,
      autoScroll=true, totalLogs=0, unreadChat=0, activeTab='log';

  /* ---- Refs ---- */
  var el=function(id){return document.getElementById(id);};
  var pauseBtn=el('agb-pause-btn'), resumeBtn=el('agb-resume-btn'),
      stopBtn=el('agb-stop-btn'), restartBtn=el('agb-restart-btn'),
      collapseBtn=el('agb-collapse-btn'), sdot=el('agb-sdot'),
      slabel=el('agb-slabel'), banner=el('agb-banner'),
      stopBanner=el('agb-stop-banner'), logArea=el('agb-log'),
      lcount=el('agb-lcount'), clearBtn=el('agb-clear'),
      ascrollBtn=el('agb-ascroll'), msgs=el('agb-msgs'),
      typing=el('agb-typing'), opts=el('agb-opts'),
      inp=el('agb-inp'), sendBtn=el('agb-send'), cbadge=el('agb-cbadge');

  /* ---- Collapse ---- */
  el('agb-hdr').addEventListener('click',function(e){
    if([pauseBtn,resumeBtn,stopBtn,restartBtn,collapseBtn].some(function(b){return b.contains(e.target);})) return;
    collapsed=!collapsed;
    root.classList.toggle('agb-collapsed',collapsed);
  });
  collapseBtn.addEventListener('click',function(e){
    e.stopPropagation();
    collapsed=!collapsed;
    root.classList.toggle('agb-collapsed',collapsed);
  });

  /* ---- Tabs ---- */
  document.querySelectorAll('.agb-tab').forEach(function(b){
    b.addEventListener('click',function(){
      var tab=b.dataset.tab; activeTab=tab;
      document.querySelectorAll('.agb-tab').forEach(function(x){x.classList.toggle('agb-active',x.dataset.tab===tab);});
      document.querySelectorAll('.agb-pane').forEach(function(x){x.classList.toggle('agb-active',x.id==='agb-pane-'+tab);});
      if(tab==='chat'){unreadChat=0;cbadge.classList.remove('agb-visible');}
      if(tab==='log'&&autoScroll) logArea.scrollTop=logArea.scrollHeight;
    });
  });

  /* ---- Status badge ---- */
  function updateBadge(paused,stopped,reachable){
    pauseBtn.disabled=resumeBtn.disabled=stopBtn.disabled=restartBtn.disabled=false;
    if(!reachable){
      sdot.style.background='#ef4444'; slabel.textContent='Offline'; slabel.style.color='#ef4444';
      [pauseBtn,resumeBtn,stopBtn,restartBtn].forEach(function(b){b.disabled=true;});
      return;
    }
    if(stopped){
      sdot.style.background='#ef4444'; slabel.textContent='⏹ Stopped'; slabel.style.color='#ef4444';
      pauseBtn.style.display='none'; resumeBtn.style.display='none';
      stopBtn.style.display='none';   restartBtn.style.display='';
      banner.classList.remove('agb-visible'); stopBanner.classList.add('agb-visible');
    } else if(paused){
      sdot.style.background='#f59e0b'; slabel.textContent='⏸ Paused'; slabel.style.color='#f59e0b';
      pauseBtn.style.display='none';   resumeBtn.style.display='';
      stopBtn.style.display='';        restartBtn.style.display='none';
      banner.classList.add('agb-visible'); stopBanner.classList.remove('agb-visible');
    } else {
      sdot.style.background='#22c55e'; slabel.textContent='▶ Running'; slabel.style.color='#22c55e';
      pauseBtn.style.display='';       resumeBtn.style.display='none';
      stopBtn.style.display='';        restartBtn.style.display='none';
      banner.classList.remove('agb-visible'); stopBanner.classList.remove('agb-visible');
    }
  }

  /* ---- Control buttons ---- */
  function ctrlPost(endpoint){
    fetch(S+endpoint,{method:'POST'}).catch(function(){});
  }
  pauseBtn.addEventListener('click',  function(e){e.stopPropagation();ctrlPost('/pause');});
  resumeBtn.addEventListener('click', function(e){e.stopPropagation();ctrlPost('/resume');});
  stopBtn.addEventListener('click',   function(e){e.stopPropagation();ctrlPost('/stop');});
  restartBtn.addEventListener('click',function(e){e.stopPropagation();ctrlPost('/restart');});

  /* ---- Log ---- */
  function appendLog(e){
    var row=document.createElement('div');
    row.className='agb-lr '+(e.level||'INFO');
    var ts=document.createElement('span'); ts.className='agb-lt'; ts.textContent=e.ts;
    var msg=document.createElement('span'); msg.className='agb-lm'; msg.textContent=e.msg;
    row.appendChild(ts); row.appendChild(msg);
    logArea.appendChild(row);
    totalLogs++; lcount.textContent=totalLogs+' entries';
    if(autoScroll) logArea.scrollTop=logArea.scrollHeight;
  }
  ascrollBtn.addEventListener('click',function(e){
    e.stopPropagation();
    autoScroll=!autoScroll;
    ascrollBtn.textContent=autoScroll?'Auto ✓':'Auto';
    ascrollBtn.classList.toggle('on',autoScroll);
    if(autoScroll) logArea.scrollTop=logArea.scrollHeight;
  });
  clearBtn.addEventListener('click',function(e){
    e.stopPropagation();
    logArea.innerHTML=''; totalLogs=0; lcount.textContent='0 entries';
  });

  /* ---- Chat ---- */
  function addMsg(text,role){
    var wrap=document.createElement('div'); wrap.className='agb-msg '+role;
    var av=document.createElement('div'); av.className='agb-av';
    av.textContent=role==='bot'?'🤖':role==='usr'?'🧑':'';
    var bbl=document.createElement('div'); bbl.className='agb-bbl';
    bbl.innerHTML=text.replace(/\n/g,'<br>');
    if(role!=='sys') wrap.appendChild(av);
    wrap.appendChild(bbl); msgs.appendChild(wrap);
    msgs.scrollTop=msgs.scrollHeight;
    if(activeTab!=='chat'&&role!=='usr'){
      unreadChat++; cbadge.textContent=unreadChat>9?'9+':unreadChat;
      cbadge.classList.add('agb-visible');
      if(collapsed){collapsed=false;root.classList.remove('agb-collapsed');}
    }
  }
  function renderOpts(list){
    opts.innerHTML='';
    (list||[]).forEach(function(o){
      var b=document.createElement('button'); b.className='agb-opt'; b.textContent=o;
      b.addEventListener('click',function(){sendAns(o);});
      opts.appendChild(b);
    });
  }
  async function sendAns(text){
    if(!text||!awaitingAnswer) return;
    awaitingAnswer=false;
    addMsg(text,'usr'); opts.innerHTML='';
    inp.value=''; inp.style.height='auto'; sendBtn.disabled=true;
    try{
      await fetch(S+'/answer',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({answer:text})});
      addMsg('✅ Got it! Saved for next time.','bot'); currentQId=null;
    }catch(e){addMsg('❌ Could not reach bot server.','bot');}
  }
  inp.addEventListener('input',function(){
    sendBtn.disabled=inp.value.trim()===''||!awaitingAnswer;
    inp.style.height='auto'; inp.style.height=Math.min(inp.scrollHeight,80)+'px';
  });
  inp.addEventListener('keydown',function(e){
    if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();if(!sendBtn.disabled)sendAns(inp.value.trim());}
  });
  sendBtn.addEventListener('click',function(){sendAns(inp.value.trim());});

  /* ---- Polling ---- */
  async function pollStatus(){
    try{
      var r=await fetch(S+'/status',{cache:'no-store'});
      var d=await r.json();
      var wasPaused=botPaused, wasStopped=botStopped;
      botPaused=d.paused; botStopped=d.stopped;
      updateBadge(botPaused,botStopped,true);
      if(!wasPaused&&botPaused) addMsg('⏸ <strong>Bot paused.</strong> Fill the form manually, then click Resume.','sys');
      if(wasPaused&&!botPaused&&!botStopped) addMsg('▶ <strong>Bot resumed.</strong> Continuing...','sys');
      if(!wasStopped&&botStopped) addMsg('⏹ <strong>Bot stopped.</strong> Click Restart to continue.','sys');
      if(wasStopped&&!botStopped) addMsg('🔄 <strong>Bot restarted.</strong> Continuing...','sys');
    }catch(e){updateBadge(false,false,false);}
  }
  async function pollLogs(){
    try{
      var r=await fetch(S+'/logs?since='+lastLogIdx,{cache:'no-store'});
      var d=await r.json();
      (d.logs||[]).forEach(function(e){appendLog(e);if(e.i>lastLogIdx)lastLogIdx=e.i;});
    }catch(e){}
  }
  async function pollQ(){
    try{
      var r=await fetch(S+'/question',{cache:'no-store'});
      var d=await r.json();
      if(d&&d.id&&d.id!==currentQId){
        currentQId=d.id; awaitingAnswer=true;
        if(activeTab!=='chat') document.querySelector('[data-tab="chat"]').click();
        if(collapsed){collapsed=false;root.classList.remove('agb-collapsed');}
        typing.classList.add('agb-visible'); msgs.scrollTop=msgs.scrollHeight;
        await new Promise(function(res){setTimeout(res,600);});
        typing.classList.remove('agb-visible');
        var tl=d.type?'['+d.type.toUpperCase()+'] ':'';
        addMsg('❓ <strong>'+tl+d.question+'</strong>','bot');
        if(d.options&&d.options.length){addMsg('Pick an option or type a custom answer:','bot');renderOpts(d.options);}
        else addMsg('Type your answer and press <strong>Enter</strong>.','bot');
        sendBtn.disabled=false; inp.focus();
      }
    }catch(e){}
  }
  pollStatus(); pollLogs(); pollQ();
  setInterval(pollStatus,1500);
  setInterval(pollLogs,600);
  setInterval(pollQ,1500);
})();
"""
        try:
            self.browser.execute_script(js)
            print("[ChatPanel] Panel injected into page.")
        except Exception as e:
            print(f"[ChatPanel] Could not inject panel: {e}")


        """
        Post a question to the browser chat overlay and block until the user
        replies (or the server times out).  The answer is persisted to
        unanswered_question.csv so the bot will use it on future runs without
        asking again.

        Returns the user's answer string, or None on timeout/error.
        """
        question_id = str(uuid.uuid4())
        payload = {
            "id":       question_id,
            "question": question_text,
            "type":     answer_type,
            "options":  options or []
        }
        try:
            _requests.post(
                f"http://127.0.0.1:{_chat_server.SERVER_PORT}/question",
                json=payload,
                timeout=5
            )
            print(f"[Chat] Waiting for user to answer [{answer_type}]: {question_text}")
        except Exception as e:
            print(f"[Chat] Could not post question to chat server: {e}")
            return None

        # Block until the server gets the answer (server has its own 180-s timeout)
        try:
            resp = _requests.get(
                f"http://127.0.0.1:{_chat_server.SERVER_PORT}/answer",
                timeout=200   # slightly above server POLL_TIMEOUT
            )
            answer = resp.json().get("answer")
        except Exception as e:
            print(f"[Chat] Error waiting for answer: {e}")
            return None

        if answer:
            print(f"[Chat] User answered [{answer_type}]: '{answer}'")
            # Persist so the bot reuses this answer without asking again
            self._persist_chat_answer(answer_type, question_text, answer)
        else:
            print("[Chat] No answer received (timeout). Falling back to default.")
        return answer

    def _wait_if_paused(self):
        """
        Block the bot until the user clicks Resume in the browser chat.
        Calls chat_server.wait_if_paused() which blocks on a threading.Event.
        Safe to call from any thread — returns immediately when not paused.
        """
        try:
            _chat_server.wait_if_paused()
        except Exception as e:
            print(f"[Chat] _wait_if_paused error: {e}")

    def _persist_chat_answer(self, answer_type, question_text, answer):
        """
        Write the chat-supplied answer back into unanswered_question.csv so the
        bot can use it on the next run without prompting the user again.
        Also updates the in-memory user_answers dict immediately.
        """
        file_path = self.unanswered_questions_file_name + ".csv"
        q_key = question_text.strip().lower()

        # Update in-memory cache right away
        self.user_answers[q_key] = answer

        # Read existing rows, update or append
        rows = []
        fieldnames = ["answer_type", "question_text", "user_answer"]
        found = False
        if os.path.exists(file_path):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        if row.get("question_text", "").strip().lower() == q_key:
                            row["user_answer"] = answer
                            found = True
                        rows.append(row)
            except Exception as e:
                print(f"[Chat] Could not read {file_path}: {e}")

        if not found:
            rows.append({"answer_type": answer_type, "question_text": question_text, "user_answer": answer})

        try:
            with open(file_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)
            print(f"[Chat] Saved answer to {file_path}")
        except Exception as e:
            print(f"[Chat] Could not save answer: {e}")

    def _save_unanswered_question(self, answer_type, question_text):
        """
        Save a question the bot could not answer to unanswered_question.csv.
        The user can open the file, fill in the 'user_answer' column, and on the
        next run the bot will use those answers instead of falling back to AI/defaults.
        Already-recorded questions are NOT duplicated.
        """
        file_path = self.unanswered_questions_file_name + ".csv"
        q_key = question_text.strip().lower()

        # Don't duplicate entries that are already in the file
        existing = set()
        if os.path.exists(file_path):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        existing.add(row.get('question_text', '').strip().lower())
            except Exception:
                pass

        if q_key in existing:
            return  # already recorded, nothing to do

        try:
            file_exists = os.path.exists(file_path)
            with open(file_path, 'a', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=['answer_type', 'question_text', 'user_answer'])
                if not file_exists:
                    writer.writeheader()  # write header only once
                writer.writerow({
                    'answer_type': answer_type,
                    'question_text': question_text,
                    'user_answer': ''  # user fills this column manually
                })
            print(f"Saved unanswered question to {file_path}: [{answer_type}] {question_text}")
        except Exception as e:
            print(f"Could not save to {file_path}: {e}")

    def _load_user_answers(self):
        """
        Load answers the user filled in manually inside unanswered_question.csv.
        Returns a dict keyed by lowercased question_text → answer string.
        Only entries where user_answer is non-empty are included.
        """
        answers = {}
        file_path = self.unanswered_questions_file_name + ".csv"
        if not os.path.exists(file_path):
            return answers
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    q_text = row.get('question_text', '').strip().lower()
                    user_answer = row.get('user_answer', '').strip()
                    if q_text and user_answer:  # only load rows where user typed an answer
                        answers[q_text] = user_answer
            print(f"Loaded {len(answers)} user-provided answer(s) from {file_path}.")
        except Exception as e:
            print(f"Could not load user answers from {file_path}: {e}")
        return answers

    def scroll_slow(self, scrollable_element, start=0, end=3600, step=100, reverse=False):
        if reverse:
            start, end = end, start
            step = -step

        for i in range(start, end, step):
            self.browser.execute_script("arguments[0].scrollTo(0, {})".format(i), scrollable_element)
            time.sleep(random.uniform(0.1, .6))

    def avoid_lock(self):
        if self.disable_lock:
            return

        pyautogui.keyDown('ctrl')
        pyautogui.press('esc')
        pyautogui.keyUp('ctrl')
        time.sleep(1.0)
        pyautogui.press('esc')

    def get_base_search_url(self, parameters):
        remote_url = ""
        lessthanTenApplicants_url = ""
        newestPostingsFirst_url = ""

        if parameters.get('remote'):
            remote_url = "&f_WT=2"
        else:
            remote_url = ""
            # TO DO: Others &f_WT= options { WT=1 onsite, WT=2 remote, WT=3 hybrid, f_WT=1%2C2%2C3 }

        if parameters['lessthanTenApplicants']:
            lessthanTenApplicants_url = "&f_EA=true"

        if parameters['newestPostingsFirst']:
            newestPostingsFirst_url += "&sortBy=DD"

        level = 1
        experience_level = parameters.get('experienceLevel', [])
        experience_url = "f_E="
        for key in experience_level.keys():
            if experience_level[key]:
                experience_url += "%2C" + str(level)
            level += 1

        distance_url = "?distance=" + str(parameters['distance'])

        job_types_url = "f_JT="
        job_types = parameters.get('jobTypes', [])
        # job_types = parameters.get('experienceLevel', [])
        for key in job_types:
            if job_types[key]:
                job_types_url += "%2C" + key[0].upper()

        date_url = ""
        dates = {"all time": "", "month": "&f_TPR=r2592000", "week": "&f_TPR=r604800", "24 hours": "&f_TPR=r86400"}
        date_table = parameters.get('date', [])
        for key in date_table.keys():
            if date_table[key]:
                date_url = dates[key]
                break

        easy_apply_url = "&f_AL=true"

        extra_search_terms = [distance_url, remote_url, lessthanTenApplicants_url, newestPostingsFirst_url, job_types_url, experience_url]
        # Store base (no Easy Apply filter) separately so we can switch mid-session
        self._base_search_url_no_filter = '&'.join(
            term for term in extra_search_terms if len(term) > 0) + date_url
        extra_search_terms_str = self._base_search_url_no_filter + easy_apply_url

        return extra_search_terms_str

    def _get_current_search_url(self):
        """
        Return the correct search URL suffix for the current mode.
        When Easy Apply is exhausted, drop &f_AL=true so external
        (non-Easy-Apply) jobs also appear in search results.
        """
        base = getattr(self, '_base_search_url_no_filter', self.base_search_url)
        if self._easy_apply_exhausted:
            self._log("External-only mode: searching ALL jobs (no Easy Apply filter).", "INFO")
            return base
        return base + "&f_AL=true"

    def next_job_page(self, position, location, job_page):
        self.browser.get("https://www.linkedin.com/jobs/search/" + self._get_current_search_url() +
                         "&keywords=" + position + location + "&start=" + str(job_page * 25))

        self.avoid_lock()

    def next_job_page_direct(self, base_url, job_page):
        """Navigate to a user-supplied URL with automatic pagination (&start=N)."""
        # Strip any existing &start= / ?start= parameter so we can append cleanly
        import re as _re
        clean_url = _re.sub(r'[&?]start=\d+', '', base_url).rstrip('&').rstrip('?')
        separator = '&' if '?' in clean_url else '?'
        paginated_url = clean_url + separator + "start=" + str(job_page * 25)
        print(f"Navigating to: {paginated_url}")
        self.browser.get(paginated_url)
        self.avoid_lock()
