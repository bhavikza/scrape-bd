
import time
import random
import sqlite3
import requests
import os
from dotenv import load_dotenv
from datetime import datetime
import undetected_chromedriver as uc
from selenium_stealth import stealth
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# --- Configuration ---
load_dotenv() # Load variables from .env

DB_NAME = os.getenv("DB_NAME")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") 
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
BASE_URL = os.getenv("BASE_URL")

def init_db():
    """Initialize the SQLite database and create the table if it doesn't exist."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS events
                 (market_id TEXT PRIMARY KEY, 
                  event_time TEXT, 
                  description TEXT, 
                  back_price TEXT, 
                  back_liquidity TEXT, 
                  lay_price TEXT, 
                  lay_liquidity TEXT,
                  first_seen TEXT,
                  last_updated TEXT)''')
    conn.commit()
    conn.close()

def send_telegram__notification(message):
    """Send a message via Telegram."""
    if TELEGRAM_BOT_TOKEN == "YOUR_BOT_TOKEN":
        print(f"[simulate] Telegram Notification: {message}")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code != 200:
            print(f"Failed to send Telegram message: {response.text}")
    except Exception as e:
        print(f"Error sending Telegram notification: {e}")

def process_event_db(data):
    """
    Insert or update the event in the database.
    Returns True if it was a new event (inserted), False otherwise.
    """
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    market_id = data.get('market_id')
    if not market_id or market_id == "N/A":
        conn.close()
        return False

    # Check if exists
    c.execute("SELECT market_id FROM events WHERE market_id = ?", (market_id,))
    exists = c.fetchone()
    
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    is_new = False
    if exists is None:
        # Insert new
        c.execute('''INSERT INTO events 
                     (market_id, event_time, description, back_price, back_liquidity, lay_price, lay_liquidity, first_seen, last_updated)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                  (market_id, data['time'], data['description'], 
                   data['back_price'], data['back_liquidity'], 
                   data['lay_price'], data['lay_liquidity'], 
                   now, now))
        is_new = True
    else:
        # Update existing (keep history of last seen state)
        c.execute('''UPDATE events SET 
                     back_price=?, back_liquidity=?, lay_price=?, lay_liquidity=?, last_updated=?
                     WHERE market_id=?''',
                  (data['back_price'], data['back_liquidity'], 
                   data['lay_price'], data['lay_liquidity'], 
                   now, market_id))
    
    conn.commit()
    conn.close()
    return is_new

def main():
    init_db()
    
    # Setup Chrome options
    options = uc.ChromeOptions()
    options.add_argument('--headless')  # Comment in if you want headless mode
    
    # Speed optimizations - Use with caution if you get blocked, sometimes eager is detectable
    options.page_load_strategy = 'eager' 
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    prefs = {
        "profile.managed_default_content_settings.images": 2, 
    }
    options.add_experimental_option("prefs", prefs)

    # Patch undetected_chromedriver's __del__ to suppress the annoying OSError on Windows
    def _suppress_del_error(self):
        try:
            self.quit()
        except OSError:
            pass
        except Exception:
            pass
    uc.Chrome.__del__ = _suppress_del_error

    # Initialize the driver
    driver = uc.Chrome(options=options)
    
    try:
        # Apply stealth settings
        stealth(driver,
            languages=["en-US", "en"],
            vendor="Google Inc.",
            platform="Win32",
            webgl_vendor="Intel Inc.",
            renderer="Intel Iris OpenGL Engine",
            fix_hairline=True,
        )

        print(f"Navigating to {BASE_URL}...")
        driver.get(BASE_URL)
        
        # Random sleep to mimic human pause
        time.sleep(random.uniform(1.5, 3.0))
        
        wait = WebDriverWait(driver, 20)
        
        try:
            print("Looking for 'enhanced' link in menu...")
            menu_wrapper = wait.until(EC.presence_of_element_located((By.CLASS_NAME, "menu-items-wrapper")))
            
            # Find link
            enhanced_link = menu_wrapper.find_element(By.XPATH, ".//a[contains(@href, 'enhanced')]")
            target_url = enhanced_link.get_attribute("href")
            print(f"Found target URL: {target_url}")
            
            # Navigate
            driver.get(target_url)
            
        except Exception as e:
            print(f"Failed to find or navigate to enhanced specials page: {e}")
            return

        # Wait for page content
        print("Waiting for page content...")
        wait.until(EC.presence_of_element_located((By.CLASS_NAME, "widgetEvent")))
        
        # Random delay for dynamic content load + human behavior
        time.sleep(random.uniform(1.5, 2.5))
        
        events = driver.find_elements(By.CLASS_NAME, "widgetEvent")
        print(f"Found {len(events)} events. Extracting data...\n")
        
        results = []
        
        for event in events:
            data = {}
            
            # --- Extract Market ID ---
            try:
                # Class string looks like "widgetEvent marketId-49119881"
                class_names = event.get_attribute("class").split()
                # Find the class that starts with 'marketId-' and strip the prefix
                market_id = next((c.replace("marketId-", "") for c in class_names if c.startswith("marketId-")), "N/A")
                data['market_id'] = market_id
            except:
                data['market_id'] = "N/A"

            # --- Extract Header Information ---
            try:
                data['time'] = event.find_element(By.CLASS_NAME, "widgetEvent-startTime").text
            except:
                data['time'] = "N/A"
                
            try:
                # The main market description (e.g. "Bobby De Cordova-Reid ...")
                data['description'] = event.find_element(By.CLASS_NAME, "marketName").text.strip()
            except:
                data['description'] = "N/A"
            
            # --- Extract Odds and Liquidity ---
            # We target the .widgetSelection container
            try:
                selection = event.find_element(By.CLASS_NAME, "widgetSelection")
                
                # Back Price (b_0) - The primary back column (Yellow/Orange)
                try:
                    b0 = selection.find_element(By.CSS_SELECTOR, ".back-price.b_0")
                    data['back_price'] = b0.find_element(By.CLASS_NAME, "price").text
                    data['back_liquidity'] = b0.find_element(By.CLASS_NAME, "stake").text
                except:
                    data['back_price'] = "-"
                    data['back_liquidity'] = "-"

                # Lay Price (l_0) - The primary lay column (Green)
                try:
                    l0 = selection.find_element(By.CSS_SELECTOR, ".lay-price.l_0")
                    data['lay_price'] = l0.find_element(By.CLASS_NAME, "price").text
                    data['lay_liquidity'] = l0.find_element(By.CLASS_NAME, "stake").text
                except:
                    data['lay_price'] = "-"
                    data['lay_liquidity'] = "-"
                    
            except Exception as e:
                print(f"Error parsing selection for event: {data.get('description', 'Unknown')}")
                data['back_price'] = "Err"
                
            results.append(data)
            
            # --- DB & Notification ---
            try:
                is_new_event = process_event_db(data)
                if is_new_event:
                    msg = (f"🔥 *New Enhanced Special Found!* 🔥\n\n"
                           f"*{data.get('description', 'N/A')}*\n"
                           f"Time: {data.get('time', 'N/A')}\n"
                           f"Back: {data.get('back_price', '-')} ({data.get('back_liquidity', '-')})\n"
                           f"Lay: {data.get('lay_price', '-')} ({data.get('lay_liquidity', '-')})\n"
                           f"Market ID: `{data.get('market_id')}`")
                    send_telegram__notification(msg)
                    print(f"-> New event detected! Notification sent for {data.get('market_id')}")
            except Exception as e:
                print(f"Error processing DB/Notification: {e}")
            
        # --- Output Data ---
        # Headers
        print(f"{'MARKET ID':<12} | {'TIME':<8} | {'DESCRIPTION':<50} | {'BACK':<6} | {'LIQUIDITY':<10} | {'LAY':<6} | {'LIQUIDITY':<10}")
        print("-" * 130)
        
        for r in results:
            m_id = r.get('market_id', '')
            time_str = r.get('time', '')
            desc = r.get('description', '')
            # Truncate description if too long
            if len(desc) > 48:
                desc = desc[:45] + "..."
            
            print(f"{m_id:<12} | {time_str:<8} | {desc:<50} | {r.get('back_price', ''):<6} | {r.get('back_liquidity', ''):<10} | {r.get('lay_price', ''):<6} | {r.get('lay_liquidity', ''):<10}")

    except Exception as e:
        print(f"An error occurred during execution: {e}")
        
    finally:
        print("\nClosing driver...")
        driver.quit()

if __name__ == "__main__":
    main()
