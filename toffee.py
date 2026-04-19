# ===================================================
# Toffee Live TV Playlist Generator - FINAL
# Sports channels with separate cookies
# ===================================================

import requests
import json
import time
import re
import os
import hashlib
import secrets
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from Crypto.Cipher import AES

# ========== কনফিগারেশন ==========
SECRET_KEY = "06e63248b1b56d5789ba0b047f548eba"
SECRET_KEY_BYTES = SECRET_KEY.encode('utf-8')

DEVICE_REGISTER_URL = "https://prod-services.toffeelive.com/sms/v1/device/register"
CONTENT_BASE = "https://content-prod.services.toffeelive.com/toffee/BD/DK/android-mobile"
PLAYBACK_BASE = "https://entitlement-prod.services.toffeelive.com/toffee/BD/DK/android-mobile/playback"
ALL_LIVE_TV_URL = f"{CONTENT_BASE}/rail/generic/editorial-dynamic?filters=v_type:channels;subType:Live_TV&page={{page}}"

SLUG_FILE = "slug.txt"
OUTPUT_FILES = ["ottnavigator.m3u", "nsplayer.m3u", "toffee.json"]

SPORTS_PATTERNS = ["match-", "bdvsnz", "epl", "bfl", "sports", "cricket", "icc", "vs"]

# স্পোর্টস চ্যানেলের জন্য আলাদা ইউজার এজেন্ট
SPORTS_USER_AGENT = "Toffee/8.8.0 (Linux;Android 7.1.2) ExoPlayerLib/2.18.6"
NORMAL_USER_AGENT = "okhttp/5.1.0"

# ========== গ্লোবাল ভেরিয়েবল ==========
slug_mapping = {}

# ========== ইউটিলিটি ফাংশন ==========
def generate_random_hex(bytes_count: int = 16) -> str:
    return secrets.token_hex(bytes_count)

def md5_hash(data: str) -> str:
    return hashlib.md5(data.encode()).hexdigest()

def generate_device_id() -> str:
    return md5_hash(SECRET_KEY + generate_random_hex(16))[:32]

def generate_nonce() -> str:
    return generate_random_hex(16)

def aes_ecb_encrypt(plain_text: str) -> str:
    plain_bytes = plain_text.encode('utf-8')
    pad_len = 16 - (len(plain_bytes) % 16)
    plain_bytes += bytes([pad_len]) * pad_len
    cipher = AES.new(SECRET_KEY_BYTES, AES.MODE_ECB)
    return cipher.encrypt(plain_bytes).hex()

def generate_hash(payload: dict) -> str:
    return aes_ecb_encrypt(json.dumps(payload, separators=(',', ':')))

def is_sports_channel(title: str, slug: str = "") -> bool:
    text = (title + " " + slug).lower()
    return any(p in text for p in SPORTS_PATTERNS)

def get_logo(channel: Dict) -> str:
    images = channel.get("images", [])
    for img in images:
        if img.get("ratio") == "1:1":
            path = img.get("path", "")
            if path:
                if path.startswith("http"):
                    return path
                return f"https://assets-prod.services.toffeelive.com/f_png,w_300,q_85/{path}"
    if images:
        path = images[0].get("path", "")
        if path:
            return f"https://assets-prod.services.toffeelive.com/f_png,w_300,q_85/{path}"
    return ""

def get_user_agent(title: str, slug: str) -> str:
    """স্পোর্টস চ্যানেলের জন্য আলাদা user-agent"""
    return SPORTS_USER_AGENT if is_sports_channel(title, slug) else NORMAL_USER_AGENT

# ========== Slug ফাইল ম্যানেজমেন্ট ==========
def load_slug_mapping() -> Dict:
    mapping = {}
    if os.path.exists(SLUG_FILE):
        with open(SLUG_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and '=' in line and not line.startswith('#'):
                    parts = line.split('=', 1)
                    channel = parts[0].strip()
                    slug = parts[1].strip()
                    if channel and slug:
                        mapping[channel] = slug
    return mapping

def save_slug_mapping(mapping: Dict):
    with open(SLUG_FILE, 'w', encoding='utf-8') as f:
        f.write("# Toffee Channel Slug Mapping\n")
        f.write("# Format: Channel Name = slug\n\n")
        for channel, slug in sorted(mapping.items()):
            f.write(f"{channel} = {slug}\n")

# ========== ডিভাইস রেজিস্ট্রেশন ==========
def register_device() -> Optional[str]:
    device_id = generate_device_id()
    nonce = generate_nonce()
    
    payload = {
        "provider": "toffee", "device_id": device_id, "type": "mobile",
        "os": "android", "os_version": "10", "app_version": "8.8.0", "country": "BD"
    }
    hash_value = generate_hash(payload)
    
    headers = {
        "Host": "prod-services.toffeelive.com", "Content-Type": "application/json; charset=utf-8",
        "Accept-Encoding": "gzip", "User-Agent": "okhttp/5.1.0", "Connection": "Keep-Alive"
    }
    
    try:
        resp = requests.post(f"{DEVICE_REGISTER_URL}?nonce={nonce}&hash={hash_value}", 
                            headers=headers, json=payload, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("success") and "data" in data:
                return data["data"]["access"]
    except:
        pass
    return None

def get_headers(access_token: str) -> Dict:
    return {
        "Authorization": f"Bearer {access_token}",
        "User-Agent": "okhttp/5.1.0",
        "Accept": "application/json",
        "Content-Type": "application/json"
    }

def get_playback_data(content_id: str, access_token: str) -> Tuple[Optional[str], Optional[str]]:
    """প্লেব্যাক API থেকে stream_url ও cookie বের করে"""
    try:
        resp = requests.post(f"{PLAYBACK_BASE}/{content_id}", headers=get_headers(access_token), json={}, timeout=15)
        if resp.status_code != 200:
            return None, None
        
        data = resp.json()
        stream_url = None
        if "playbackDetails" in data and data["playbackDetails"].get("data"):
            stream_url = data["playbackDetails"]["data"][0].get("url")
        elif "stream_url" in data:
            stream_url = data["stream_url"]
        elif "url" in data:
            stream_url = data["url"]
        
        if not stream_url:
            return None, None
        
        cookie = None
        if "set-cookie" in resp.headers:
            match = re.search(r'(Edge-Cache-Cookie=[^;]+)', resp.headers["set-cookie"])
            if match:
                cookie = match.group(1)
        
        return stream_url, cookie
    except:
        return None, None

def get_stream_url_from_slug(title: str, slug: str) -> str:
    """slug থেকে সঠিক CDN ব্যবহার করে URL তৈরি করে"""
    if is_sports_channel(title, slug):
        return f"https://mprod-cdn.toffeelive.com/live/{slug}/index.m3u8"
    return f"https://bldcmprod-cdn.toffeelive.com/cdn/live/{slug}/playlist.m3u8"

def fetch_all_channels(access_token: str) -> List[Dict]:
    channels = []
    headers = get_headers(access_token)
    for page in range(1, 9):
        try:
            resp = requests.get(ALL_LIVE_TV_URL.format(page=page), headers=headers, timeout=15)
            if resp.status_code != 200:
                break
            items = resp.json().get('list', [])
            if not items:
                break
            for item in items:
                if item.get('v_type') == 'channels' and item.get('subType') == 'Live_TV' and item.get('id'):
                    channels.append(item)
            time.sleep(0.3)
        except:
            break
    return channels

# ========== প্লেলিস্ট জেনারেটর ==========
def generate_playlists(channels: List[Dict], access_token: str):
    ott_lines = ["#EXTM3U"]
    ns_list = []
    toffee_channels = []
    
    api_success = 0
    fallback_success = 0
    sports_count = 0
    
    for ch in channels:
        title = ch.get('title')
        ch_id = ch.get('id')
        if not title or not ch_id:
            continue
        
        logo = get_logo(ch)
        
        # প্রথমে API চেষ্টা (এখান থেকে কুকি ও স্ট্রিম ইউআরএল আসবে)
        stream_url, cookie = get_playback_data(ch_id, access_token)
        
        # API ব্যর্থ হলে slug ম্যাপিং ব্যবহার
        if not stream_url and title in slug_mapping:
            slug = slug_mapping[title]
            stream_url = get_stream_url_from_slug(title, slug)
            fallback_success += 1
            if is_sports_channel(title, slug):
                sports_count += 1
        elif stream_url:
            api_success += 1
            if is_sports_channel(title, ""):
                sports_count += 1
        else:
            continue
        
        # সঠিক user-agent নির্বাচন
        user_agent = get_user_agent(title, slug_mapping.get(title, ""))
        
        # OTT M3U লাইন
        ott_lines.append(f'#EXTINF:-1 group-title="Live TV" tvg-logo="{logo}" tvg-name="{title}", {title}')
        ott_lines.append(f'#EXTVLCOPT:http-user-agent={user_agent}')
        if cookie:
            ott_lines.append(f'#EXTHTTP:{{"cookie":"{cookie}"}}')
        ott_lines.append(stream_url)
        ott_lines.append('')
        
        # NS Player JSON
        ns_list.append({
            "category": "Live TV",
            "name": title,
            "link": stream_url,
            "logo": logo,
            "cookie": cookie or "",
            "user_agent": user_agent
        })
        
        # Toffee JSON
        toffee_channels.append({
            "category_name": "Live TV",
            "name": title,
            "link": stream_url,
            "headers": {"cookie": cookie or ""},
            "logo": logo
        })
    
    # ফাইল সেভ
    with open("ottnavigator.m3u", "w", encoding='utf-8') as f:
        f.write('\n'.join(ott_lines))
    
    with open("nsplayer.m3u", "w", encoding='utf-8') as f:
        json.dump(ns_list, f, indent=2, ensure_ascii=False)
    
    with open("toffee.json", "w", encoding='utf-8') as f:
        json.dump({
            "name": "Toffee Live TV",
            "owner": "GitHub: kgkaku",
            "channels_amount": len(toffee_channels),
            "updated_on": datetime.now().strftime("%d-%m-%Y at %I:%M:%S %p"),
            "channels": toffee_channels
        }, f, indent=2, ensure_ascii=False)
    
    return len(toffee_channels), api_success, fallback_success, sports_count

# ========== মেইন ==========
def main():
    print("=" * 50)
    print("Toffee Live TV Playlist Generator")
    print("Sports channels with separate cookies")
    print("=" * 50)
    
    global slug_mapping
    slug_mapping = load_slug_mapping()
    print(f"✓ Loaded {len(slug_mapping)} slug mappings")
    
    print("\n🔐 Registering device...")
    access_token = register_device()
    if not access_token:
        print("❌ Registration failed!")
        return
    print("✓ Device registered")
    
    print("\n📺 Fetching channels...")
    channels = fetch_all_channels(access_token)
    print(f"✓ Found {len(channels)} channels")
    
    print("\n📝 Generating playlists...")
    total, api, fallback, sports = generate_playlists(channels, access_token)
    
    # নতুন চ্যানেল পাওয়া গেলে slug.txt আপডেট
    new_mappings = {}
    for ch in channels:
        title = ch.get('title')
        if title and title not in slug_mapping:
            ch_id = ch.get('id')
            if ch_id:
                stream_url, _ = get_playback_data(ch_id, access_token)
                if stream_url:
                    match = re.search(r'/(?:live|cdn/live)/([^/]+)/', stream_url)
                    if match:
                        slug = match.group(1)
                        new_mappings[title] = slug
    
    if new_mappings:
        slug_mapping.update(new_mappings)
        save_slug_mapping(slug_mapping)
        print(f"\n✓ Added {len(new_mappings)} new slug mappings")
    
    print("\n" + "=" * 50)
    print(f"✓ Complete! {total}/{len(channels)} channels")
    print(f"  • API success: {api}")
    print(f"  • Fallback: {fallback}")
    print(f"  • Sports channels: {sports}")
    print("=" * 50)
    
    for f in OUTPUT_FILES:
        if os.path.exists(f):
            print(f"✓ {f}")

if __name__ == "__main__":
    main()
