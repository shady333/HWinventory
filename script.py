import requests
from bs4 import BeautifulSoup
import re
import pandas as pd
from datetime import datetime
import os
import json
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import requests.exceptions
import time
from fake_useragent import UserAgent

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
    for url in urls:
        try:
            result = get_page_data(url)
            if (result is not None):
                results.append({
                    'Car Series': group_name,
                    'Car Name': result['title'],
                    'InventoryQty': result['inventoryQty'],
                    'maxInventoryQty': result['maxInventoryQty'],
                    'isNegative': result['isNegative'],
                    'linkUrl': result['linkUrl'],
                    'imgSrc': result['imgSrc'],
                })
                time.sleep(1)  # Затримка 1 секунда між запитами
        except Exception as e:
            print("ERROR ON GET DATA")
            # results.append({
            #     'Car Series': group_name,
            #     'Car Name': f"Error: {url}",
            #     'InventoryQty': str(e),
            #     'maxInventoryQty': None,
            #     'isNegative': False,
            #     'linkUrl': None,
            #     'imgSrc': None
            # })
    return results

def update_csv_file(all_results, csv_file):
    # Перевіряємо, чи є помилка 429
    for result in all_results:
        if "Error: 429" in result["InventoryQty"] or "Error: 429" in result["Car Name"]:
            print(f"Помилка 429 виявлена для {result['Car Name']}. Пропускаємо збереження CSV.")
            return  # Не зберігаємо CSV

    current_date = datetime.now().strftime("%d.%m.%Y")
    if os.path.exists(csv_file):
        df = pd.read_csv(csv_file)
    else:
        df = pd.DataFrame(columns=["Car Series", "Car Name"])

    new_data = []
    for result in all_results:
        new_data.append({
            "Car Series": result["Car Series"],
            "Car Name": result["Car Name"],
            current_date: result["InventoryQty"]
        })
    new_df = pd.DataFrame(new_data)

    if df.empty:
        df = new_df
    else:
        if current_date in df.columns:
            df = df.drop(columns=[current_date])
        df = df.merge(new_df, on=["Car Series", "Car Name"], how="outer")

    df = df.fillna("N/A")
    df.to_csv(csv_file, index=False)

def load_max_inventory(file_path):
    try:
        if os.path.exists(file_path):
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {"us": {}, "uk": {}}
    except Exception as e:
        return {"us": {}, "uk": {}}

def update_max_inventory(all_results, all_results_uk, max_file):
    max_inventory = load_max_inventory(max_file)
    current_date = datetime.now().strftime("%d.%m.%Y %H:%M UTC")

    # Перевіряємо, чи є помилка 429
    for result in all_results + all_results_uk:
        if "Error: 429" in result["InventoryQty"] or "Error: 429" in result["Car Name"]:
            print(f"Помилка 429 виявлена для {result['linkUrl']}. Пропускаємо оновлення max_inventory.")
            return max_inventory  # Не оновлюємо, повертаємо поточний max_inventory

    for result in all_results:
        key = f"{result['Car Series']}:{result['Car Name']}"
        current_qty = result['maxInventoryQty']
        is_negative = result['isNegative']
        if current_qty is not None:
            current_qty_int = int(current_qty)
            max_qty = max_inventory["us"].get(key, {}).get("maxInventoryQty", 0)
            max_date = max_inventory["us"].get(key, {}).get("maxInventoryDate", "N/A")
            update_needed = False
            max_date_value = "" if is_negative else current_date
            if is_negative:
                update_needed = True
            elif max_qty == 0 or max_date == "N/A":
                update_needed = True
            elif current_qty_int > max_qty:
                update_needed = True
            if update_needed:
                max_inventory["us"][key] = {
                    "Car Series": result["Car Series"],
                    "Car Name": result["Car Name"],
                    "maxInventoryQty": current_qty_int,
                    "maxInventoryDate": max_date_value,
                    "linkUrl": result['linkUrl'],
                    "imgSrc": result['imgSrc']
                }

    for result in all_results_uk:
        key = f"{result['Car Series']}:{result['Car Name']}"
        current_qty = result['maxInventoryQty']
        is_negative = result['isNegative']
        if current_qty is not None:
            current_qty_int = int(current_qty)
            max_qty = max_inventory["uk"].get(key, {}).get("maxInventoryQty", 0)
            max_date = max_inventory["uk"].get(key, {}).get("maxInventoryDate", "N/A")
            update_needed = False
            max_date_value = "" if is_negative else current_date
            if is_negative:
                update_needed = True
            elif max_qty == 0 or max_date == "N/A":
                update_needed = True
            elif current_qty_int > max_qty:
                update_needed = True
            if update_needed:
                max_inventory["uk"][key] = {
                    "Car Series": result["Car Series"],
                    "Car Name": result["Car Name"],
                    "maxInventoryQty": current_qty_int,
                    "maxInventoryDate": max_date_value,
                    "linkUrl": result['linkUrl'],
                    "imgSrc": result['imgSrc']
                }

    with open(max_file, 'w', encoding='utf-8') as f:
        json.dump(max_inventory, f, ensure_ascii=False, indent=2)
    return max_inventory

def save_to_json(all_results, all_results_uk, max_inventory, json_file):
    # Перевіряємо, чи є помилка 429 у результатах
    for result in all_results + all_results_uk:
        if "Error: 429" in result["InventoryQty"] or "Error: 429" in result["Car Name"]:
            print(f"Помилка 429 виявлена для {result['linkUrl']}. Пропускаємо збереження JSON.")
            return  # Не зберігаємо файл, якщо є помилка 429

    # Зчитуємо існуючий JSON-файл, якщо він існує
    existing_data = {"date": "", "us": [], "uk": []}
    if os.path.exists(json_file):
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                existing_data = json.load(f)
        except json.JSONDecodeError:
            print(f"Помилка зчитування JSON-файлу {json_file}. Створюємо новий.")

    current_date = datetime.now().strftime("%d.%m.%Y %H:%M UTC")
    new_data = {
        "date": current_date,
        "us": existing_data["us"].copy(),  # Зберігаємо існуючі дані для США
        "uk": existing_data["uk"].copy()   # Зберігаємо існуючі дані для Великобританії
    }

    # Оновлюємо дані для США, якщо є нові результати
    for result in all_results:
        key = f"{result['Car Series']}:{result['Car Name']}"
        max_data = max_inventory["us"].get(key, {})
        max_qty = max_data.get("maxInventoryQty", "N/A")
        max_date = max_data.get("maxInventoryDate", "N/A")

        # Шукаємо існуючий запис для цього автомобіля
        existing_car_index = next(
            (i for i, car in enumerate(new_data["us"]) if car["Car Series"] == result["Car Series"] and car["Car Name"] == result["Car Name"]),
            -1
        )

        # Новий запис для автомобіля
        new_car = {
            "Car Series": result["Car Series"],
            "Car Name": result["Car Name"],
            "InventoryQty": result["InventoryQty"],
            "maxInventoryQty": str(max_qty) if max_qty != "N/A" else "N/A",
            "maxInventoryDate": max_date,
            "linkUrl": result['linkUrl'],
            "imgSrc": result['imgSrc']
        }

        # Якщо запис існує, оновлюємо його, якщо InventoryQty змінилося
        if existing_car_index != -1:
            if new_data["us"][existing_car_index]["InventoryQty"] != result["InventoryQty"]:
                new_data["us"][existing_car_index] = new_car
        else:
            # Якщо запису немає, додаємо новий
            new_data["us"].append(new_car)

    # Оновлюємо дані для Великобританії, якщо є нові результати
    for result in all_results_uk:
        key = f"{result['Car Series']}:{result['Car Name']}"
        max_data = max_inventory["uk"].get(key, {})
        max_qty = max_data.get("maxInventoryQty", "N/A")
        max_date = max_data.get("maxInventoryDate", "N/A")

        # Шукаємо існуючий запис для цього автомобіля
        existing_car_index = next(
            (i for i, car in enumerate(new_data["uk"]) if car["Car Series"] == result["Car Series"] and car["Car Name"] == result["Car Name"]),
            -1
        )

        # Новий запис для автомобіля
        new_car = {
            "Car Series": result["Car Series"],
            "Car Name": result["Car Name"],
            "InventoryQty": result["InventoryQty"],
            "maxInventoryQty": str(max_qty) if max_qty != "N/A" else "N/A",
            "maxInventoryDate": max_date,
            "linkUrl": result['linkUrl'],
            "imgSrc": result['imgSrc']
        }

        # Якщо запис існує, оновлюємо його, якщо InventoryQty змінилося
        if existing_car_index != -1:
            if new_data["uk"][existing_car_index]["InventoryQty"] != result["InventoryQty"]:
                new_data["uk"][existing_car_index] = new_car
        else:
            # Якщо запису немає, додаємо новий
            new_data["uk"].append(new_car)

    # Записуємо оновлені дані у файл
    with open(json_file, 'w', encoding='utf-8') as f:
        json.dump(new_data, f, ensure_ascii=False, indent=2)

def load_urls(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        return {"us": [], "uk": []}

if __name__ == "__main__":
    urls_data = load_urls("urls.json")
    all_results = []
    for group in urls_data.get("us", []):
        group_results = process_url_group(group["name"], group["urls"])
        all_results.extend(group_results)

    if len(all_results) > 0:
        update_csv_file(all_results, "inventory_data.csv")

    all_results_uk = []
    for group in urls_data.get("uk", []):
        group_results_UK = process_url_group(group["name"], group["urls"])
        all_results_uk.extend(group_results_UK)

    if len(all_results_uk) > 0:
        update_csv_file(all_results_uk, "inventory_data_UK.csv")

    max_inventory = update_max_inventory(all_results, all_results_uk, "max_inventory.json")
    save_to_json(all_results, all_results_uk, max_inventory, "docs/inventory.json")