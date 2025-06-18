import logging
import requests
from bs4 import BeautifulSoup
import re
from datetime import datetime
import os
import json
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import requests.exceptions
import time
from fake_useragent import UserAgent

# Налаштування логування
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('script.log', 'a', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

def get_page_data(url):
    @retry(
        stop=stop_after_attempt(3),  # Максимум 3 спроби
        wait=wait_exponential(multiplier=1, min=4, max=10),  # Експоненційна затримка від 4 до 10 секунд
        retry=retry_if_exception_type(requests.exceptions.HTTPError)
    )
    def fetch_page(url, headers):
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return response

    try:
        ua = UserAgent()
        headers = {
            'User-Agent': ua.random,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Referer': 'https://creations.mattel.com/'
        }
        response = fetch_page(url, headers)

        soup = BeautifulSoup(response.text, 'html.parser')
        title_tag = soup.find('title')
        title = title_tag.text.strip() if title_tag else "Title not found"
        if " | " in title:
            title = title.split(" | ")[0].strip()

        script_tags = soup.find_all('script')
        inventory_qty_value = None
        max_inventory_qty = None
        is_negative = False

        for script in script_tags:
            script_content = script.text
            if script_content and 'SDG.Data.inventoryQty' in script_content:
                match = re.search(r'inventoryQty\s*=\s*({[^}]*})', script_content)
                if match:
                    inventory_qty_object = match.group(1)
                    value_match = re.search(r'"\d+"\s*:\s*(-?\d+)', inventory_qty_object)
                    if value_match:
                        inventory_qty_value = value_match.group(1)
                    break

        if inventory_qty_value is None:
            inventory_qty_value = "Inventory quantity not found"
            return None
        else:
            inventory_qty_int = int(inventory_qty_value)
            max_inventory_qty = abs(inventory_qty_int)
            if inventory_qty_int < 0:
                inventory_qty_value = "SOLD OUT"
                is_negative = True
            else:
                inventory_qty_value = str(inventory_qty_int)

        try:
            filename = re.search(r'products/(.+)', url).group(1) + ".png"
        except (AttributeError, IndexError):
            filename = ""

        return {
            'title': title,
            'inventoryQty': inventory_qty_value,
            'maxInventoryQty': max_inventory_qty,
            'isNegative': is_negative,
            'linkUrl': url,
            'imgSrc': filename
        }

    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 429:
            print(f"Помилка 429 для {url}. Спроби вичерпано.")
        return {
            'title': f"Error: {str(e)}",
            'inventoryQty': f"Error: {str(e)}",
            'maxInventoryQty': None,
            'isNegative': False,
            'linkUrl': url,
            'imgSrc': None
        }
    except requests.RequestException as e:
        return {
            'title': f"Error: {str(e)}",
            'inventoryQty': f"Error: {str(e)}",
            'maxInventoryQty': None,
            'isNegative': False,
            'linkUrl': url,
            'imgSrc': None
        }

def process_url_group(group_name, urls):
    results = []
    logging.info(f"Analysing group - {group_name}")
    for url in urls:
        try:
            result = get_page_data(url)
            if result is not None and not result['title'].startswith('Error'):
                results.append({
                    'Car Series': group_name,
                    'Car Name': result['title'],
                    'InventoryQty': result['inventoryQty'],
                    'maxInventoryQty': result['maxInventoryQty'],
                    'isNegative': result['isNegative'],
                    'linkUrl': result['linkUrl'],
                    'imgSrc': result['imgSrc'],
                })
                logging.info(f"Processed {url} successfully")
            else:
                logging.warning(f"Skipping {url}: result={result}")
            time.sleep(2)  # Затримка 2 секунди
        except Exception as e:
            logging.error(f"Error processing {url}: {str(e)}")
    return results

def load_max_inventory(file_path):
    try:
        if os.path.exists(file_path):
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}
    except Exception as e:
        logging.error(f"Error loading max_inventory from {file_path}: {e}")
        return {}

def update_max_inventory(all_results_by_region, max_file):
    max_inventory = load_max_inventory(max_file)
    current_date = datetime.now().strftime("%d.%m.%Y %H:%M UTC")

    for region in all_results_by_region:
        for result in all_results_by_region[region]:
            if "Error: 429" in str(result["InventoryQty"]) or "Error: 429" in str(result["Car Name"]):
                logging.error(f"Error 429 detected for {result['linkUrl']}. Skipping max_inventory update.")
                return max_inventory

    for region in all_results_by_region:
        if region not in max_inventory:
            max_inventory[region] = {}
        for result in all_results_by_region[region]:
            key = f"{result['Car Series']}:{result['Car Name']}"
            current_qty = result['maxInventoryQty']
            is_negative = result['isNegative']
            if current_qty is not None:
                current_qty_int = int(current_qty)
                max_qty = max_inventory[region].get(key, {}).get("maxInventoryQty", 0)
                max_date = max_inventory[region].get(key, {}).get("maxInventoryDate", "N/A")
                update_needed = False
                max_date_value = "" if is_negative else current_date
                if is_negative or max_qty == 0 or max_date == "N/A" or current_qty_int > max_qty:
                    update_needed = True
                if update_needed:
                    max_inventory[region][key] = {
                        "Car Series": result["Car Series"],
                        "Car Name": result["Car Name"],
                        "maxInventoryQty": current_qty_int,
                        "maxInventoryDate": max_date_value,
                        "linkUrl": result['linkUrl'],
                        "imgSrc": result['imgSrc']
                    }

    with open(max_file, 'w', encoding='utf-8') as f:
        json.dump(max_inventory, f, ensure_ascii=False, indent=2)
    logging.info(f"Updated max_inventory: {max_file}")
    return max_inventory

def save_to_json(all_results_by_region, max_inventory, json_file):
    for region in all_results_by_region:
        for result in all_results_by_region[region]:
            if "Error: 429" in str(result["InventoryQty"]) or "Error: 429" in str(result["Car Name"]):
                logging.error(f"Error 429 detected for {result['linkUrl']}. Skipping JSON save.")
                return

    existing_data = {"date": "", **{region: [] for region in all_results_by_region}}
    if os.path.exists(json_file):
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                existing_data = json.load(f)
        except json.JSONDecodeError:
            logging.error(f"Error reading JSON file {json_file}. Creating new.")

    current_date = datetime.now().strftime("%d.%m.%Y %H:%M UTC")
    new_data = {
        "date": current_date,
        **{region: existing_data.get(region, []).copy() for region in all_results_by_region}
    }

    for region in all_results_by_region:
        for result in all_results_by_region[region]:
            key = f"{result['Car Series']}:{result['Car Name']}"
            max_data = max_inventory.get(region, {}).get(key, {})
            max_qty = max_data.get("maxInventoryQty", "N/A")
            max_date = max_data.get("maxInventoryDate", "N/A")
            existing_car_index = next(
                (i for i, car in enumerate(new_data[region]) if car["Car Series"] == result["Car Series"] and car["Car Name"] == result["Car Name"]),
                -1
            )
            new_car = {
                "Car Series": result["Car Series"],
                "Car Name": result["Car Name"],
                "InventoryQty": result["InventoryQty"],
                "maxInventoryQty": str(max_qty) if max_qty != "N/A" else "N/A",
                "maxInventoryDate": max_date,
                "linkUrl": result['linkUrl'],
                "imgSrc": result['imgSrc']
            }
            if existing_car_index != -1:
                if new_data[region][existing_car_index]["InventoryQty"] != result["InventoryQty"]:
                    new_data[region][existing_car_index] = new_car
            else:
                new_data[region].append(new_car)

    with open(json_file, 'w', encoding='utf-8') as f:
        json.dump(new_data, f, ensure_ascii=False, indent=2)
    logging.info(f"Saved JSON: {json_file}")

def load_urls(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logging.error(f"Error loading urls from {file_path}: {e}")
        return {}

if __name__ == "__main__":
    urls_data = load_urls("urls.json")
    all_results_by_region = {}

    for region in urls_data:
        all_results_by_region[region] = []
        for group in urls_data.get(region, []):
            group_results = process_url_group(group["name"], group["urls"])
            all_results_by_region[region].extend(group_results)

    max_inventory = update_max_inventory(all_results_by_region, "max_inventory.json")
    save_to_json(all_results_by_region, max_inventory, "docs/inventory.json")