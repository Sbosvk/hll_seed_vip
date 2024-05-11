import json
from pathlib import Path
from datetime import datetime, timedelta, timezone

def load_vip_data(file_path):
    if Path(file_path).exists():
        with open(file_path, 'r') as file:
            return json.load(file)
    else:
        return {"players": []}

def save_vip_data(data, file_path):
    with open(file_path, 'w') as file:
        json.dump(data, file, indent=4)

def add_vip_player(steam_id, name, file_path, vip_duration):
    data = load_vip_data(file_path)
    now = datetime.now(timezone.utc)
    vip_expires = now + timedelta(days=vip_duration)  # Use the configured duration
    player_data = {
        "steam_id": steam_id,
        "name": name,
        "vip_granted": now.isoformat(),
        "vip_expires": vip_expires.isoformat()
    }
    # Update if existing, add if new
    for player in data["players"]:
        if player["steam_id"] == steam_id:
            player.update(player_data)
            break
    else:
        data["players"].append(player_data)
    
    save_vip_data(data, file_path)

def is_eligible_for_vip(steam_id, file_path, cooldown_days):
    data = load_vip_data(file_path)
    for player in data["players"]:
        if player["steam_id"] == steam_id:
            last_vip_granted = datetime.fromisoformat(player["vip_granted"])
            if (datetime.now(timezone.utc) - last_vip_granted) > timedelta(days=cooldown_days):
                return True
            break
    return False

def get_last_vip_granted_date(file_path):
    data = load_vip_data(file_path)
    last_dates = [datetime.fromisoformat(p['vip_granted']) for p in data['players']]
    return max(last_dates) if last_dates else None