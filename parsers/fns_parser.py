import asyncio
import logging
import re
import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

async def search_fns(fio: str, cancel_event: asyncio.Event = None) -> dict:
    """
    Поиск по реестрам ФНС через list-org.com с поддержкой пагинации.
    """
    fio_parts = fio.strip().split()
    is_full_fio = len(fio_parts) == 3
    results = []
    seen_links = set()
    MAX_PAGES = 5
    # Переменные для отслеживания точек остановки
    ip_stopped_at_page = None
    boss_stopped_at_page = None

    try:
        chrome_options = Options()
        chrome_options.add_argument('--headless=new')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--window-size=1920,1080')
        chrome_options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
        chrome_options.add_argument('--disable-blink-features=AutomationControlled')

        loop = asyncio.get_event_loop()
        logging.info("Запускаем Chrome browser...")
        driver = await loop.run_in_executor(
            None,
            lambda: webdriver.Chrome(
                service=Service(ChromeDriverManager().install()),
                options=chrome_options
            )
        )
        driver.set_page_load_timeout(300)
        driver.set_script_timeout(300)
        driver.implicitly_wait(10)

        try:
            # ==========================================
            # ЭТАП 1: ПАРСИМ ИП (type=fio)
            # ==========================================
            logging.info(f"Этап 1: Поиск ИП (type=fio)")
            for page in range(1, MAX_PAGES + 1):
                if cancel_event and cancel_event.is_set():
                    return {"found": False, "message": "Поиск отменен", "cancelled": True}
                if page == 1:
                    url = f"https://www.list-org.com/search?type=fio&val={requests.utils.quote(fio)}"
                else:
                    url = f"https://www.list-org.com/search?type=fio&val={requests.utils.quote(fio)}&page={page}"
                logging.info(f"Загружаем страницу ИП {page}: {url}")
                try:
                    await loop.run_in_executor(None, lambda: driver.get(url))
                    await loop.run_in_executor(
                        None,
                        lambda: WebDriverWait(driver, 30).until(
                            lambda d: d.find_elements(By.CSS_SELECTOR, "a[href*='/man/']") or
                                      "ничего не найдено" in d.page_source.lower() or
                                      "по вашему запросу ничего не найдено" in d.page_source.lower()
                        )
                    )
                except Exception as e:
                    logging.warning(f"Таймаут или ошибка загрузки страницы ИП {page}: {e}")
                    break

                html = await loop.run_in_executor(None, lambda: driver.page_source)
                soup = BeautifulSoup(html, 'lxml')
                links = soup.find_all('a', href=re.compile(r'/man/\d+'))
                if not links:
                    logging.info(f"Страница ИП {page} пуста. Останавливаем цикл ИП.")
                    break

                ip_found_on_page = 0
                for link_elem in links:
                    try:
                        href = link_elem.get('href', '')
                        if href in seen_links: continue
                        name = link_elem.get_text(strip=True)
                        if is_full_fio:
                            name_lower = name.lower()
                            fio_parts_lower = [p.lower() for p in fio_parts]
                            if not all(part in name_lower for part in fio_parts_lower):
                                continue
                        seen_links.add(href)
                        block = link_elem.parent if link_elem.parent else link_elem
                        full_text = block.get_text(separator=' ', strip=True)
                        inn = 'Не указан'
                        inn_m = re.search(r'\b(\d{12})\b', full_text)
                        if inn_m: inn = inn_m.group(1)
                        clean_name = re.sub(r'\(ИНН[:\s]*\d+\)', '', name).strip()
                        clean_name = re.sub(r'ИНН[:\s]*\d+', '', clean_name).strip()
                        results.append({
                            'name': clean_name, 'type': 'ИП', 'status': '-', 'inn': inn,
                            'kpp': 'Не применяется', 'address': '-', 'role': 'Индивидуальный предприниматель',
                            'link': 'https://www.list-org.com' + href, 'search_type': 'Руководитель/учредитель'
                        })
                        ip_found_on_page += 1
                    except Exception as e:
                        logging.warning(f"Ошибка парсинга ИП: {e}")
                        continue
                logging.info(f"На странице ИП {page} добавлено: {ip_found_on_page}")
                # Если нашли что-то на этой странице и это была последняя в лимите
                if ip_found_on_page > 0 and page == MAX_PAGES:
                    ip_stopped_at_page = page + 1

            # --- ПРОВЕРКА СУЩЕСТВОВАНИЯ СЛЕДУЮЩЕЙ СТРАНИЦЫ ИП ---
            if ip_stopped_at_page == MAX_PAGES + 1:
                next_url = f"https://www.list-org.com/search?type=fio&val={requests.utils.quote(fio)}&page={MAX_PAGES + 1}"
                try:
                    logging.info(f"Проверяем наличие данных на следующей странице ИП: {next_url}")
                    await loop.run_in_executor(None, lambda: driver.get(next_url))
                    await loop.run_in_executor(
                        None,
                        lambda: WebDriverWait(driver, 15).until(
                            lambda d: d.find_elements(By.CSS_SELECTOR, "a[href*='/man/']") or
                                      "ничего не найдено" in d.page_source.lower() or
                                      "по вашему запросу ничего не найдено" in d.page_source.lower()
                        )
                    )
                    html_next = await loop.run_in_executor(None, lambda: driver.page_source)
                    soup_next = BeautifulSoup(html_next, 'lxml')
                    next_links = soup_next.find_all('a', href=re.compile(r'/man/\d+'))
                    if not next_links:
                        logging.info("Следующая страница ИП пуста. Ссылку не даем.")
                        ip_stopped_at_page = None
                except Exception as e:
                    logging.warning(f"Ошибка проверки следующей страницы ИП: {e}")
                    ip_stopped_at_page = None

            # ==========================================
            # ЭТАП 2: ПАРСИМ КОМПАНИИ (type=boss)
            # ==========================================
            logging.info(f"Этап 2: Поиск Компаний (type=boss)")
            for page in range(1, MAX_PAGES + 1):
                if cancel_event and cancel_event.is_set():
                    return {"found": False, "message": "Поиск отменен", "cancelled": True}
                if page == 1:
                    url = f"https://www.list-org.com/search?val={requests.utils.quote(fio)}&type=boss&sort="
                else:
                    url = f"https://www.list-org.com/search?val={requests.utils.quote(fio)}&type=boss&sort=&page={page}"
                logging.info(f"Загружаем страницу Компаний {page}: {url}")
                try:
                    await loop.run_in_executor(None, lambda: driver.get(url))
                    await loop.run_in_executor(
                        None,
                        lambda: WebDriverWait(driver, 30).until(
                            lambda d: d.find_elements(By.CSS_SELECTOR, "a[href*='/company/']") or
                                      "ничего не найдено" in d.page_source.lower() or
                                      "по вашему запросу ничего не найдено" in d.page_source.lower()
                        )
                    )
                except Exception as e:
                    logging.warning(f"Таймаут или ошибка загрузки страницы Компаний {page}: {e}")
                    break

                html = await loop.run_in_executor(None, lambda: driver.page_source)
                soup = BeautifulSoup(html, 'lxml')
                links = soup.find_all('a', href=re.compile(r'/company/\d+'))
                if not links:
                    logging.info(f"Страница Компаний {page} пуста. Останавливаем цикл Компаний.")
                    break

                comp_found_on_page = 0
                for link_elem in links:
                    try:
                        href = link_elem.get('href', '')
                        if href in seen_links: continue
                        name = link_elem.get_text(strip=True)
                        seen_links.add(href)
                        block = None
                        for parent in link_elem.parents:
                            if parent.name in ['tr', 'li', 'div', 'article', 'section', 'td']:
                                other_links = parent.find_all('a', href=re.compile(r'/(company|man)/\d+'))
                                unique_hrefs = set(a.get('href') for a in other_links)
                                if len(unique_hrefs) <= 2:
                                    block = parent
                                    break
                        if not block:
                            block = link_elem.parent.parent if link_elem.parent else link_elem
                        full_text = block.get_text(separator=' ', strip=True)
                        text_lower = full_text.lower()
                        # УЛУЧШЕННОЕ ОПРЕДЕЛЕНИЕ ТИПА ОРГАНИЗАЦИИ
                        org_type = 'Не определено'
                        if 'ПАО' in name:
                            org_type = 'ПАО'
                        elif 'ЗАО' in name:
                            org_type = 'ЗАО'
                        elif 'ОАО' in name:
                            org_type = 'ОАО'
                        elif 'АО' in name:
                            org_type = 'АО'
                        elif 'ООО' in name:
                            org_type = 'ООО'
                        elif 'НП' in name or 'НЕКОММЕРЧЕСКОЕ ПАРТНЕРСТВО' in name:
                            org_type = 'НП'
                        elif 'АНО' in name or 'АВТОНОМНАЯ НЕКОММЕРЧЕСКАЯ' in name:
                            org_type = 'АНО'
                        elif 'ФОНД' in name:
                            org_type = 'Фонд'
                        elif 'НКО' in name:
                            org_type = 'НКО'
                        elif 'ФГУП' in name:
                            org_type = 'ФГУП'
                        elif 'ГУП' in name:
                            org_type = 'ГУП'
                        elif 'МУП' in name:
                            org_type = 'МУП'
                        elif 'ТОВАРИЩЕСТВО' in name:
                            org_type = 'Товарищество'
                        elif 'КООПЕРАТИВ' in name:
                            org_type = 'Кооператив'
                        elif 'СОЮЗ' in name:
                            org_type = 'Союз'
                        elif 'АССОЦИАЦИЯ' in name:
                            org_type = 'Ассоциация'

                        status = 'ДЕЙСТВУЮЩАЯ'
                        if re.search(r'(ликвидирован|не\s*действую|прекращен|исключен|закрыт|аннулирован)', text_lower):
                            status = 'ЛИКВИДИРОВАНА'
                        elif re.search(r'(в\s*стадии|ликвидаци|реорганизаци)', text_lower):
                            status = 'В ПРОЦЕССЕ ЛИКВИДАЦИИ'

                        inn = 'Не указан'
                        kpp = 'Не указан'
                        inn_m = re.search(r'\b(\d{10})\b', full_text)
                        if inn_m: inn = inn_m.group(1)
                        kpp_slash = re.search(r'\d{10}\s*/\s*(\d{9})\b', full_text)
                        if kpp_slash:
                            kpp = kpp_slash.group(1)
                        else:
                            kpp_m = re.search(r'\b(\d{9})\b', full_text)
                            if kpp_m: kpp = kpp_m.group(1)

                        address = 'Не указан'
                        addr_m = re.search(r'(?:Адрес|Юр\.?\s*адрес|Местонахождение)[:\s]*(.+?)(?:\n|$)', full_text,
                                           re.IGNORECASE)
                        if addr_m:
                            address = addr_m.group(1).strip()
                        else:
                            addr_m = re.search(r'\b(\d{6}[^<\n]{5,50})\b', full_text)
                            if addr_m: address = addr_m.group(1).strip()

                        clean_name = re.sub(r'\(ИНН[:\s]*\d+\)', '', name).strip()
                        clean_name = re.sub(r'ИНН[:\s]*\d+', '', clean_name).strip()
                        results.append({
                            'name': clean_name, 'type': org_type, 'status': status, 'inn': inn, 'kpp': kpp,
                            'address': address, 'role': 'Учредитель (один из учредителей)',
                            'link': 'https://www.list-org.com' + href, 'search_type': 'Руководитель/учредитель'
                        })
                        comp_found_on_page += 1
                    except Exception as e:
                        logging.warning(f"Ошибка парсинга компании: {e}")
                        continue
                logging.info(f"На странице Компаний {page} добавлено: {comp_found_on_page}")
                # Если нашли что-то на этой странице и это была последняя в лимите
                if comp_found_on_page > 0 and page == MAX_PAGES:
                    boss_stopped_at_page = page + 1

            # --- ПРОВЕРКА СУЩЕСТВОВАНИЯ СЛЕДУЮЩЕЙ СТРАНИЦЫ КОМПАНИЙ ---
            if boss_stopped_at_page == MAX_PAGES + 1:
                next_url = f"https://www.list-org.com/search?val={requests.utils.quote(fio)}&type=boss&sort=&page={MAX_PAGES + 1}"
                try:
                    logging.info(f"Проверяем наличие данных на следующей странице Компаний: {next_url}")
                    await loop.run_in_executor(None, lambda: driver.get(next_url))
                    await loop.run_in_executor(
                        None,
                        lambda: WebDriverWait(driver, 15).until(
                            lambda d: d.find_elements(By.CSS_SELECTOR, "a[href*='/company/']") or
                                      "ничего не найдено" in d.page_source.lower() or
                                      "по вашему запросу ничего не найдено" in d.page_source.lower()
                        )
                    )
                    html_next = await loop.run_in_executor(None, lambda: driver.page_source)
                    soup_next = BeautifulSoup(html_next, 'lxml')
                    next_links = soup_next.find_all('a', href=re.compile(r'/company/\d+'))
                    if not next_links:
                        logging.info("Следующая страница Компаний пуста. Ссылку не даем.")
                        boss_stopped_at_page = None
                except Exception as e:
                    logging.warning(f"Ошибка проверки следующей страницы Компаний: {e}")
                    boss_stopped_at_page = None

        finally:
            await loop.run_in_executor(None, lambda: driver.quit())

        # Формируем ссылки на продолжение поиска
        ip_next_url = None
        boss_next_url = None
        if ip_stopped_at_page:
            ip_next_url = f"https://www.list-org.com/search?type=fio&val={requests.utils.quote(fio)}&page={ip_stopped_at_page}"
        if boss_stopped_at_page:
            boss_next_url = f"https://www.list-org.com/search?val={requests.utils.quote(fio)}&type=boss&sort=&page={boss_stopped_at_page}"

        if not results:
            return {"found": False, "message": "Ничего не найдено в реестрах ФНС"}

        return {
            "found": True,
            "count": len(results),
            "results": results,
            "search_type": "full" if is_full_fio else "partial",
            "ip_next_url": ip_next_url,
            "boss_next_url": boss_next_url
        }
    except Exception as e:
        logging.error(f"Ошибка при поиске в ФНС: {e}", exc_info=True)
        return {"error": f"Ошибка при обработке данных: {str(e)}"}