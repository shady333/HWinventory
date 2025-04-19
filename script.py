import requests
from bs4 import BeautifulSoup
import re
import pandas as pd
from datetime import datetime
import os
from tabulate import tabulate
import json

# Функція для отримання даних із URL
def get_page_data(url):
    try:
        response = requests.get(url)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, 'html.parser')

        # Отримуємо title
        title_tag = soup.find('title')
        title = title_tag.text.strip() if title_tag else "Title not found"
        if " | " in title:
            title = title.split(" | ")[0].strip()

        # Шукаємо inventoryQty
        script_tags = soup.find_all('script')
        inventory_qty_value = None

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
            if inventory_qty_int < 0:
                inventory_qty_value = "SOLD OUT"

        return {
            'title': title,
            'inventoryQty': inventory_qty_value
        }

    except requests.RequestException as e:
        return {
            'title': f"Error: {str(e)}",
            'inventoryQty': "Error fetching data"
        }

# Функція для обробки групи URL і виводу в консоль
def process_url_group(group_name, urls):
    print(f"\n{group_name}")
    print("=" * len(group_name))

    table_data = []
    results = []

    for url in urls:
        try:
            result = get_page_data(url)
            table_data.append([result['title'], result['inventoryQty']])
            results.append({
                'Car Series': group_name,
                'Car Name': result['title'],
                'InventoryQty': result['inventoryQty']
            })
        except Exception as e:
            table_data.append([f"Error: {url}", str(e)])
            results.append({
                'Car Series': group_name,
                'Car Name': f"Error: {url}",
                'InventoryQty': str(e)
            })

    headers = ["Title", "InventoryQty"]
    print(tabulate(table_data, headers=headers, tablefmt="grid"))
    print("-" * 50)

    return results

# Функція для оновлення CSV-файлу
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
    print(f"\nДані збережено у {csv_file}")

# Функція для збереження результатів у JSON
def save_to_json(all_results, all_results_uk, json_file):
    current_date = datetime.now().strftime("%d.%m.%Y")
    data = {
        "date": current_date,
        "us": [
            {
                "Car Series": r["Car Series"],
                "Car Name": r["Car Name"],
                "InventoryQty": r["InventoryQty"]
            } for r in all_results
        ],
        "uk": [
            {
                "Car Series": r["Car Series"],
                "Car Name": r["Car Name"],
                "InventoryQty": r["InventoryQty"]
            } for r in all_results_uk
        ]
    }
    with open(json_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"Дані збережено у {json_file}")

# Завантаження URL із файлу
def load_urls(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading URLs: {str(e)}")
        return {"us": [], "uk": []}

# Основна частина
if __name__ == "__main__":
    # Завантажуємо URL
    urls_data = load_urls("urls.json")
    url_groups = urls_data.get("us", [])
    url_groups_uk = urls_data.get("uk", [])

    # Обробляємо всі групи та збираємо результати
    all_results = []
    for group in url_groups:
        group_results = process_url_group(group["name"], group["urls"])
        all_results.extend(group_results)

    # Оновлюємо CSV-файл
    update_csv_file(all_results, "inventory_data.csv")

    # Обробляємо всі групи та збираємо результати для UK
    all_results_uk = []
    for group in url_groups_uk:
        group_results_UK = process_url_group(group["name"], group["urls"])
        all_results_uk.extend(group_results_UK)

    # Оновлюємо CSV-файл для UK
    update_csv_file(all_results_uk, "inventory_data_UK.csv")

    # Зберігаємо у JSON
    save_to_json(all_results, all_results_uk, "inventory.json")
