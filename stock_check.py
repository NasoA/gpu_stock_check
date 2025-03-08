import requests
from bs4 import BeautifulSoup
import time
import logging
import re
import random
from fake_useragent import UserAgent
import subprocess

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Your phone number or Apple ID to receive iMessages
YOUR_PHONE_NUMBER = '123456789'  # Replace with your iMessage-enabled number or Apple ID email

# Price limits
PRICE_LIMITS = {
    'AMD': {'min': 599, 'max': 699},
    'Nvidia': {'min': 599, 'max': 799}
}

# Target products
TARGET_PRODUCTS = {
    'AMD': ["RX 9070 XT"],
    'Nvidia': ["RTX 5070", "RTX 5070 Ti"]
}

# Initialize User-Agent rotator
ua = UserAgent()

# Search URLs to monitor
URLS = {
    'AMD': {
        'Amazon': 'https://www.amazon.com/s?k=radeon+rx+9070+xt',
        'BestBuy': 'https://www.bestbuy.com/site/searchpage.jsp?st=radeon+rx+9070+xt',
        'Newegg': 'https://www.newegg.com/p/pl?d=radeon+rx+9070+xt'
    },
    'Nvidia': {
        'Amazon': 'https://www.amazon.com/s?k=rtx+5070+5070+ti',
        'BestBuy': 'https://www.bestbuy.com/site/searchpage.jsp?st=rtx+5070+5070+ti',
        'Newegg': 'https://www.newegg.com/p/pl?d=rtx+5070+5070+ti'
    }
}

def send_imessage(message):
    """Send an iMessage using AppleScript on macOS."""
    try:
        applescript = f'''
        tell application "Messages"
            set iMessageService to (1st account whose service type is iMessage)
            set targetBuddy to buddy "{YOUR_PHONE_NUMBER}" of iMessageService
            send "{message}" to targetBuddy
        end tell
        '''
        result = subprocess.run(['osascript', '-e', applescript], check=True, capture_output=True, text=True)
        logging.info(f"iMessage sent: {message} - Output: {result.stdout}")
    except subprocess.CalledProcessError as e:
        logging.error(f"Failed to send iMessage: {e.stderr}")
    except Exception as e:
        logging.error(f"Failed to send iMessage: {str(e)}")

def extract_price(text):
    """Extract price from text and convert to float."""
    match = re.search(r'\$?(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)', text)
    if match:
        price_str = match.group(1).replace(',', '')
        return float(price_str)
    return None

def is_target_gpu(title, gpu_type):
    """Check if the product title matches the target GPU."""
    title = title.lower()
    if gpu_type == 'AMD':
        if "rx 9070 xt" in title and not re.search(r'rx\s*(7800|7900|6800|6700|6900)\s*xt', title):
            return True
    elif gpu_type == 'Nvidia':
        if ("rtx 5070" in title or "rtx 5070 ti" in title) and not re.search(r'rtx\s*(4060|4070|4080|4090|5060)', title):
            return True
    return False

def get_headers():
    """Generate random headers to mimic a browser."""
    return {
        'User-Agent': ua.random,
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Referer': 'https://www.google.com/',
        'Connection': 'keep-alive'
    }

def retry_request(url, retries=3, backoff_factor=2):
    """Retry a request with exponential backoff."""
    headers = get_headers()
    for attempt in range(retries):
        try:
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            return response
        except requests.RequestException as e:
            if attempt == retries - 1:
                raise e
            sleep_time = backoff_factor * (2 ** attempt) + random.uniform(0, 1)
            logging.warning(f"Request failed for {url}: {e}. Retrying in {sleep_time:.2f} seconds...")
            time.sleep(sleep_time)
    return None

def check_amazon(gpu_type):
    try:
        response = retry_request(URLS[gpu_type]['Amazon'])
        if not response:
            return False, None, None, None
        soup = BeautifulSoup(response.text, 'html.parser')
        for item in soup.find_all('div', {'data-component-type': 's-search-result'}):
            title_elem = item.find('span', {'class': 'a-text-normal'})
            if not title_elem:
                continue
            title = title_elem.text.strip()
            if not is_target_gpu(title, gpu_type):
                logging.debug(f"Skipping non-target GPU on Amazon: {title}")
                continue
            link = item.find('a', {'class': 'a-link-normal'})
            if link:
                product_url = 'https://www.amazon.com' + link['href']
                product_response = retry_request(product_url)
                if not product_response:
                    continue
                product_soup = BeautifulSoup(product_response.text, 'html.parser')
                add_to_cart = product_soup.find('input', {'id': 'add-to-cart-button'})
                if add_to_cart:
                    price_span = product_soup.find('span', {'class': 'a-price'})
                    if price_span:
                        price = extract_price(price_span.text)
                        if price and PRICE_LIMITS[gpu_type]['min'] <= price <= PRICE_LIMITS[gpu_type]['max']:
                            return True, price, product_url, title
        return False, None, None, None
    except Exception as e:
        logging.error(f"Amazon check failed for {gpu_type}: {e}")
        return False, None, None, None

def check_bestbuy(gpu_type):
    try:
        response = retry_request(URLS[gpu_type]['BestBuy'])
        if not response:
            return False, None, None, None
        soup = BeautifulSoup(response.text, 'html.parser')
        for item in soup.find_all('li', {'class': 'sku-item'}):
            title_elem = item.find('h4', {'class': 'sku-title'})
            if not title_elem:
                continue
            title = title_elem.text.strip()
            if not is_target_gpu(title, gpu_type):
                logging.debug(f"Skipping non-target GPU on Best Buy: {title}")
                continue
            add_to_cart = item.find('button', {'class': 'add-to-cart-button'})
            if add_to_cart and 'btn-disabled' not in add_to_cart.get('class', []):
                link = item.find('a', {'class': 'image-link'})
                if link:
                    product_url = 'https://www.bestbuy.com' + link['href']
                    price_div = item.find('div', {'class': 'priceView-hero-price'})
                    if price_div:
                        price = extract_price(price_div.text)
                        if price and PRICE_LIMITS[gpu_type]['min'] <= price <= PRICE_LIMITS[gpu_type]['max']:
                            return True, price, product_url, title
        return False, None, None, None
    except Exception as e:
        logging.error(f"BestBuy check failed for {gpu_type}: {e}")
        return False, None, None, None

def check_newegg(gpu_type):
    try:
        response = retry_request(URLS[gpu_type]['Newegg'])
        if not response:
            return False, None, None, None
        soup = BeautifulSoup(response.text, 'html.parser')
        for item in soup.find_all('div', {'class': 'item-container'}):
            title_elem = item.find('a', {'class': 'item-title'})
            if not title_elem:
                continue
            title = title_elem.text.strip()
            if not is_target_gpu(title, gpu_type):
                logging.debug(f"Skipping non-target GPU on Newegg: {title}")
                continue
            if "Add to Cart" in item.text or item.find('button', {'title': 'Add to cart'}):
                link = item.find('a', {'class': 'item-title'})
                if link:
                    product_url = link['href']
                    price_span = item.find('li', {'class': 'price-current'})
                    if price_span:
                        price = extract_price(price_span.text)
                        if price and PRICE_LIMITS[gpu_type]['min'] <= price <= PRICE_LIMITS[gpu_type]['max']:
                            return True, price, product_url, title
        return False, None, None, None
    except Exception as e:
        logging.error(f"Newegg check failed for {gpu_type}: {e}")
        return False, None, None, None

def main():
    logging.info("Starting GPU stock checker bot (RX 9070 XT: $599-$699, RTX 5070/5070 Ti: $599-$799)...")
    in_stock = {
        'AMD': {'Amazon': False, 'BestBuy': False, 'Newegg': False},
        'Nvidia': {'Amazon': False, 'BestBuy': False, 'Newegg': False}
    }
    failure_counts = {
        'AMD': {'Amazon': 0, 'BestBuy': 0, 'Newegg': 0},
        'Nvidia': {'Amazon': 0, 'BestBuy': 0, 'Newegg': 0}
    }
    max_failures = 10
    
    while True:
        # Check AMD GPUs
        if failure_counts['AMD']['Amazon'] < max_failures:
            amd_amazon_stock, amd_amazon_price, amd_amazon_url, amd_amazon_title = check_amazon('AMD')
            if amd_amazon_stock:
                message = f"RX 9070 XT in stock at Amazon for ${amd_amazon_price:.2f}! {amd_amazon_url} ({amd_amazon_title})"
                send_imessage(message)
                in_stock['AMD']['Amazon'] = True
                failure_counts['AMD']['Amazon'] = 0
            elif amd_amazon_price is None:
                failure_counts['AMD']['Amazon'] += 1
                if failure_counts['AMD']['Amazon'] == max_failures:
                    logging.warning("Amazon AMD skipped due to repeated failures.")
            else:
                failure_counts['AMD']['Amazon'] = 0

        if failure_counts['AMD']['BestBuy'] < max_failures:
            amd_bestbuy_stock, amd_bestbuy_price, amd_bestbuy_url, amd_bestbuy_title = check_bestbuy('AMD')
            if amd_bestbuy_stock and not in_stock['AMD']['BestBuy']:
                message = f"RX 9070 XT in stock at Best Buy for ${amd_bestbuy_price:.2f}! {amd_bestbuy_url} ({amd_bestbuy_title})"
                send_imessage(message)
                in_stock['AMD']['BestBuy'] = True
                failure_counts['AMD']['BestBuy'] = 0
            elif amd_bestbuy_price is None:
                failure_counts['AMD']['BestBuy'] += 1
                if failure_counts['AMD']['BestBuy'] == max_failures:
                    logging.warning("Best Buy AMD skipped due to repeated failures.")
            else:
                failure_counts['AMD']['BestBuy'] = 0

        if failure_counts['AMD']['Newegg'] < max_failures:
            amd_newegg_stock, amd_newegg_price, amd_newegg_url, amd_newegg_title = check_newegg('AMD')
            if amd_newegg_stock and not in_stock['AMD']['Newegg']:
                message = f"RX 9070 XT in stock at Newegg for ${amd_newegg_price:.2f}! {amd_newegg_url} ({amd_newegg_title})"
                send_imessage(message)
                in_stock['AMD']['Newegg'] = True
                failure_counts['AMD']['Newegg'] = 0
            elif amd_newegg_price is None:
                failure_counts['AMD']['Newegg'] += 1
                if failure_counts['AMD']['Newegg'] == max_failures:
                    logging.warning("Newegg AMD skipped due to repeated failures.")
            else:
                failure_counts['AMD']['Newegg'] = 0

        # Check Nvidia GPUs
        if failure_counts['Nvidia']['Amazon'] < max_failures:
            nvidia_amazon_stock, nvidia_amazon_price, nvidia_amazon_url, nvidia_amazon_title = check_amazon('Nvidia')
            if nvidia_amazon_stock:
                message = f"RTX 5070/5070 Ti in stock at Amazon for ${nvidia_amazon_price:.2f}! {nvidia_amazon_url} ({nvidia_amazon_title})"
                send_imessage(message)
                in_stock['Nvidia']['Amazon'] = True
                failure_counts['Nvidia']['Amazon'] = 0
            elif nvidia_amazon_price is None:
                failure_counts['Nvidia']['Amazon'] += 1
                if failure_counts['Nvidia']['Amazon'] == max_failures:
                    logging.warning("Amazon Nvidia skipped due to repeated failures.")
            else:
                failure_counts['Nvidia']['Amazon'] = 0

        if failure_counts['Nvidia']['BestBuy'] < max_failures:
            nvidia_bestbuy_stock, nvidia_bestbuy_price, nvidia_bestbuy_url, nvidia_bestbuy_title = check_bestbuy('Nvidia')
            if nvidia_bestbuy_stock and not in_stock['Nvidia']['BestBuy']:
                message = f"RTX 5070/5070 Ti in stock at Best Buy for ${nvidia_bestbuy_price:.2f}! {nvidia_bestbuy_url} ({nvidia_bestbuy_title})"
                send_imessage(message)
                in_stock['Nvidia']['BestBuy'] = True
                failure_counts['Nvidia']['BestBuy'] = 0
            elif nvidia_bestbuy_price is None:
                failure_counts['Nvidia']['BestBuy'] += 1
                if failure_counts['Nvidia']['BestBuy'] == max_failures:
                    logging.warning("Best Buy Nvidia skipped due to repeated failures.")
            else:
                failure_counts['Nvidia']['BestBuy'] = 0

        if failure_counts['Nvidia']['Newegg'] < max_failures:
            nvidia_newegg_stock, nvidia_newegg_price, nvidia_newegg_url, nvidia_newegg_title = check_newegg('Nvidia')
            if nvidia_newegg_stock and not in_stock['Nvidia']['Newegg']:
                message = f"RTX 5070/5070 Ti in stock at Newegg for ${nvidia_newegg_price:.2f}! {nvidia_newegg_url} ({nvidia_newegg_title})"
                send_imessage(message)
                in_stock['Nvidia']['Newegg'] = True
                failure_counts['Nvidia']['Newegg'] = 0
            elif nvidia_newegg_price is None:
                failure_counts['Nvidia']['Newegg'] += 1
                if failure_counts['Nvidia']['Newegg'] == max_failures:
                    logging.warning("Newegg Nvidia skipped due to repeated failures.")
            else:
                failure_counts['Nvidia']['Newegg'] = 0

        logging.info(f"Checked all sites. Failures: AMD(Amazon={failure_counts['AMD']['Amazon']}, BestBuy={failure_counts['AMD']['BestBuy']}, Newegg={failure_counts['AMD']['Newegg']}), Nvidia(Amazon={failure_counts['Nvidia']['Amazon']}, BestBuy={failure_counts['Nvidia']['BestBuy']}, Newegg={failure_counts['Nvidia']['Newegg']})")
        
        sleep_time = random.uniform(50, 70)
        logging.info(f"Waiting {sleep_time:.2f} seconds before next check...")
        time.sleep(sleep_time)

if __name__ == "__main__":
    main()
