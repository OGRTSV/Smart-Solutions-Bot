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


async def search_phone_org(phone: str, cancel_event: asyncio.Event = None) -> dict:
    """
    Поиск организаций по номеру телефона через list-org.com
    """
    # Импорты исключений selenium для корректной обработки
    from selenium.common.exceptions import TimeoutException, WebDriverException

    results = []
    seen_links = set()

    driver = None  # Объявляем driver снаружи try для надёжного закрытия

    try:
        chrome_options = Options()
        chrome_options.add_argument('--headless=new')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--window-size=1920,1080')
        chrome_options.add_argument(
            '--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36')
        chrome_options.add_argument('--disable-blink-features=AutomationControlled')

        loop = asyncio.get_event_loop()
        logging.info(f"Запускаем Chrome для поиска по телефону {phone}...")

        driver = await loop.run_in_executor(
            None,
            lambda: webdriver.Chrome(
                service=Service(ChromeDriverManager().install()),
                options=chrome_options
            )
        )
        driver.set_page_load_timeout(60)
        driver.implicitly_wait(10)

        try:
            # Очищаем номер от лишних символов
            clean_phone = re.sub(r'\D', '', phone)
            if clean_phone.startswith('7'):
                clean_phone = '+' + clean_phone
            elif clean_phone.startswith('8'):
                clean_phone = '+7' + clean_phone[1:]
            else:
                clean_phone = '+' + clean_phone

            url = f"https://www.list-org.com/search?val={requests.utils.quote(clean_phone)}&type=phone&sort="
            logging.info(f"Загружаем страницу: {url}")

            # Обработка загрузки страницы отдельно
            try:
                await loop.run_in_executor(None, lambda: driver.get(url))
            except WebDriverException as e:
                logging.warning(f"Не удалось загрузить страницу для {phone}: {e}")
                return {
                    "found": False,
                    "results": [],
                    "message": "Сайт list-org.com временно недоступен"
                }

            # Обработка таймаутов и отсутствия результатов отдельно
            results_present = False
            try:
                # Пробуем дождаться результатов максимум 15 секунд
                results_present = await loop.run_in_executor(
                    None,
                    lambda: WebDriverWait(driver, 15).until(
                        lambda d: bool(d.find_elements(By.CSS_SELECTOR, "a[href*='/company/']"))
                    )
                )
            except TimeoutException:
                # Таймаут — это НЕ ошибка. Скорее всего, просто нет результатов.
                logging.info(f"Таймаут ожидания результатов для {phone} (вероятно, ничего не найдено)")
                results_present = False
            except WebDriverException as e:
                logging.warning(f"Ошибка при ожидании результатов: {e}")
                return {
                    "found": False,
                    "results": [],
                    "message": "Сайт list-org.com вернул некорректный ответ"
                }

            # Проверяем отмену пользователя ДО парсинга
            if cancel_event and cancel_event.is_set():
                return {"found": False, "message": "Поиск отменен", "cancelled": True, "results": []}

            html = await loop.run_in_executor(None, lambda: driver.page_source)
            soup = BeautifulSoup(html, 'lxml')
            page_text_lower = html.lower()

            # Проверяем явные сообщения об отсутствии результата
            no_result_keywords = ['ничего не найдено', 'не найдено', 'нет данных',
                                  'поиск не дал результатов', 'компании не найдены']
            if any(keyword in page_text_lower for keyword in no_result_keywords):
                logging.info(f"Сайт явно указал, что для {phone} ничего не найдено")
                return {
                    "found": False,
                    "results": [],
                    "message": "Организации с таким номером не найдены"
                }

            # Если и таймаут был, и явного "не найдено" нет, но и результатов нет
            # → скорее всего это и есть "ничего не найдено", но без надписи
            links = soup.find_all('a', href=re.compile(r'/company/\d+'))
            if not links:
                logging.info(f"Ссылок на компании не найдено для {phone}")
                return {
                    "found": False,
                    "results": [],
                    "message": "Организации с таким номером не найдены"
                }

            # Парсим результаты (тот же блок, что и раньше)
            for link_elem in links:
                if cancel_event and cancel_event.is_set():
                    return {"found": False, "message": "Поиск отменен", "cancelled": True, "results": results}

                try:
                    href = link_elem.get('href', '')
                    if href in seen_links:
                        continue
                    seen_links.add(href)

                    block = None
                    for parent in link_elem.parents:
                        if parent.name in ['tr', 'li', 'div', 'article', 'section', 'td']:
                            company_links = parent.find_all('a', href=re.compile(r'/company/\d+'))
                            if len(company_links) == 1:
                                block = parent
                                break

                    if not block:
                        block = link_elem.parent if link_elem.parent else link_elem
                        if block and block.parent:
                            block = block.parent

                    full_text = block.get_text(separator=' ', strip=True)
                    name = link_elem.get_text(strip=True)

                    org_type = 'Не определено'
                    for prefix in ['ПАО', 'ЗАО', 'ОАО', 'АО', 'ООО']:
                        if prefix in name:
                            org_type = prefix
                            break
                    if org_type == 'Не определено' and (
                            'ИП' in name or 'ИНДИВИДУАЛЬНЫЙ ПРЕДПРИНИМАТЕЛЬ' in full_text.upper()):
                        org_type = 'ИП'

                    status = 'ДЕЙСТВУЮЩАЯ'
                    if re.search(r'(не\s*действ|ликвидир|закрыт|прекращен)', full_text.lower()):
                        status = 'НЕ ДЕЙСТВУЮЩАЯ'
                    elif re.search(r'(в\s*стадии|ликвидаци)', full_text.lower()):
                        status = 'В ПРОЦЕССЕ ЛИКВИДАЦИИ'

                    inn, kpp = 'Не указан', 'Не указан'
                    for pattern in [
                        r'ИНН[:\s]*(\d{10})', r'ИНН[:\s]*(\d{12})',
                        r'ОГРН[:\s]*\d{13,15}.*?(\d{10})', r'\b(\d{10})\b'
                    ]:
                        m = re.search(pattern, full_text, re.IGNORECASE)
                        if m:
                            inn = m.group(1)
                            break

                    kpp_m = re.search(r'\d{10}\s*/\s*(\d{9})\b', full_text)
                    if kpp_m:
                        kpp = kpp_m.group(1)
                    else:
                        kpp_match = re.search(r'КПП[:\s]*(\d{9})', full_text, re.IGNORECASE)
                        if kpp_match:
                            kpp = kpp_match.group(1)

                    address = 'Не указан'
                    for pattern in [
                        r'(?:ЮР\.?\s*АДРЕС|АДРЕС|ЮРИДИЧЕСКИЙ\s*АДРЕС)[:\s]*(.+?)(?:\n|$|ТЕЛЕФОН)',
                        r'(\d{6}[^<\n]{5,80})'
                    ]:
                        addr_m = re.search(pattern, full_text, re.IGNORECASE)
                        if addr_m:
                            address = addr_m.group(1).strip()
                            break

                    results.append({
                        'name': name, 'type': org_type, 'status': status,
                        'inn': inn, 'kpp': kpp, 'address': address,
                        'role': 'Найдено по телефону',
                        'link': 'https://www.list-org.com' + href
                    })
                except Exception as e:
                    logging.warning(f"Ошибка парсинга отдельной компании: {e}")
                    continue

            if not results:
                return {
                    "found": False,
                    "results": [],
                    "message": "Организации с таким номером не найдены"
                }

            return {"found": True, "count": len(results), "results": results}

        finally:
            # Гарантированно закрываем браузер
            if driver is not None:
                await loop.run_in_executor(None, lambda: driver.quit())

    except Exception as e:
        # Сюда попадаем ТОЛЬКО при критических сбоях (не при отсутствии результата!)
        logging.error(f"Критическая ошибка при поиске по телефону {phone}: {e}", exc_info=True)
        # Гарантированно закрываем браузер, если остался открытым
        if driver is not None:
            try:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, lambda: driver.quit())
            except Exception:
                pass
        return {
            "found": False,
            "results": [],
            "message": "Внутренняя ошибка бота. Попробуйте повторить запрос позже.",
            "error": str(e)
        }