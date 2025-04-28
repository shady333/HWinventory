import requests
from bs4 import BeautifulSoup
import re
import pandas as pd
from datetime import datetime
import os
import json

def get_page_data(url):
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Referer': 'https://creations.mattel.com/'
        }
        response = requests.get(url, headers=headers)
        response.raise_for_status()

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

    except requests.RequestException as e:
        return {
            'title': f"Error: {str(e)}",
            'inventoryQty': "Error fetching data",
            'maxInventoryQty': None,
            'isNegative': False,
            'linkUrl': None,
            'imgSrc': None
        }

def process_url_group(group_name, urls):
    results = []
    for url in urls:
        try:
            result = get_page_data(url)
            results.append({
                'Car Series': group_name,
                'Car Name': result['title'],
                'InventoryQty': result['inventoryQty'],
                'maxInventoryQty': result['maxInventoryQty'],
                'isNegative': result['isNegative'],
                'linkUrl': result['linkUrl'],
                'imgSrc': result['imgSrc'],
            })
        except Exception as e:
            results.append({
                'Car Series': group_name,
                'Car Name': f"Error: {url}",
                'InventoryQty': str(e),
                'maxInventoryQty': None,
                'isNegative': False,
                'linkUrl': None,
                'imgSrc': None
            })
    return results

def update_csv_file(all_results, csv_file):
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
    current_date = datetime.now().strftime("%d.%m.%Y %H:%M UTC")
    data = {
        "date": current_date,
        "us": [],
        "uk": []
    }

    for result in all_results:
        key = f"{result['Car Series']}:{result['Car Name']}"
        max_data = max_inventory["us"].get(key, {})
        max_qty = max_data.get("maxInventoryQty", "N/A")
        max_date = max_data.get("maxInventoryDate", "N/A")
        data["us"].append({
            "Car Series": result["Car Series"],
            "Car Name": result["Car Name"],
            "InventoryQty": result["InventoryQty"],
            "maxInventoryQty": str(max_qty) if max_qty != "N/A" else "N/A",
            "maxInventoryDate": max_date,
            "linkUrl": result['linkUrl'],
            "imgSrc": result['imgSrc']
        })

    for result in all_results_uk:
        key = f"{result['Car Series']}:{result['Car Name']}"
        max_data = max_inventory["uk"].get(key, {})
        max_qty = max_data.get("maxInventoryQty", "N/A")
        max_date = max_data.get("maxInventoryDate", "N/A")
        data["uk"].append({
            "Car Series": result["Car Series"],
            "Car Name": result["Car Name"],
            "InventoryQty": result["InventoryQty"],
            "maxInventoryQty": str(max_qty) if max_qty != "N/A" else "N/A",
            "maxInventoryDate": max_date,
            "linkUrl": result['linkUrl'],
            "imgSrc": result['imgSrc']
        })

    with open(json_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

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

    update_csv_file(all_results, "inventory_data.csv")

    all_results_uk = []
    for group in urls_data.get("uk", []):
        group_results_UK = process_url_group(group["name"], group["urls"])
        all_results_uk.extend(group_results_UK)

    update_csv_file(all_results_uk, "inventory_data_UK.csv")

    max_inventory = update_max_inventory(all_results, all_results_uk, "max_inventory.json")
    save_to_json(all_results, all_results_uk, max_inventory, "inventory.json")