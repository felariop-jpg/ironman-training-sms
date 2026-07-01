"""
Daily IRONMAN 70.3 training SMS (Whoop-only).

Pulls recent Whoop recovery/sleep/strain/workout data, hands it to Claude with
race-specific context, and texts you the result via Twilio.

Whoop rotates its refresh token every time it's used, so this script also pushes
the newly-issued refresh token back into the GitHub repo secret so the next run
still works.
"""
import os
import sys
import json
import base64
import datetime
import requests
from nacl import encoding, public  # from the pynacl package

# ---- Race context: edit this if your race details change ----
RACE_NAME = "IRONMAN 70.3 Ohio (Sandusky)"
RACE_DATE = datetime.date(2026, 7, 19)

# ---- Secrets / env vars ----
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
TWILIO_ACCOUNT_SID = os.environ["TWILIO_ACCOUNT_SID"]
TWILIO_AUTH_TOKEN = os.environ["TWILIO_AUTH_TOKEN"]
TWILIO_FROM_NUMBER = os.environ["TWILIO_FROM_NUMBER"]
TWILIO_TO_NUMBER = os.environ["TWILIO_TO_NUMBER"]

WHOOP_CLIENT_ID = os.environ["WHOOP_CLIENT_ID"]
WHOOP_CLIENT_SECRET = os.environ["WHOOP_CLIENT_SECRET"]
WHOOP_REFRESH_TOKEN = os.environ["WHOOP_REFRESH_TOKEN"]

GH_PAT = os.environ["GH_PAT"]    # fine-grained PAT, "Secrets: write" on this repo only
GH_REPO = os.environ["GH_REPO"]  # e.g. "yourusername/ironman-training-sms"


def _parse_iso(ts: str):
    if not ts:
        return None
    return datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))


# ---------------- Whoop ----------------

def whoop_refresh() -> tuple:
    """Returns (access_token, new_refresh_token)."""
    r = requests.post(
        "https://api.prod.whoop.com/oauth/oauth2/token",
        data={
            "grant_type": "refresh_token",
            "client_id": WHOOP_CLIENT_ID,
            "client_secret": WHOOP_CLIENT_SECRET,
            "refresh_token": WHOOP_REFRESH_TOKEN,
            "scope": "offline",
        },
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    return data["access_token"], data.get("refresh_token", WHOOP_REFRESH_TOKEN)


def whoop_recent(access_token: str, days: int = 8) -> dict:
    start = (datetime.datetime.utcnow() - datetime.timedelta(days=days)).isoformat() + "Z"
    headers = {"Authorization": f"Bearer {access_token}"}

    def get(path):
        r = requests.get(
            f"https://api.prod.whoop.com/developer/v2/{path}",
            headers=headers,
            params={"start": start, "limit": 10},
            timeout=30,
        )
        r.raise_for_status()
        return r.json().get("records", [])

    recovery = get("recovery")
    sleep = get("activity/sleep")
    cycles = get("cycle")
    workouts = get("activity/workout")

    recovery_summary = []
    for rec in recovery[:5]:
        score = rec.get("score") or {}
        recovery_summary.append({
            "date": (rec.get("created_at") or "")[:10],
            "recovery_pct": score.get("recovery_score"),
            "resting_hr": score.get("resting_heart_rate"),
            "hrv_ms": score.get("hrv_rmssd_milli"),
        })

    sleep_summary = []
    for s in sleep[:5]:
        score = s.get("score") or {}
        sleep_summary.append({
            "date": (s.get("start") or "")[:10],
            "sleep_performance_pct": score.get("sleep_performance_percentage"),
        })

    strain_summary = []
    for c in cycles[:5]:
        score = c.get("score") or {}
        strain_summary.append({
            "date": (c.get("start") or "")[:10],
            "strain": score.get("strain"),
        })

    workout_summary = []
    for w in workouts[:8]:
        score = w.get("score") or {}
        start_dt = _parse_iso(w.get("start"))
        end_dt = _parse_iso(w.get("end"))
        duration_min = (
            round((end_dt - start_dt).total_seconds() / 60, 1)
            if start_dt and end_dt else None
        )
        workout_summary.append({
            "date": (w.get("start") or "")[:10],
            "sport": w.get("sport_name"),
            "duration_min": duration_min,
            "strain": score.get("strain"),
            "avg_hr": score.get("average_heart_rate"),
            "max_hr": score.get("max_heart_rate"),
            "kilojoules": score.get("kilojoule"),
        })

    return {
        "recovery": recovery_summary,
        "sleep": sleep_summary,
        "strain": strain_summary,
        "workouts": workout_summary,
    }


# ---------------- Claude ----------------

def build_prompt(whoop_data: dict, days_out: int) -> str:
    return f"""You are my triathlon coach texting me first thing in the morning,
{days_out} days out from {RACE_NAME} on {RACE_DATE.isoformat()}.

Here is my last ~8 days of Whoop data (JSON): recovery scores, HRV, resting heart
rate, sleep performance, daily strain, and individual workouts (sport, duration,
strain, heart rate):
{json.dumps(whoop_data, indent=2)}

Write a short morning text (under 500 characters) that:
- Tells me plainly what today should look like: a specific workout type, intensity, and
  duration, or explicit rest, based on my recent training load (from strain and workouts)
  and recovery/HRV/sleep trend.
- If recovery or HRV looks low or trending down, prioritize rest or an easy day and say so
  clearly. Don't push through data that suggests I need rest.
- I'm {days_out} days from race day, so adjust for taper: reduce volume and intensity as
  race day approaches, prioritize sleep, avoid new stress, don't introduce anything I
  haven't already trained.
- If there's a specific race-week task worth flagging (gear check, nutrition rehearsal,
  course familiarization, travel logistics) given how many days out I am, mention it in
  one line.
- Sound like a real coach who knows my data, not a generic fitness app notification.
- This is training guidance based on data trends, not medical advice. If something looks
  like a real red flag (resting HR spiking hard, recovery cratering multiple days running),
  say so plainly and suggest checking in with a doctor rather than prescribing a fix.

No preamble, just the text message itself."""


def generate_message(whoop_data: dict, days_out: int) -> str:
    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": "claude-sonnet-4-6",
            "max_tokens": 300,
            "messages": [{"role": "user", "content": build_prompt(whoop_data, days_out)}],
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    return "".join(b["text"] for b in data["content"] if b.get("type") == "text").strip()


# ---------------- Twilio ----------------

def send_sms(body: str) -> None:
    url = f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_ACCOUNT_SID}/Messages.json"
    r = requests.post(
        url,
        auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN),
        data={"From": TWILIO_FROM_NUMBER, "To": TWILIO_TO_NUMBER, "Body": body},
        timeout=30,
    )
    r.raise_for_status()


# ---------------- GitHub secret update (Whoop's refresh token rotates) ----------------

def update_github_secret(secret_name: str, secret_value: str) -> None:
    headers = {"Authorization": f"Bearer {GH_PAT}", "Accept": "application/vnd.github+json"}

    key_resp = requests.get(
        f"https://api.github.com/repos/{GH_REPO}/actions/secrets/public-key",
        headers=headers, timeout=30,
    )
    key_resp.raise_for_status()
    key_data = key_resp.json()

    public_key = public.PublicKey(key_data["key"].encode("utf-8"), encoding.Base64Encoder())
    sealed_box = public.SealedBox(public_key)
    encrypted = sealed_box.encrypt(secret_value.encode("utf-8"))
    encrypted_b64 = base64.b64encode(encrypted).decode("utf-8")

    put_resp = requests.put(
        f"https://api.github.com/repos/{GH_REPO}/actions/secrets/{secret_name}",
        headers=headers,
        json={"encrypted_value": encrypted_b64, "key_id": key_data["key_id"]},
        timeout=30,
    )
    put_resp.raise_for_status()


# ---------------- Main ----------------

def main() -> int:
    try:
        days_out = (RACE_DATE - datetime.date.today()).days

        whoop_token, new_whoop_refresh = whoop_refresh()
        whoop_data = whoop_recent(whoop_token)

        if new_whoop_refresh != WHOOP_REFRESH_TOKEN:
            update_github_secret("WHOOP_REFRESH_TOKEN", new_whoop_refresh)
            print("Updated WHOOP_REFRESH_TOKEN secret (Whoop rotated it).")

        message = generate_message(whoop_data, days_out)
        print(f"Generated message ({len(message)} chars):\n{message}")

        send_sms(message)
        print("SMS sent.")
        return 0
    except requests.HTTPError as e:
        print(f"HTTP error: {e.response.status_code} {e.response.text}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
